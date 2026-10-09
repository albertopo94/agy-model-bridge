"""Pure transformation functions between OpenAI and Google Cloud Code Assist schemas."""

import hashlib
import json
import threading
import time
from typing import Any
import uuid

DUMMY_THOUGHT_SIGNATURE: str = "context_engineering_is_the_way_to_go"
_THOUGHT_SIG_CACHE: dict[str, str] = {}
_THOUGHT_SIG_LOCK = threading.Lock()
_THOUGHT_SIG_MAX = 2048


def _hash_args(args: Any) -> str:
    """Computes a deterministic SHA-256 hash for tool arguments."""
    raw = ""
    if isinstance(args, dict):
        try:
            raw = json.dumps(args, sort_keys=True)
        except Exception:
            raw = str(args)
    elif isinstance(args, str):
        try:
            parsed = json.loads(args)
            if isinstance(parsed, dict):
                raw = json.dumps(parsed, sort_keys=True)
            else:
                raw = args
        except Exception:
            raw = args
    elif args is not None:
        raw = str(args)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cache_thought_signature(
    call_id: str | None = None,
    signature: str | None = None,
    name: str | None = None,
    args: Any = None,
) -> None:
    """Stores a thought signature associated with a tool call ID and/or function signature."""
    if not signature:
        return
    with _THOUGHT_SIG_LOCK:
        while len(_THOUGHT_SIG_CACHE) >= _THOUGHT_SIG_MAX:
            first_key = next(iter(_THOUGHT_SIG_CACHE))
            _THOUGHT_SIG_CACHE.pop(first_key, None)
        if call_id:
            _THOUGHT_SIG_CACHE[f"id:{call_id}"] = signature
        if name:
            _THOUGHT_SIG_CACHE[f"call:{name}:{_hash_args(args)}"] = signature


def get_thought_signature(
    call_id: str | None = None,
    name: str | None = None,
    args: Any = None,
) -> str:
    """Retrieves a cached thought signature, or returns the documented skip-validation sentinel."""
    with _THOUGHT_SIG_LOCK:
        if call_id:
            sig = _THOUGHT_SIG_CACHE.get(f"id:{call_id}")
            if sig:
                return sig
        if name:
            sig = _THOUGHT_SIG_CACHE.get(f"call:{name}:{_hash_args(args)}")
            if sig:
                return sig
    return DUMMY_THOUGHT_SIGNATURE


_TOOL_NAME_CACHE: dict[str, str] = {}
_TOOL_NAME_LOCK = threading.Lock()
_TOOL_NAME_MAX = 2048


def cache_tool_name(call_id: str, name: str) -> None:
    """Stores a tool function name associated with a tool call ID."""
    if not call_id or not name:
        return
    with _TOOL_NAME_LOCK:
        if len(_TOOL_NAME_CACHE) >= _TOOL_NAME_MAX:
            first_key = next(iter(_TOOL_NAME_CACHE))
            _TOOL_NAME_CACHE.pop(first_key, None)
        _TOOL_NAME_CACHE[call_id] = name


def get_tool_name(call_id: str) -> str | None:
    """Retrieves a cached tool function name for a tool call ID."""
    if not call_id:
        return None
    with _TOOL_NAME_LOCK:
        return _TOOL_NAME_CACHE.get(call_id)


from bridge.client import (
    AuthenticationError,
    BridgeError,
    CapacityExhaustedError,
    ForbiddenError,
    InvalidRequestError,
    ModelNotFoundError,
    RateLimitError,
)

UNSUPPORTED_SCHEMA_KEYS = frozenset({
    "$schema",
    "$id",
    "$ref",
    "$defs",
    "$comment",
    "definitions",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "patternProperties",
    "unevaluatedProperties",
    "unevaluatedItems",
    "if",
    "then",
    "else",
    "contentEncoding",
    "contentMediaType",
    "contentSchema",
    "dependentRequired",
    "dependentSchemas",
    "dependencies",
    "additionalProperties",
    "examples",
    "const",
    "readOnly",
    "writeOnly",
    "uniqueItems",
    "not",
    "allOf",
    "oneOf",
    "prefixItems",
    "contains",
    "minContains",
    "maxContains",
    "propertyNames",
    "multipleOf",
    "deprecated",
})


def _resolve_pointer(root: Any, ref: str) -> Any:
    """Best-effort JSON pointer resolution against schema root."""
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return None
    node = root
    for raw_segment in ref[2:].split("/"):
        if not isinstance(node, dict):
            return None
        segment = raw_segment.replace("~1", "/").replace("~0", "~")
        node = node.get(segment)
    return node


