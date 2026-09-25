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
            if (not content or not content.strip()) and tool_calls and isinstance(tool_calls, list):
                tool_call_strs = []
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        fn = tc.get("function", {})
                        fn_name = fn.get("name", "tool") if isinstance(fn, dict) else "tool"
                        fn_args = fn.get("arguments", "") if isinstance(fn, dict) else ""
                        tool_call_strs.append(f"[Tool Call: {fn_name}({fn_args})]")
                content = " ".join(tool_call_strs)
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

    if "stop" in openai_payload and openai_payload["stop"] is not None:
        stop_val = openai_payload["stop"]
        stop_list: list[str] = []
        if isinstance(stop_val, str):
            if stop_val.strip():
                stop_list = [stop_val]
        elif isinstance(stop_val, list):
            stop_list = [str(s) for s in stop_val if s is not None and str(s).strip()]
        if stop_list:
            gen_config["stopSequences"] = stop_list

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
                    "object": "model",
                    "created": created,
                    "owned_by": "google",
                }
            )

    return {"object": "list", "data": models_data}


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
