"""Pure transformation functions between OpenAI and Google Cloud Code Assist schemas."""

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any
from bridge.events import (
    ChatRequest as ChatRequest,
    OpenAIChatRequest as OpenAIChatRequest,
    StreamEvent as StreamEvent,
    ToolCallDelta as ToolCallDelta,
    Usage as Usage,
    append_or_merge_turn as append_or_merge_turn,
    build_system_instruction as build_system_instruction,
    build_tool_declarations as build_tool_declarations,
    check_sse_error as check_sse_error,
    normalize_turn_boundaries as normalize_turn_boundaries,
    parse_stream_event as parse_stream_event,
)
from bridge.errors import InvalidRequestError

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
        budget_val = _default_budget()
        return {"thinkingBudget": budget_val} if budget_val else None

    return None


MODEL_TIER_TABLE: dict[str, tuple[str, str | None]] = {
    # Default / empty / auto
    "": ("gemini-3.8-flash-tiered", "HIGH"),
    "auto": ("gemini-3.8-flash-tiered", "HIGH"),
    # Gemini 3.8 / flash
    "gemini-3.8": ("gemini-3.8-flash-tiered", "HIGH"),
    "gemini-3.8-flash": ("gemini-3.8-flash-tiered", "HIGH"),
    "gemini-3.8-flash-high": ("gemini-3.8-flash-tiered", "HIGH"),
    "gemini-3.8-flash-medium": ("gemini-3.8-flash-tiered", "MEDIUM"),
    "gemini-3.8-flash-low": ("gemini-3.8-flash-tiered", "LOW"),
    "gemini-3.8-pro": ("gemini-3.8-pro", None),
    # Standalone flash aliases
    "flash": ("gemini-3.8-flash-tiered", "HIGH"),
    "flash-high": ("gemini-3.8-flash-tiered", "HIGH"),
    "flash-medium": ("gemini-3.8-flash-tiered", "MEDIUM"),
    "flash-low": ("gemini-3.8-flash-tiered", "LOW"),
    # Claude 3.7 Sonnet aliases
    "claude-3-7-sonnet": ("claude-3-7-sonnet", None),
    "claude-3-7-sonnet-high": ("claude-3-7-sonnet", "HIGH"),
    "claude-3-7-sonnet-medium": ("claude-3-7-sonnet", "MEDIUM"),
    "claude-3-7-sonnet-low": ("claude-3-7-sonnet", "LOW"),
    # Claude 5.5 Sonnet aliases
    "claude-sonnet-5-5": ("claude-sonnet-5-5", None),
    "claude-sonnet-5-5-high": ("claude-sonnet-5-5", "HIGH"),
    "claude-sonnet-5-5-medium": ("claude-sonnet-5-5", "MEDIUM"),
    "claude-sonnet-5-5-low": ("claude-sonnet-5-5", "LOW"),
    # Claude 5.5 Opus aliases
    "claude-opus-5-5": ("claude-opus-5-5", None),
    "claude-opus-5-5-high": ("claude-opus-5-5", "HIGH"),
    "claude-opus-5-5-medium": ("claude-opus-5-5", "MEDIUM"),
    "claude-opus-5-5-low": ("claude-opus-5-5", "LOW"),
    # Claude 5.5 Haiku aliases
    "claude-haiku-5-5": ("claude-haiku-5-5", None),
    "claude-haiku-5-5-high": ("claude-haiku-5-5", "HIGH"),
    "claude-haiku-5-5-medium": ("claude-haiku-5-5", "MEDIUM"),
    "claude-haiku-5-5-low": ("claude-haiku-5-5", "LOW"),
}