def sanitize_schema_for_gemini(
    schema: Any,
    inside_properties_map: bool = False,
    root: Any = None,
    expanding: frozenset[str] | None = None,
) -> Any:
    """Recursively sanitizes a JSON schema to ensure compatibility with Google Gemini OpenAPI 3.0 protobuf schema."""
    if root is None:
        root = schema
    if expanding is None:
        expanding = frozenset()

    if isinstance(schema, list):
        return [sanitize_schema_for_gemini(item, False, root, expanding) for item in schema]

    if not isinstance(schema, dict):
        return schema

    out: dict[str, Any] = {}
    nullable = False
    inlined: dict[str, Any] | None = None

    for key, value in schema.items():
        if inside_properties_map:
            out[key] = sanitize_schema_for_gemini(value, False, root, expanding)
            continue

        if key.lower().startswith("x-"):
            continue

        if key == "$ref" and isinstance(value, str) and value not in expanding:
            target = _resolve_pointer(root, value)
            if isinstance(target, dict):
                inlined_res = sanitize_schema_for_gemini(
                    target, False, root, expanding | {value}
                )
                if isinstance(inlined_res, dict):
                    inlined = inlined_res
            continue

        if key in UNSUPPORTED_SCHEMA_KEYS:
            continue

        if key == "type" and isinstance(value, list):
            names = [str(x) for x in value if isinstance(x, str)]
            is_null = any(n.lower() == "null" for n in names)
            concrete = next((n for n in names if n.lower() != "null"), None)
            if concrete:
                out["type"] = concrete
            if is_null:
                nullable = True
            continue

        if key == "anyOf" and isinstance(value, list) and "type" not in schema:
            concrete_subschemas: list[dict[str, Any]] = []
            for sub in value:
                if isinstance(sub, dict):
                    if sub.get("type") == "null":
                        nullable = True
                    else:
                        concrete_subschemas.append(sub)
            if concrete_subschemas:
                chosen = sanitize_schema_for_gemini(
                    concrete_subschemas[0], False, root, expanding
                )
                if isinstance(chosen, dict):
                    for ck, cv in chosen.items():
                        out.setdefault(ck, cv)
            continue

        out[key] = sanitize_schema_for_gemini(value, key == "properties", root, expanding)

    if nullable:
        out["nullable"] = True

    merged = {**inlined, **out} if inlined else out

    if inside_properties_map:
        return merged

    # Gemini Schema proto requires `items` on every ARRAY.
    # Handle tuple params (prefixItems or items list) and missing items.
    type_val = merged.get("type")
    is_array = isinstance(type_val, str) and type_val.lower() == "array"
    if is_array or "items" in merged or "prefixItems" in schema:
        members: list[Any] = []
        if isinstance(schema.get("prefixItems"), list):
            members.extend(sanitize_schema_for_gemini(schema["prefixItems"], False, root, expanding))
        single: dict[str, Any] | None = None
        if isinstance(merged.get("items"), list):
            members.extend(merged["items"])
        elif isinstance(merged.get("items"), dict):
            single = merged["items"]

        if members:
            branches = members + ([single] if single else [])
            valid_branches = [b for b in branches if isinstance(b, dict) and b]
            if len(valid_branches) == 1:
                merged["items"] = valid_branches[0]
            elif valid_branches:
                merged["items"] = {"anyOf": valid_branches}
            else:
                merged["items"] = {}
        elif single is None and (is_array or "items" in merged):
            merged["items"] = {}

    return merged


