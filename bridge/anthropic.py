"""Anthropic Messages API shim for Google Cloud Code Assist.

Translates Anthropic Messages requests, responses, and SSE event streams.
Zero external dependencies: pure Python standard library.
"""

import json
import uuid
from typing import Any, Iterator

from bridge.transform import (
    build_thinking_config,
    check_sse_error,
    extract_finish_reason,
    extract_text_delta,
    extract_usage,
    parse_cloudcode_sse_event,
    resolve_model_and_thinking,
)


def anthropic_to_cloudcode_request(
    payload: dict[str, Any], project: str
) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
    """Validates Anthropic Messages payload and transforms to Cloud Code parameters.

    Args:
        payload: Anthropic request payload matching /v1/messages schema.
        project: Upstream project identifier.

    Returns:
        tuple of (model_name, contents_list, system_instruction_dict_or_None, generation_config_dict_or_None)

    Raises:
        ValueError: If model or messages are missing or invalid.
    """
    raw_model = payload.get("model")
    if raw_model is not None and not isinstance(raw_model, str):
        raise ValueError("Invalid 'model' parameter: must be a string")
    model, thinking_cfg = resolve_model_and_thinking(raw_model, payload)

    messages = payload.get("messages")
    if not messages or not isinstance(messages, list) or len(messages) == 0:
        raise ValueError("Missing or invalid 'messages' parameter: must be a non-empty list")

    # Parse system instruction
    raw_system = payload.get("system")
    system_texts: list[str] = []
    if isinstance(raw_system, str):
        if raw_system.strip():
            system_texts.append(raw_system.strip())
    elif isinstance(raw_system, list):
        for item in raw_system:
            if isinstance(item, dict) and (item.get("type") == "text" or "text" in item):
                txt = str(item.get("text") or "")
                if txt.strip():
                    system_texts.append(txt.strip())
            elif isinstance(item, str) and item.strip():
                system_texts.append(item.strip())

    system_instruction: dict[str, Any] | None = None
    if system_texts:
        system_instruction = {"parts": [{"text": "\n".join(system_texts)}]}

    # Parse message turns
    contents: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            raise ValueError("Each message must be a dictionary")
        role = msg.get("role")
        if role == "user":
            turn_role = "user"
        elif role == "assistant":
            turn_role = "model"
        else:
            raise ValueError(f"Invalid Anthropic message role: {role}")

        raw_content = msg.get("content")
        if isinstance(raw_content, str):
            text = raw_content
        elif isinstance(raw_content, list):
            parts_str = []
            for block in raw_content:
                if isinstance(block, dict):
                    b_type = block.get("type")
                    if b_type == "tool_result":
                        tr_content = block.get("content")
                        if tr_content is None:
                            tr_content = block.get("text", "")
                        if isinstance(tr_content, list):
                            nested_strs = []
                            for nb in tr_content:
                                if isinstance(nb, dict):
                                    nested_strs.append(str(nb.get("text") or ""))
                                elif isinstance(nb, str):
                                    nested_strs.append(nb)
                            content_str = "\n".join(nested_strs) if nested_strs else json.dumps(tr_content)
                        elif isinstance(tr_content, (dict, list)):
                            content_str = json.dumps(tr_content)
                        else:
                            content_str = str(tr_content)
                        parts_str.append(f"[Tool Result]: {content_str}")
                    elif b_type == "tool_use":
                        name = block.get("name", "tool")
                        inp = block.get("input")
                        if inp is None:
                            inp = {}
                        parts_str.append(f"[Tool Call]: {name}({json.dumps(inp)})")
                    elif b_type == "text" or "text" in block:
                        parts_str.append(str(block.get("text") or ""))
                elif isinstance(block, str):
                    parts_str.append(block)
            text = "\n".join(parts_str) if any(p.startswith("[Tool ") for p in parts_str) else "".join(parts_str)
        elif raw_content is None:
            text = ""
        else:
            text = str(raw_content)

        part_text = text if text and text.strip() else " "
        turn_parts = [{"text": part_text}]

        if contents and contents[-1]["role"] == turn_role:
            contents[-1]["parts"].extend(turn_parts)
        else:
            contents.append({"role": turn_role, "parts": turn_parts})

    # Alternation & turn order enforcement
    if contents and contents[0]["role"] == "model":
        contents.insert(0, {"role": "user", "parts": [{"text": "Hello"}]})
    if contents and contents[-1]["role"] == "model":
        contents.append({"role": "user", "parts": [{"text": "Continue"}]})

    # Generation config
    gen_config: dict[str, Any] = {}
    if "max_tokens" in payload and payload["max_tokens"] is not None:
        gen_config["maxOutputTokens"] = int(payload["max_tokens"])

    if "temperature" in payload and payload["temperature"] is not None:
        gen_config["temperature"] = float(payload["temperature"])

    if "top_p" in payload and payload["top_p"] is not None:
        gen_config["topP"] = float(payload["top_p"])

    if "top_k" in payload and payload["top_k"] is not None:
        try:
            gen_config["topK"] = int(payload["top_k"])
        except (ValueError, TypeError):
            pass

    if "stop_sequences" in payload and payload["stop_sequences"] is not None:
        raw_stops = payload["stop_sequences"]
        if isinstance(raw_stops, list):
            clean_stops = [str(s) for s in raw_stops if s is not None and str(s) != ""]
            if clean_stops:
                gen_config["stopSequences"] = clean_stops

    if thinking_cfg is not None:
        gen_config["thinkingConfig"] = thinking_cfg

    generation_config: dict[str, Any] | None = gen_config if gen_config else None

    return model, contents, system_instruction, generation_config