def resolve_model_and_thinking(
    model: str | None,
    payload: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """Resolves model name and thinkingConfig applying model routing table and client overrides.

    Args:
        model: Optional model identifier string.
        payload: Request payload dictionary which may contain client thinking overrides.

    Returns:
        tuple of (resolved_model_name, thinking_config_dict_or_None)
    """
    raw_model = (model or "").strip()
    m = raw_model.lower()

    if m in MODEL_TIER_TABLE:
        resolved_model, tier = MODEL_TIER_TABLE[m]
        default_thinking: dict[str, Any] | None = {"thinkingLevel": tier} if tier else None
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


def validate_generation_parameters(payload: dict[str, Any]) -> None:
    """Validates generation parameters in payload according to API specifications.

    Raises:
        InvalidRequestError: If temperature, top_p, or max_tokens have invalid types or values.
    """
    if "temperature" in payload and payload["temperature"] is not None:
        val = payload["temperature"]
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise InvalidRequestError("Parameter 'temperature' must be a number")

    if "top_p" in payload and payload["top_p"] is not None:
        val = payload["top_p"]
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise InvalidRequestError("Parameter 'top_p' must be a number")

    for key in ("max_tokens", "max_output_tokens", "max_completion_tokens"):
        if key in payload and payload[key] is not None:
            val = payload[key]
            if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
                raise InvalidRequestError("Parameter 'max_tokens' must be a positive integer")


def _extract_text_and_parts_from_content(raw_content: Any) -> str:
    """Extracts text content, rejecting multimodal image content with 400 InvalidRequestError."""
    if isinstance(raw_content, list):
        parts_str: list[str] = []
        for item in raw_content:
            if isinstance(item, dict):
                item_type = item.get("type")
                if item_type in ("image_url", "image") or "image_url" in item:
                    raise InvalidRequestError("Multimodal image content is not supported by agy-model-bridge")
                if item_type == "text" or "text" in item:
                    parts_str.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts_str.append(item)
        return "".join(parts_str)
    elif isinstance(raw_content, dict):
        item_type = raw_content.get("type")
        if item_type in ("image_url", "image") or "image_url" in raw_content:
            raise InvalidRequestError("Multimodal image content is not supported by agy-model-bridge")
        if item_type == "text" or "text" in raw_content:
            return str(raw_content.get("text") or "")
        return ""
    elif raw_content is None:
        return ""
    elif isinstance(raw_content, str):
        return raw_content
    else:
        return str(raw_content)


def openai_to_cloudcode_request(
    openai_payload: dict[str, Any], project: str
) -> OpenAIChatRequest:
    """Validates OpenAI payload, extracts model, builds Cloud Code contents, systemInstruction, generationConfig, and tools.

    Args:
        openai_payload: Raw request dictionary matching OpenAI schema.
        project: Upstream project identifier.

    Returns:
        OpenAIChatRequest containing validated request parameters (unpackable as 5-tuple).

    Raises:
        ValueError: If model or messages are missing/invalid.
    """
    validate_generation_parameters(openai_payload)
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
        content = _extract_text_and_parts_from_content(raw_content)

        if role in ("system", "developer"):
            system_texts.append(content)
            continue
        turn_parts: list[dict[str, Any]]
        if role == "user":
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
                    fn_raw = tc.get("function")
                    fn: dict[str, Any] = fn_raw if isinstance(fn_raw, dict) else tc
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
            else:
                fc = msg.get("function_call")
                if isinstance(fc, dict):
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

        append_or_merge_turn(contents, turn_role, turn_parts)

    if len(contents) == 0:
        raise ValueError(
            "Missing or empty user/assistant messages: at least one message is required"
        )

    normalize_turn_boundaries(contents)
    system_instruction = build_system_instruction(system_texts)

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
            fn_obj = t.get("function")
            fn_dict: dict[str, Any] = fn_obj if isinstance(fn_obj, dict) else t
            if not isinstance(fn_dict, dict):
                continue
            name = fn_dict.get("name")
            if not name or not isinstance(name, str):
                continue
            decl: dict[str, Any] = {"name": name}
            desc = fn_dict.get("description")
            if desc is not None:
                decl["description"] = str(desc)
            params = fn_dict.get("parameters")
            if params is not None and isinstance(params, dict):
                decl["parameters"] = sanitize_schema_for_gemini(params)
            else:
                decl["parameters"] = {"type": "object", "properties": {}}
            function_declarations.append(decl)
        tools = build_tool_declarations(function_declarations)

    return OpenAIChatRequest(
        model=model,
        contents=contents,
        system_instruction=system_instruction,
        generation_config=generation_config,
        tools=tools,
    )


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
    return parse_stream_event(event_dict, check_error=False).delta_text


def extract_thought_delta(event_dict: dict[str, Any]) -> str | None:
    """Extracts text chunk from candidates[0].parts where thought is True."""
    return parse_stream_event(event_dict, check_error=False).delta_thought


def extract_function_calls(event_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """Extracts function calls from candidates[0].parts.

    Returns a list of dicts: [{"id": ..., "name": ..., "args": ...}]
    """
    return [
        tc.to_dict()
        for tc in parse_stream_event(event_dict, check_error=False).tool_calls
    ]




def extract_finish_reason(event_dict: dict[str, Any]) -> str | None:
    """Extracts finishReason ('stop', 'length', 'content_filter') if candidate finished."""
    return parse_stream_event(event_dict, check_error=False).finish_reason


def extract_usage(event_dict: dict[str, Any]) -> dict[str, int] | None:
    """Translates usageMetadata into OpenAI usage format."""
    ev = parse_stream_event(event_dict, check_error=False)
    return ev.usage.to_dict() if ev.usage is not None else None


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


def build_openai_sse_events(
    lines_gen: Iterator[Any],
    model: str,
    completion_id: str | None = None,
) -> Iterator[str]:
    """Generates OpenAI-compatible SSE chunk events from an upstream stream."""
    if not completion_id:
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    last_finish_reason: str = "stop"
    last_usage: dict[str, int] | None = None
    is_first_chunk: bool = True
    tool_calls_emitted: bool = False
    tc_index: int = 0
    cached_stream_thought_sig: str | None = None

    for item in lines_gen:
        if isinstance(item, StreamEvent):
            event = item
        elif isinstance(item, dict):
            event = parse_stream_event(item, check_error=True)
        elif isinstance(item, str):
            parsed = parse_cloudcode_sse_event(item)
            if not parsed:
                continue
            event = parse_stream_event(parsed, check_error=True)
        else:
            continue

        if event.usage:
            last_usage = event.usage.to_dict()
        if event.thought_signature:
            cached_stream_thought_sig = event.thought_signature
        if event.finish_reason:
            last_finish_reason = event.finish_reason

        delta_text = event.delta_text
        delta_tool_calls: list[dict[str, Any]] | None = None

        if event.tool_calls:
            tool_calls_emitted = True
            delta_tool_calls = []
            for tc in event.tool_calls:
                if isinstance(tc, ToolCallDelta):
                    tc_id = tc.id
                    tc_name = tc.name
                    tc_args = tc.args
                    tc_sig = tc.thought_signature
                elif isinstance(tc, dict):
                    tc_id = tc.get("id")
                    tc_name = tc.get("name")
                    tc_args = tc.get("args", {})
                    tc_sig = tc.get("thought_signature") or tc.get("thoughtSignature")
                else:
                    continue

                if not tc_id:
                    tc_id = f"call_{uuid.uuid4().hex[:12]}"
                elif tc_id.startswith("toolu_"):
                    tc_id = f"call_{tc_id[6:]}"

                sig = tc_sig or event.thought_signature or cached_stream_thought_sig
                if sig:
                    cache_thought_signature(call_id=tc_id, signature=sig, name=tc_name, args=tc_args)
                if tc_name and tc_id:
                    cache_tool_name(tc_id, tc_name)

                args_str = json.dumps(tc_args) if isinstance(tc_args, (dict, list)) else str(tc_args or "{}")
                call_dict: dict[str, Any] = {
                    "index": tc_index,
                    "id": tc_id,
                    "type": "function",
                    "function": {
                        "name": tc_name or "",
                        "arguments": args_str,
                    },
                }
                if sig:
                    call_dict["thought_signature"] = sig
                delta_tool_calls.append(call_dict)
                tc_index += 1

        if delta_text or delta_tool_calls:
            chunk = build_openai_chunk(
                completion_id,
                model,
                delta_text=delta_text,
                role="assistant" if is_first_chunk else None,
                delta_tool_calls=delta_tool_calls,
            )
            is_first_chunk = False
            yield chunk

    if tool_calls_emitted:
        last_finish_reason = "tool_calls"

    stop_chunk = build_openai_chunk(
        completion_id,
        model,
        finish_reason=last_finish_reason,
        usage=last_usage,
    )
    yield stop_chunk
    yield "data: [DONE]\n\n"


class OpenAIProtocolAdapter:
    """Protocol adapter for OpenAI Chat Completions API."""

    @staticmethod
    def transform_request(
        payload: dict[str, Any], project: str = ""
    ) -> OpenAIChatRequest:
        return openai_to_cloudcode_request(payload, project)

    @staticmethod
    def build_response(
        completion_id: str,
        model: str,
        text: str,
        usage: dict[str, int] | None = None,
        finish_reason: str = "stop",
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return build_openai_completion(
            completion_id, model, text, usage=usage, finish_reason=finish_reason, tool_calls=tool_calls
        )

    @staticmethod
    def build_stream(
        lines_gen: Iterator[Any],
        model: str,
        completion_id: str | None = None,
    ) -> Iterator[str]:
        return build_openai_sse_events(lines_gen, model, completion_id=completion_id)