def build_thinking_config(model: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Builds Cloud Code thinkingConfig based on model heuristics and payload overrides.

    Args:
        model: Model identifier string.
        payload: Request payload dictionary which may contain client thinking overrides.

    Returns:
        A dict with thinkingConfig parameters, or None if no thinking config applies.
    """
    m = (model or "").lower()

    # Helper to clamp default thinking budget when max tokens specified
    max_tokens_val = (
        payload.get("max_tokens")
        or payload.get("maxOutputTokens")
        or payload.get("max_completion_tokens")
        or payload.get("max_output_tokens")
    )
    if max_tokens_val is None:
        gen_cfg = payload.get("generation_config") or payload.get("generationConfig")
        if isinstance(gen_cfg, dict):
            max_tokens_val = gen_cfg.get("maxOutputTokens") or gen_cfg.get("max_tokens")

    def _default_budget() -> int | None:
        if max_tokens_val is not None:
            try:
                mt = int(max_tokens_val)
                budget = min(2048, max(0, mt - 128))
                return budget if budget > 0 else None
            except (ValueError, TypeError):
                pass
        return 2048

    def _tiered_or_budget() -> dict[str, Any] | None:
        if "-medium" in m:
            return {"thinkingLevel": "MEDIUM"}
        if "-low" in m:
            return {"thinkingLevel": "LOW"}
        if "tiered" in m or "-high" in m or not m:
            return {"thinkingLevel": "HIGH"}
        b = _default_budget()
        return {"thinkingBudget": b} if b else None

    # 1. Explicit client overrides take precedence over heuristics
    if "thinkingConfig" in payload and isinstance(payload["thinkingConfig"], dict):
        cfg = payload["thinkingConfig"]
        sanitized: dict[str, Any] = {}
        if "thinkingBudget" in cfg and cfg["thinkingBudget"] is not None:
            try:
                b = int(cfg["thinkingBudget"])
                if b >= 0:
                    sanitized["thinkingBudget"] = b
            except (ValueError, TypeError):
                pass
        if "thinkingLevel" in cfg and cfg["thinkingLevel"] is not None:
            sanitized["thinkingLevel"] = str(cfg["thinkingLevel"]).upper()
        if sanitized:
            return sanitized

    output_cfg = payload.get("output_config") or payload.get("outputConfig")
    output_effort: str | None = None
    if isinstance(output_cfg, dict):
        effort_val = output_cfg.get("effort")
        if effort_val:
            effort_str = str(effort_val).strip().lower()
            if effort_str in ("high", "xhigh", "max"):
                output_effort = "HIGH"
            elif effort_str == "medium":
                output_effort = "MEDIUM"
            elif effort_str == "low":
                output_effort = "LOW"

    if "thinking" in payload:
        val = payload["thinking"]
        if isinstance(val, dict):
            t_type = str(val.get("type", "")).strip().lower()
            if t_type in ("disabled", "off", "none"):
                if m.startswith("claude-") or "claude" in m:
                    return {"thinkingLevel": "LOW"}
                return None
            if "budget_tokens" in val and val["budget_tokens"] is not None:
                try:
                    b = int(val["budget_tokens"])
                    return {"thinkingBudget": b} if b > 0 else None
                except (ValueError, TypeError):
                    pass
            if "thinkingBudget" in val and val["thinkingBudget"] is not None:
                try:
                    b = int(val["thinkingBudget"])
                    return {"thinkingBudget": b} if b > 0 else None
                except (ValueError, TypeError):
                    pass
            if "thinkingLevel" in val and val["thinkingLevel"] is not None:
                return {"thinkingLevel": str(val["thinkingLevel"]).upper()}
            if t_type == "between_tools":
                if output_effort is not None:
                    return {"thinkingLevel": output_effort}
                return {"thinkingLevel": "LOW"}
            if t_type in ("adaptive", "auto"):
                if output_effort is not None:
                    return {"thinkingLevel": output_effort}
                return _tiered_or_budget()
            if t_type == "enabled":
                if output_effort is not None:
                    return {"thinkingLevel": output_effort}
                return _tiered_or_budget()
            # If any other dict, only extract thinkingBudget or thinkingLevel
            sanitized_thinking: dict[str, Any] = {}
            if "thinkingBudget" in val and val["thinkingBudget"] is not None:
                try:
                    b = int(val["thinkingBudget"])
                    if b >= 0:
                        sanitized_thinking["thinkingBudget"] = b
                except (ValueError, TypeError):
                    pass
            if "thinkingLevel" in val and val["thinkingLevel"] is not None:
                sanitized_thinking["thinkingLevel"] = str(val["thinkingLevel"]).upper()
            if sanitized_thinking:
                return sanitized_thinking
            if output_effort is not None:
                return {"thinkingLevel": output_effort}
            return None
        elif val is False:
            if m.startswith("claude-") or "claude" in m:
                return {"thinkingLevel": "LOW"}
            return None
        elif val is True:
            if output_effort is not None:
                return {"thinkingLevel": output_effort}
            return _tiered_or_budget()

    if output_effort is not None:
        return {"thinkingLevel": output_effort}

    effort = None
    if "reasoning_effort" in payload and payload["reasoning_effort"] is not None:
        effort = str(payload["reasoning_effort"]).strip().lower()
    elif "effort" in payload and payload["effort"] is not None:
        effort = str(payload["effort"]).strip().lower()

    if effort is not None:
        if effort in ("none", "disabled", "off"):
            if m.startswith("claude-") or "claude" in m:
                return {"thinkingLevel": "LOW"}
            return None
        if effort in ("high", "xhigh", "max"):
            return {"thinkingLevel": "HIGH"}
        elif effort == "medium":
            return {"thinkingLevel": "MEDIUM"}
        elif effort == "low":
            return {"thinkingLevel": "LOW"}

    if "thinking_budget" in payload and payload["thinking_budget"] is not None:
        b = int(payload["thinking_budget"])
        return {"thinkingBudget": b} if b > 0 else None

    # 2. Model suffix heuristics
    m = (model or "").lower()
    if "-high" in m:
        return {"thinkingLevel": "HIGH"}
    if "-medium" in m:
        return {"thinkingLevel": "MEDIUM"}
    if "-low" in m:
        return {"thinkingLevel": "LOW"}
    if "-thinking" in m:
        b = _default_budget()
        return {"thinkingBudget": b} if b else None

    return None


def resolve_model_and_thinking(
    model: str | None,
    payload: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """Resolves model name and thinkingConfig applying flash-high/auto aliasing and client overrides.

    Args:
        model: Optional model identifier string.
        payload: Request payload dictionary which may contain client thinking overrides.

    Returns:
        tuple of (resolved_model_name, thinking_config_dict_or_None)
    """
    raw_model = (model or "").strip()
    m = raw_model.lower()

    if not m or m == "auto" or m in ("gemini-3.8", "gemini-3.8-flash", "gemini-3.8-flash-high"):
        resolved_model = "gemini-3.8-flash-tiered"
        default_thinking: dict[str, Any] | None = {"thinkingLevel": "HIGH"}
    elif m == "gemini-3.8-flash-medium":
        resolved_model = "gemini-3.8-flash-tiered"
        default_thinking = {"thinkingLevel": "MEDIUM"}
    elif m == "gemini-3.8-flash-low":
        resolved_model = "gemini-3.8-flash-tiered"
        default_thinking = {"thinkingLevel": "LOW"}
    elif m == "claude-sonnet-5-5-high":
        resolved_model = "claude-sonnet-5-5"
        default_thinking = {"thinkingLevel": "HIGH"}
    elif m == "claude-sonnet-5-5-medium":
        resolved_model = "claude-sonnet-5-5"
        default_thinking = {"thinkingLevel": "MEDIUM"}
    elif m == "claude-sonnet-5-5-low":
        resolved_model = "claude-sonnet-5-5"
        default_thinking = {"thinkingLevel": "LOW"}
    elif m == "claude-sonnet-5-5":
        resolved_model = "claude-sonnet-5-5"
        default_thinking = None
    elif m == "claude-opus-5-5-high":
        resolved_model = "claude-opus-5-5"
        default_thinking = {"thinkingLevel": "HIGH"}
    elif m == "claude-opus-5-5-medium":
        resolved_model = "claude-opus-5-5"
        default_thinking = {"thinkingLevel": "MEDIUM"}
    elif m == "claude-opus-5-5-low":
        resolved_model = "claude-opus-5-5"
        default_thinking = {"thinkingLevel": "LOW"}
    elif m == "claude-opus-5-5":
        resolved_model = "claude-opus-5-5"
        default_thinking = None
    elif m == "claude-haiku-5-5-high":
        resolved_model = "claude-haiku-5-5"
        default_thinking = {"thinkingLevel": "HIGH"}
    elif m == "claude-haiku-5-5-medium":
        resolved_model = "claude-haiku-5-5"
        default_thinking = {"thinkingLevel": "MEDIUM"}
    elif m == "claude-haiku-5-5-low":
        resolved_model = "claude-haiku-5-5"
        default_thinking = {"thinkingLevel": "LOW"}
    elif m == "claude-haiku-5-5":
        resolved_model = "claude-haiku-5-5"
        default_thinking = None
    else:
        resolved_model = raw_model
        default_thinking = None

    output_cfg = payload.get("output_config") or payload.get("outputConfig")
    has_output_effort = isinstance(output_cfg, dict) and bool(output_cfg.get("effort"))

    has_payload_override = (
        ("thinkingConfig" in payload and isinstance(payload["thinkingConfig"], dict))
        or "thinking" in payload
        or "reasoning_effort" in payload
        or "effort" in payload
        or "thinking_budget" in payload
        or has_output_effort
    )

    if has_payload_override:
        thinking_cfg = build_thinking_config(resolved_model, payload)
    else:
        thinking_cfg = default_thinking if default_thinking is not None else build_thinking_config(resolved_model, payload)

    return resolved_model, thinking_cfg


def openai_to_cloudcode_request(
    openai_payload: dict[str, Any], project: str
) -> tuple[
    str,
    list[dict[str, Any]],
    dict[str, Any] | None,
    dict[str, Any] | None,
    list[dict[str, Any]] | None,
]:
    """Validates OpenAI payload, extracts model, builds Cloud Code contents, systemInstruction, generationConfig, and tools.

    Args:
        openai_payload: Raw request dictionary matching OpenAI schema.
        project: Upstream project identifier.

    Returns:
        tuple of (model_name, contents_list, system_instruction_dict_or_None, generation_config_dict_or_None, tools_list_or_None)

    Raises:
        ValueError: If model or messages are missing/invalid.
    """
    raw_model = openai_payload.get("model")
    if raw_model is not None and not isinstance(raw_model, str):
        raise ValueError("Invalid 'model' parameter: must be a string")
    model, thinking_cfg = resolve_model_and_thinking(raw_model, openai_payload)

    messages = openai_payload.get("messages")
    if not messages or not isinstance(messages, list) or len(messages) == 0:
        raise ValueError("Missing or invalid 'messages' parameter: must be a non-empty list")

    system_texts: list[str] = []
    contents: list[dict[str, Any]] = []
    tool_names_by_call_id: dict[str, str] = {}

    for msg in messages:
        if not isinstance(msg, dict):
            raise ValueError("Each message must be a dictionary")
        role = msg.get("role")
        raw_content = msg.get("content")
        if isinstance(raw_content, list):
            parts_str = []
            for item in raw_content:
                if isinstance(item, dict) and (item.get("type") == "text" or "text" in item):
                    parts_str.append(str(item.get("text") or ""))
                elif isinstance(item, str):
                    parts_str.append(item)
            content = "".join(parts_str)
        elif raw_content is None:
            content = ""
        elif isinstance(raw_content, str):
            content = raw_content
        else:
            content = str(raw_content)

        if role in ("system", "developer"):
            system_texts.append(content)
            continue
        elif role == "user":
            turn_role = "user"
            part_text = content if content and content.strip() else " "
            turn_parts = [{"text": part_text}]
        elif role == "assistant":
            turn_role = "model"
            turn_parts = []
            if content and content.strip():
                turn_parts.append({"text": content})
            tool_calls = msg.get("tool_calls")
            if tool_calls and isinstance(tool_calls, list):
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    call_id = tc.get("id") or ""
                    fn = tc.get("function") if isinstance(tc.get("function"), dict) else tc
                    fn_name = fn.get("name") or "unknown"
                    if call_id:
                        tool_names_by_call_id[call_id] = fn_name
                    args_raw = fn.get("arguments")
                    if isinstance(args_raw, dict):
                        args_dict = args_raw
                    elif isinstance(args_raw, str):
                        try:
                            args_dict = json.loads(args_raw) if args_raw.strip() else {}
                            if not isinstance(args_dict, dict):
                                args_dict = {"raw": args_dict}
                        except Exception:
                            args_dict = {"raw": args_raw} if args_raw else {}
                    else:
                        args_dict = {}
                    sig = (
                        tc.get("thoughtSignature")
                        or tc.get("thought_signature")
                        or (fn.get("thoughtSignature") if isinstance(fn, dict) else None)
                        or (fn.get("thought_signature") if isinstance(fn, dict) else None)
                        or get_thought_signature(call_id, fn_name, args_dict)
                    )
                    turn_parts.append({
                        "thoughtSignature": sig,
                        "functionCall": {"name": fn_name, "args": args_dict},
                    })
            elif msg.get("function_call") and isinstance(msg.get("function_call"), dict):
                fc = msg.get("function_call")
                fn_name = fc.get("name") or "unknown"
                call_id = msg.get("name") or ""
                if call_id:
                    tool_names_by_call_id[call_id] = fn_name
                args_raw = fc.get("arguments")
                if isinstance(args_raw, dict):
                    args_dict = args_raw
                elif isinstance(args_raw, str):
                    try:
                        args_dict = json.loads(args_raw) if args_raw.strip() else {}
                        if not isinstance(args_dict, dict):
                            args_dict = {"raw": args_dict}
                    except Exception:
                        args_dict = {"raw": args_raw} if args_raw else {}
                else:
                    args_dict = {}
                sig = (
                    fc.get("thoughtSignature")
                    or fc.get("thought_signature")
                    or get_thought_signature(call_id, fn_name, args_dict)
                )
                turn_parts.append({
                    "thoughtSignature": sig,
                    "functionCall": {"name": fn_name, "args": args_dict},
                })
            if not turn_parts:
                part_text = content if content and content.strip() else " "
                turn_parts = [{"text": part_text}]
        elif role in ("tool", "function"):
            turn_role = "user"
            call_id = msg.get("tool_call_id") or msg.get("name") or ""
            fn_name = msg.get("name") or tool_names_by_call_id.get(call_id, "tool")
            turn_parts = [{"functionResponse": {"name": fn_name, "response": {"output": content}}}]
        else:
            raise ValueError(f"Invalid role: {role}")

        if contents and contents[-1]["role"] == turn_role:
            contents[-1]["parts"].extend(turn_parts)
        else:
            contents.append({"role": turn_role, "parts": turn_parts})

    if len(contents) == 0:
        raise ValueError(
            "Missing or empty user/assistant messages: at least one message is required"
        )

    if contents[0]["role"] == "model":
        contents.insert(0, {"role": "user", "parts": [{"text": "Hello"}]})

    if contents[-1]["role"] == "model":
        contents.append({"role": "user", "parts": [{"text": "Continue"}]})

    system_instruction: dict[str, Any] | None = None
    if system_texts:
        combined_system = "\n".join(system_texts)
        if combined_system.strip():
            system_instruction = {"parts": [{"text": combined_system}]}

    gen_config: dict[str, Any] = {}
    if "temperature" in openai_payload and openai_payload["temperature"] is not None:
        gen_config["temperature"] = float(openai_payload["temperature"])

    if "max_completion_tokens" in openai_payload and openai_payload["max_completion_tokens"] is not None:
        gen_config["maxOutputTokens"] = int(openai_payload["max_completion_tokens"])
    elif "max_tokens" in openai_payload and openai_payload["max_tokens"] is not None:
        gen_config["maxOutputTokens"] = int(openai_payload["max_tokens"])

    if "top_p" in openai_payload and openai_payload["top_p"] is not None:
        gen_config["topP"] = float(openai_payload["top_p"])

    if "top_k" in openai_payload and openai_payload["top_k"] is not None:
        try:
            gen_config["topK"] = int(openai_payload["top_k"])
        except (ValueError, TypeError):
            pass

    if "stop" in openai_payload and openai_payload["stop"] is not None:
        stop_val = openai_payload["stop"]
        stop_list: list[str] = []
        if isinstance(stop_val, str):
            s_str = str(stop_val)
            if s_str != "" and (s_str.strip() != "" or "\n" in s_str or "\r" in s_str):
                stop_list = [s_str]
        elif isinstance(stop_val, list):
            stop_list = [
                str(s)
                for s in stop_val
                if s is not None
                and str(s) != ""
                and (str(s).strip() != "" or "\n" in str(s) or "\r" in str(s))
            ]
        if stop_list:
            gen_config["stopSequences"] = stop_list

    if thinking_cfg is not None:
        gen_config["thinkingConfig"] = thinking_cfg

    generation_config: dict[str, Any] | None = gen_config if gen_config else None

    # Tools translation
    raw_tools = openai_payload.get("tools")
    if raw_tools is None and "functions" in openai_payload and isinstance(openai_payload.get("functions"), list):
        raw_tools = [{"type": "function", "function": f} if isinstance(f, dict) else f for f in openai_payload["functions"]]

    tools: list[dict[str, Any]] | None = None
    if isinstance(raw_tools, list) and len(raw_tools) > 0:
        function_declarations: list[dict[str, Any]] = []
        for t in raw_tools:
            if not isinstance(t, dict):
                continue
            fn = t.get("function") if isinstance(t.get("function"), dict) else t
            name = fn.get("name")
            if not name or not isinstance(name, str):
                continue
            decl: dict[str, Any] = {"name": name}
            desc = fn.get("description")
            if desc is not None:
                decl["description"] = str(desc)
            params = fn.get("parameters")
            if params is not None and isinstance(params, dict):
                decl["parameters"] = sanitize_schema_for_gemini(params)
            else:
                decl["parameters"] = {"type": "object", "properties": {}}
            function_declarations.append(decl)
        if function_declarations:
            tools = [{"functionDeclarations": function_declarations}]

    return model, contents, system_instruction, generation_config, tools


def parse_cloudcode_sse_event(raw_line: str) -> dict[str, Any] | None:
    """Parses 'data: {...}' line into dict; returns None for heartbeats/empty lines."""
    line = raw_line.strip()
    if not line or line.startswith(":"):
        return None

    if line.startswith("data:"):
        data_str = line[5:].strip()
        if data_str == "[DONE]":
            return None
        try:
            parsed = json.loads(data_str)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None

    return None


def extract_text_delta(event_dict: dict[str, Any]) -> str | None:
    """Extracts text chunk from candidates[0].parts; drops blocks with thought: true."""
    resp_obj = (
        event_dict.get("response")
        if isinstance(event_dict.get("response"), dict)
        else event_dict
    )
    candidates = resp_obj.get("candidates")
    if not candidates or not isinstance(candidates, list) or len(candidates) == 0:
        return None

    candidate = candidates[0]
    if not isinstance(candidate, dict):
        return None

    content = candidate.get("content")
    if isinstance(content, dict):
        parts = content.get("parts")
    else:
        parts = candidate.get("parts")

    if not parts or not isinstance(parts, list):
        return None

    clean_texts: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get("thought") is True:
            continue
        text = part.get("text")
        if text:
            clean_texts.append(text)

    if clean_texts:
        return "".join(clean_texts)
    return None


def extract_thought_delta(event_dict: dict[str, Any]) -> str | None:
    """Extracts text chunk from candidates[0].parts where thought is True."""
    if not isinstance(event_dict, dict):
        return None
    resp_obj = (
        event_dict.get("response")
        if isinstance(event_dict.get("response"), dict)
        else event_dict
    )
    candidates = resp_obj.get("candidates")
    if not candidates or not isinstance(candidates, list) or len(candidates) == 0:
        return None

    candidate = candidates[0]
    if not isinstance(candidate, dict):
        return None

    content = candidate.get("content")
    if isinstance(content, dict):
        parts = content.get("parts")
    else:
        parts = candidate.get("parts")

    if not parts or not isinstance(parts, list):
        return None

    thought_texts: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get("thought") is True:
            text = part.get("text")
            if text:
                thought_texts.append(text)

    if thought_texts:
        return "".join(thought_texts)
    return None


def extract_function_calls(event_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """Extracts function calls from candidates[0].parts.

    Returns a list of dicts: [{"id": ..., "name": ..., "args": ...}]
    """
    if not isinstance(event_dict, dict):
        return []
    resp_obj = (
        event_dict.get("response")
        if isinstance(event_dict.get("response"), dict)
        else event_dict
    )
    candidates = resp_obj.get("candidates")
    if not candidates or not isinstance(candidates, list) or len(candidates) == 0:
        return []

    candidate = candidates[0]
    if not isinstance(candidate, dict):
        return []

    content = candidate.get("content")
    if isinstance(content, dict):
        parts = content.get("parts")
    else:
        parts = candidate.get("parts")

    if not parts or not isinstance(parts, list):
        return []

    calls: list[dict[str, Any]] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        fc = part.get("functionCall")
        if fc and isinstance(fc, dict):
            name = fc.get("name")
            if name:
                call_id = fc.get("id") or part.get("id") or f"toolu_{uuid.uuid4().hex[:16]}"
                args = fc.get("args")
                if args is None:
                    args = {}
                elif isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        pass
                call_info: dict[str, Any] = {
                    "id": call_id,
                    "name": name,
                    "args": args,
                }
                thought_sig = (
                    part.get("thoughtSignature")
                    or part.get("thought_signature")
                    or fc.get("thoughtSignature")
                    or fc.get("thought_signature")
                )
                if thought_sig:
                    call_info["thought_signature"] = thought_sig
                calls.append(call_info)
    return calls


def check_sse_error(event_dict: dict[str, Any]) -> None:
    """Checks if SSE event contains an error payload and raises appropriate BridgeError."""
    resp_obj = (
        event_dict.get("response")
        if isinstance(event_dict.get("response"), dict)
        else event_dict
    )
    error_obj = resp_obj.get("error")
    if not error_obj:
        return

    code = None
    message = ""
    status = ""
    if isinstance(error_obj, dict):
        code = error_obj.get("code")
        message = error_obj.get("message") or ""
        status = error_obj.get("status") or ""
    else:
        message = str(error_obj)

    err_msg = message or status or "Unknown upstream error"
    if status and status not in err_msg:
        err_msg = f"{err_msg} ({status})"

    if code == 429 or status == "RESOURCE_EXHAUSTED":
        raise RateLimitError(f"Upstream rate limit: {err_msg}")
    if code == 503 or status == "UNAVAILABLE":
        raise CapacityExhaustedError(f"Upstream capacity exhausted: {err_msg}")
    if code == 403 or status == "PERMISSION_DENIED":
        raise ForbiddenError(f"Upstream forbidden: {err_msg}")
    if code == 401 or status == "UNAUTHENTICATED":
        raise AuthenticationError(f"Upstream authentication error: {err_msg}")
    if code == 404 or status == "NOT_FOUND":
        raise ModelNotFoundError(f"Upstream model not found: {err_msg}")
    if code == 400 or status == "INVALID_ARGUMENT":
        raise InvalidRequestError(f"Upstream invalid request: {err_msg}")

    raise BridgeError(f"Upstream error ({code or 'unknown'}): {err_msg}")


def extract_finish_reason(event_dict: dict[str, Any]) -> str | None:
    """Extracts finishReason ('stop', 'length', 'content_filter') if candidate finished."""
    resp_obj = (
        event_dict.get("response")
        if isinstance(event_dict.get("response"), dict)
        else event_dict
    )
    prompt_feedback = resp_obj.get("promptFeedback") or event_dict.get("promptFeedback")
    if isinstance(prompt_feedback, dict):
        block_reason = prompt_feedback.get("blockReason")
        if block_reason:
            block_reason_str = str(block_reason).strip().upper()
            if block_reason_str not in ("BLOCK_REASON_UNSPECIFIED", "0", "UNSPECIFIED", ""):
                return "content_filter"

    candidates = resp_obj.get("candidates")
    if not candidates or not isinstance(candidates, list) or len(candidates) == 0:
        return None

    candidate = candidates[0]
    if not isinstance(candidate, dict):
        return None

    reason = candidate.get("finishReason")
    if not reason:
        return None

    reason_str = str(reason).strip().upper()
    if not reason_str or reason_str in ("FINISH_REASON_UNSPECIFIED", "0", "UNSPECIFIED"):
        return None
    if reason_str in ("STOP", "1"):
        return "stop"
    if reason_str in ("MAX_TOKENS", "LENGTH", "2"):
        return "length"
    if reason_str in (
        "SAFETY",
        "RECITATION",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "MALICIOUS",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
    ):
        return "content_filter"
    return "stop"



def extract_usage(event_dict: dict[str, Any]) -> dict[str, int] | None:
    """Translates usageMetadata into OpenAI usage format."""
    resp_obj = (
        event_dict.get("response")
        if isinstance(event_dict.get("response"), dict)
        else event_dict
    )
    metadata = resp_obj.get("usageMetadata")
    if not metadata or not isinstance(metadata, dict):
        return None

    prompt_tokens = int(metadata.get("promptTokenCount") or 0)
    candidates_tokens = int(metadata.get("candidatesTokenCount") or 0)
    total_tokens = int(metadata.get("totalTokenCount") or (prompt_tokens + candidates_tokens))

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": candidates_tokens,
        "total_tokens": total_tokens,
    }


def build_openai_chunk(
    completion_id: str,
    model: str,
    delta_text: str | None = None,
    finish_reason: str | None = None,
    usage: dict[str, int] | None = None,
    role: str | None = None,
    delta_tool_calls: list[dict[str, Any]] | None = None,
) -> str:
    """Serializes a single OpenAI SSE chunk 'data: {...}\\n\\n'."""
    delta: dict[str, Any] = {}
    if role is not None:
        delta["role"] = role
    if delta_text is not None:
        delta["content"] = delta_text
    if delta_tool_calls is not None:
        delta["tool_calls"] = delta_tool_calls

    chunk: dict[str, Any] = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    if usage is not None:
        chunk["usage"] = usage

    return f"data: {json.dumps(chunk)}\n\n"


def build_openai_completion(
    completion_id: str,
    model: str,
    full_text: str,
    usage: dict[str, int] | None = None,
    finish_reason: str = "stop",
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Constructs non-streaming OpenAI chat.completion JSON object."""
    message: dict[str, Any] = {
        "role": "assistant",
        "content": full_text if full_text or not tool_calls else None,
    }
    if tool_calls is not None:
        message["tool_calls"] = tool_calls

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason or "stop",
            }
        ],
        "usage": usage
        or {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


def build_openai_model_list(upstream_models: list[Any]) -> dict[str, Any]:
    """Constructs OpenAI model list response object."""
    models_data: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    created = 1700000000

    for item in upstream_models:
        if isinstance(item, str):
            raw_id = item
        elif isinstance(item, dict):
            raw_id = item.get("id") or item.get("name") or ""
        else:
            raw_id = ""
        if not isinstance(raw_id, str):
            raw_id = str(raw_id)
        if raw_id.startswith("models/"):
            raw_id = raw_id[7:]
        if raw_id and raw_id not in seen_ids:
            seen_ids.add(raw_id)
            models_data.append(
                {
                    "id": raw_id,
                    "slug": raw_id,
                    "display_name": raw_id,
                    "object": "model",
                    "created": created,
                    "owned_by": "google",
                }
            )

    return {"object": "list", "data": models_data, "models": models_data}


def build_openai_error_response(
    status_code: int, message: str, error_type: str
) -> tuple[int, dict[str, Any]]:
    """Generates standard OpenAI error payload and HTTP code."""
    return (
        status_code,
        {
            "error": {
                "message": message,
                "type": error_type,
                "code": status_code,
            }
        },
    )
