"""Pure transformation functions between OpenAI and Google Cloud Code Assist schemas."""

import json
import time
from typing import Any

from bridge.client import (
    AuthenticationError,
    BridgeError,
    CapacityExhaustedError,
    ForbiddenError,
    InvalidRequestError,
    ModelNotFoundError,
    RateLimitError,
)


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

    if "thinking" in payload:
        val = payload["thinking"]
        if isinstance(val, dict):
            t_type = str(val.get("type", "")).strip().lower()
            if t_type in ("disabled", "off", "none"):
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
            if t_type in ("adaptive", "auto"):
                return _tiered_or_budget()
            if t_type == "enabled":
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
            return sanitized_thinking if sanitized_thinking else None
        elif val is False:
            return None
        elif val is True:
            return _tiered_or_budget()

    effort = None
    if "reasoning_effort" in payload and payload["reasoning_effort"] is not None:
        effort = str(payload["reasoning_effort"]).strip().lower()
    elif "effort" in payload and payload["effort"] is not None:
        effort = str(payload["effort"]).strip().lower()

    if effort is not None:
        if effort in ("none", "disabled", "off"):
            return None
        if effort in ("high", "medium", "low"):
            return {"thinkingLevel": effort.upper()}

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

    if not m or m == "auto" or m in ("gemini-3.8-flash", "gemini-3.8-flash-high"):
        resolved_model = "gemini-3.8-flash-tiered"
        default_thinking: dict[str, Any] | None = {"thinkingLevel": "HIGH"}
    elif m == "gemini-3.8-flash-medium":
        resolved_model = "gemini-3.8-flash-tiered"
        default_thinking = {"thinkingLevel": "MEDIUM"}
    elif m == "gemini-3.8-flash-low":
        resolved_model = "gemini-3.8-flash-tiered"
        default_thinking = {"thinkingLevel": "LOW"}
    else:
        resolved_model = raw_model
        default_thinking = None

    has_payload_override = (
        ("thinkingConfig" in payload and isinstance(payload["thinkingConfig"], dict))
        or "thinking" in payload
        or "reasoning_effort" in payload
        or "effort" in payload
        or "thinking_budget" in payload
    )

    if has_payload_override:
        thinking_cfg = build_thinking_config(resolved_model, payload)
    else:
        thinking_cfg = default_thinking if default_thinking is not None else build_thinking_config(resolved_model, payload)

    return resolved_model, thinking_cfg


def openai_to_cloudcode_request(
    openai_payload: dict[str, Any], project: str
) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
    """Validates OpenAI payload, extracts model, builds Cloud Code contents, systemInstruction, and generationConfig.

    Args:
        openai_payload: Raw request dictionary matching OpenAI schema.
        project: Upstream project identifier.

    Returns:
        tuple of (model_name, contents_list, system_instruction_dict_or_None, generation_config_dict_or_None)

    Raises:
        ValueError: If model or messages are missing/invalid.
    """
    model = openai_payload.get("model")
    if not model or not isinstance(model, str) or not model.strip():
        raise ValueError("Missing or invalid 'model' parameter")

    messages = openai_payload.get("messages")
    if not messages or not isinstance(messages, list) or len(messages) == 0:
        raise ValueError("Missing or invalid 'messages' parameter: must be a non-empty list")

    system_texts: list[str] = []
    contents: list[dict[str, Any]] = []

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
            tool_calls = msg.get("tool_calls")
            if tool_calls and isinstance(tool_calls, list):
                tool_call_strs = []
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        fn = tc.get("function") or {}
                        fn_name = fn.get("name") or "unknown"
                        fn_args = fn.get("arguments", "")
                        fn_args_str = json.dumps(fn_args) if isinstance(fn_args, (dict, list)) else str(fn_args or "")
                        tool_call_strs.append(f"[Tool Call: {fn_name}({fn_args_str})]")
                if tool_call_strs:
                    tools_text = "\n".join(tool_call_strs)
                    if content and content.strip():
                        content = f"{content}\n{tools_text}"
                    else:
                        content = tools_text
            elif msg.get("function_call") and isinstance(msg.get("function_call"), dict):
                fc = msg.get("function_call")
                fc_name = fc.get("name") or "unknown"
                fc_args = fc.get("arguments", "")
                fc_args_str = json.dumps(fc_args) if isinstance(fc_args, (dict, list)) else str(fc_args or "")
                tool_str = f"[Tool Call: {fc_name}({fc_args_str})]"
                if content and content.strip():
                    content = f"{content}\n{tool_str}"
                else:
                    content = tool_str
            part_text = content if content and content.strip() else " "
            turn_parts = [{"text": part_text}]
        elif role in ("tool", "function"):
            turn_role = "user"
            tool_text = f"[Tool Result]: {content}"
            part_text = tool_text if tool_text and tool_text.strip() else " "
            turn_parts = [{"text": part_text}]
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

    thinking_cfg = build_thinking_config(model, openai_payload)
    if thinking_cfg is not None:
        gen_config["thinkingConfig"] = thinking_cfg

    generation_config: dict[str, Any] | None = gen_config if gen_config else None

    return model, contents, system_instruction, generation_config


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
) -> str:
    """Serializes a single OpenAI SSE chunk 'data: {...}\\n\\n'."""
    delta: dict[str, str] = {}
    if role is not None:
        delta["role"] = role
    if delta_text is not None:
        delta["content"] = delta_text

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
) -> dict[str, Any]:
    """Constructs non-streaming OpenAI chat.completion JSON object."""
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": full_text,
                },
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