def build_anthropic_message(
    message_id: str,
    model: str,
    text: str,
    usage: dict[str, int] | None = None,
    stop_reason: str = "end_turn",
) -> dict[str, Any]:
    """Constructs non-streaming Anthropic Messages response dictionary."""
    if stop_reason in ("length", "max_tokens"):
        stop_reason = "max_tokens"
    elif stop_reason in ("stop_sequence", "tool_use"):
        pass
    else:
        stop_reason = "end_turn"

    input_tokens = 0
    output_tokens = 0
    if usage:
        input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)

    return {
        "id": message_id,
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    }


def build_anthropic_sse_events(lines_gen: Iterator[str], model: str) -> Iterator[str]:
    """Transforms Cloud Code SSE stream into Anthropic Messages SSE events."""
    message_id = f"msg_{uuid.uuid4().hex[:16]}"
    input_tokens = 0
    output_tokens = 0
    stop_reason = "end_turn"

    # 1. message_start
    start_payload = {
        "type": "message_start",
        "message": {
            "id": message_id,
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
            },
        },
    }
    yield f"event: message_start\ndata: {json.dumps(start_payload)}\n\n"

    # 2. content_block_start
    block_start_payload = {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    }
    yield f"event: content_block_start\ndata: {json.dumps(block_start_payload)}\n\n"

    # 3. Stream content deltas
    for line in lines_gen:
        parsed = parse_cloudcode_sse_event(line)
        if parsed is None:
            continue

        check_sse_error(parsed)

        usage = extract_usage(parsed)
        if usage:
            input_tokens = usage.get("prompt_tokens", input_tokens)
            output_tokens = usage.get("completion_tokens", output_tokens)

        finish_reason = extract_finish_reason(parsed)
        if finish_reason:
            if finish_reason in ("length", "max_tokens"):
                stop_reason = "max_tokens"
            elif finish_reason in ("stop_sequence", "tool_use"):
                stop_reason = finish_reason
            else:
                stop_reason = "end_turn"

        delta_text = extract_text_delta(parsed)
        if delta_text:
            delta_payload = {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "text_delta",
                    "text": delta_text,
                },
            }
            yield f"event: content_block_delta\ndata: {json.dumps(delta_payload)}\n\n"

    # 4. content_block_stop
    block_stop_payload = {
        "type": "content_block_stop",
        "index": 0,
    }
    yield f"event: content_block_stop\ndata: {json.dumps(block_stop_payload)}\n\n"

    # 5. message_delta
    msg_delta_payload = {
        "type": "message_delta",
        "delta": {
            "stop_reason": stop_reason,
            "stop_sequence": None,
        },
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    }
    yield f"event: message_delta\ndata: {json.dumps(msg_delta_payload)}\n\n"

    # 6. message_stop
    msg_stop_payload = {"type": "message_stop"}
    yield f"event: message_stop\ndata: {json.dumps(msg_stop_payload)}\n\n"


def build_anthropic_error_response(
    status_code: int,
    message: str,
    error_type: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Generates standard Anthropic error dictionary and HTTP status code."""
    if not error_type:
        if status_code == 400:
            error_type = "invalid_request_error"
        elif status_code == 401:
            error_type = "authentication_error"
        elif status_code == 403:
            error_type = "permission_error"
        elif status_code == 404:
            error_type = "not_found_error"
        elif status_code == 429:
            error_type = "rate_limit_error"
        elif status_code == 503:
            error_type = "overloaded_error"
        elif status_code == 504:
            error_type = "timeout_error"
        else:
            error_type = "api_error"

    return (
        status_code,
        {
            "type": "error",
            "error": {
                "type": error_type,
                "message": message,
            },
        },
    )
