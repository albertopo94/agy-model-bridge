"""OpenAI Responses API shim for Google Cloud Code Assist.

Translates OpenAI Responses requests, responses, and SSE event streams for Codex CLI.
Zero external dependencies: pure Python standard library.
"""

import json
import time
import uuid
from typing import Any, Iterator

from bridge.transform import (
    build_openai_error_response,
    build_thinking_config,
    check_sse_error,
    extract_text_delta,
    extract_usage,
    parse_cloudcode_sse_event,
    resolve_model_and_thinking,
)


def responses_to_cloudcode_request(
    payload: dict[str, Any], project: str
) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
    """Validates OpenAI Responses payload and transforms to Cloud Code parameters.

    Args:
        payload: Request payload matching /v1/responses schema.
        project: Upstream project identifier.

    Returns:
        tuple of (model_name, contents_list, system_instruction_dict_or_None, generation_config_dict_or_None)

    Raises:
        ValueError: If model or input are missing or invalid.
    """
    raw_model = payload.get("model")
    if raw_model is not None and not isinstance(raw_model, str):
        raise ValueError("Invalid 'model' parameter: must be a string")
    model, thinking_cfg = resolve_model_and_thinking(raw_model, payload)

    input_items = payload.get("input")
    if isinstance(input_items, str):
        if not input_items.strip():
            raise ValueError("Missing or invalid 'input' parameter: string cannot be empty")
        input_items = [{"role": "user", "content": input_items}]
    elif isinstance(input_items, dict):
        input_items = [input_items]
    elif not input_items or not isinstance(input_items, list) or len(input_items) == 0:
        raise ValueError("Missing or invalid 'input' parameter: must be a non-empty list or string")

    # Instructions mapped to systemInstruction
    instructions = payload.get("instructions")
    system_texts: list[str] = []
    if instructions and isinstance(instructions, str) and instructions.strip():
        system_texts.append(instructions.strip())

    # Input items mapped to contents
    contents: list[dict[str, Any]] = []
    for item in input_items:
        if isinstance(item, str):
            role = "user"
            text = item
        elif isinstance(item, dict):
            role = item.get("role", "user")
            item_type = item.get("type")
            if item_type == "function_call":
                name = item.get("name", "")
                args = item.get("arguments", "")
                args_str = json.dumps(args) if isinstance(args, (dict, list)) else str(args or "")
                text = f"[Tool Call: {name}({args_str})]"
                role = "assistant"
            elif item_type == "function_call_output":
                output = item.get("output", "")
                output_str = json.dumps(output) if isinstance(output, (dict, list)) else str(output)
                text = f"[Function Output]: {output_str}"
                role = "user"
            else:
                raw_content = item.get("content")
                if isinstance(raw_content, str):
                    text = raw_content
                elif isinstance(raw_content, list):
                    parts_str = []
                    for block in raw_content:
                        if isinstance(block, dict):
                            if block.get("type") in ("input_text", "text", "output_text") or "text" in block:
                                parts_str.append(str(block.get("text") or ""))
                        elif isinstance(block, str):
                            parts_str.append(block)
                    text = "".join(parts_str)
                elif raw_content is None:
                    text = ""
                else:
                    text = str(raw_content)
        else:
            role = "user"
            text = str(item)

        if role in ("system", "developer"):
            if text and text.strip():
                system_texts.append(text.strip())
            continue

        turn_role = "model" if role == "assistant" else "user"
        part_text = text if text and text.strip() else " "
        turn_parts = [{"text": part_text}]

        if contents and contents[-1]["role"] == turn_role:
            contents[-1]["parts"].extend(turn_parts)
        else:
            contents.append({"role": turn_role, "parts": turn_parts})

    if len(contents) == 0:
        raise ValueError(
            "Missing or empty user/assistant messages: at least one input message is required"
        )

    # Alternation & turn order enforcement
    if contents and contents[0]["role"] == "model":
        contents.insert(0, {"role": "user", "parts": [{"text": "Hello"}]})
    if contents and contents[-1]["role"] == "model":
        contents.append({"role": "user", "parts": [{"text": "Continue"}]})

    system_instruction: dict[str, Any] | None = None
    if system_texts:
        combined_system = "\n".join(system_texts)
        if combined_system.strip():
            system_instruction = {"parts": [{"text": combined_system}]}

    # Generation config
    gen_config: dict[str, Any] = {}
    if "max_output_tokens" in payload and payload["max_output_tokens"] is not None:
        gen_config["maxOutputTokens"] = int(payload["max_output_tokens"])
    elif "max_tokens" in payload and payload["max_tokens"] is not None:
        gen_config["maxOutputTokens"] = int(payload["max_tokens"])

    if "temperature" in payload and payload["temperature"] is not None:
        gen_config["temperature"] = float(payload["temperature"])

    if "top_p" in payload and payload["top_p"] is not None:
        gen_config["topP"] = float(payload["top_p"])

    stop_items: list[str] = []
    for key in ("stop", "stop_sequences"):
        val = payload.get(key)
        if val is not None:
            if isinstance(val, str):
                s_str = str(val)
                if s_str != "" and (s_str.strip() != "" or "\n" in s_str or "\r" in s_str) and s_str not in stop_items:
                    stop_items.append(s_str)
            elif isinstance(val, list):
                for s in val:
                    if s is not None:
                        s_str = str(s)
                        if s_str != "" and (s_str.strip() != "" or "\n" in s_str or "\r" in s_str) and s_str not in stop_items:
                            stop_items.append(s_str)
    if stop_items:
        gen_config["stopSequences"] = stop_items

    if thinking_cfg is not None:
        gen_config["thinkingConfig"] = thinking_cfg

    generation_config: dict[str, Any] | None = gen_config if gen_config else None

    return model, contents, system_instruction, generation_config


def build_responses_completion(
    response_id: str,
    model: str,
    text: str,
    usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Constructs non-streaming OpenAI Response object."""
    in_tok = 0
    out_tok = 0
    total_tok = 0
    if usage:
        in_tok = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        out_tok = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total_tok = int(usage.get("total_tokens") or (in_tok + out_tok))

    msg_id = f"msg_{uuid.uuid4().hex[:16]}"
    return {
        "id": response_id,
        "object": "response",
        "created": int(time.time()),
        "status": "completed",
        "model": model,
        "output": [
            {
                "id": msg_id,
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                    }
                ],
            }
        ],
        "usage": {
            "total_tokens": total_tok,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
        },
    }


def build_responses_sse_events(
    lines_gen: Iterator[str],
    model: str,
    response_id: str | None = None,
) -> Iterator[str]:
    """Transforms Cloud Code SSE stream into OpenAI Responses SSE events."""
    if not response_id:
        response_id = f"resp_{uuid.uuid4().hex[:16]}"
    item_id = f"msg_{uuid.uuid4().hex[:16]}"
    created_ts = int(time.time())
    in_tok = 0
    out_tok = 0
    total_tok = 0
    deltas: list[str] = []

    # 1. response.created
    created_payload = {
        "type": "response.created",
        "response": {
            "id": response_id,
            "object": "response",
            "created": created_ts,
            "status": "in_progress",
            "model": model,
            "output": [],
            "usage": None,
        },
    }
    yield f"event: response.created\ndata: {json.dumps(created_payload)}\n\n"

    # 2. response.output_item.added
    output_item_payload = {
        "type": "response.output_item.added",
        "response_id": response_id,
        "output_index": 0,
        "item": {
            "id": item_id,
            "type": "message",
            "status": "in_progress",
            "role": "assistant",
            "content": [],
        },
    }
    yield f"event: response.output_item.added\ndata: {json.dumps(output_item_payload)}\n\n"

    # 3. response.content_part.added
    content_part_payload = {
        "type": "response.content_part.added",
        "response_id": response_id,
        "item_id": item_id,
        "output_index": 0,
        "content_index": 0,
        "part": {
            "type": "output_text",
            "text": "",
        },
    }
    yield f"event: response.content_part.added\ndata: {json.dumps(content_part_payload)}\n\n"

    # 4. Stream response.output_text.delta
    for line in lines_gen:
        parsed = parse_cloudcode_sse_event(line)
        if parsed is None:
            continue

        check_sse_error(parsed)

        usage = extract_usage(parsed)
        if usage:
            in_tok = usage.get("prompt_tokens", in_tok)
            out_tok = usage.get("completion_tokens", out_tok)
            total_tok = usage.get("total_tokens", in_tok + out_tok)

        delta_text = extract_text_delta(parsed)
        if delta_text:
            deltas.append(delta_text)
            delta_payload = {
                "type": "response.output_text.delta",
                "response_id": response_id,
                "item_id": item_id,
                "output_index": 0,
                "content_index": 0,
                "delta": delta_text,
            }
            yield f"event: response.output_text.delta\ndata: {json.dumps(delta_payload)}\n\n"

    full_text = "".join(deltas)

    # response.output_text.done
    text_done_payload = {
        "type": "response.output_text.done",
        "response_id": response_id,
        "item_id": item_id,
        "output_index": 0,
        "content_index": 0,
        "text": full_text,
    }
    yield f"event: response.output_text.done\ndata: {json.dumps(text_done_payload)}\n\n"

    # 5. response.content_part.done
    part_done_payload = {
        "type": "response.content_part.done",
        "response_id": response_id,
        "item_id": item_id,
        "output_index": 0,
        "content_index": 0,
        "part": {
            "type": "output_text",
            "text": full_text,
        },
    }
    yield f"event: response.content_part.done\ndata: {json.dumps(part_done_payload)}\n\n"

    # 6. response.output_item.done
    item_done_payload = {
        "type": "response.output_item.done",
        "response_id": response_id,
        "output_index": 0,
        "item": {
            "id": item_id,
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": full_text,
                }
            ],
        },
    }
    yield f"event: response.output_item.done\ndata: {json.dumps(item_done_payload)}\n\n"

    # 7. response.completed
    completed_payload = {
        "type": "response.completed",
        "response": {
            "id": response_id,
            "object": "response",
            "created": created_ts,
            "status": "completed",
            "model": model,
            "output": [
                {
                    "id": item_id,
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": full_text,
                        }
                    ],
                }
            ],
            "usage": {
                "total_tokens": total_tok,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
            },
        },
    }
    yield f"event: response.completed\ndata: {json.dumps(completed_payload)}\n\n"


def build_responses_error_response(
    status_code: int,
    message: str,
    error_type: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Generates standard OpenAI error payload and HTTP code for Responses endpoint."""
    if not error_type:
        if status_code in (400, 404):
            error_type = "invalid_request_error"
        elif status_code == 401:
            error_type = "authentication_error"
        elif status_code == 403:
            error_type = "permission_denied"
        elif status_code == 429:
            error_type = "rate_limit_error"
        else:
            error_type = "api_error"

    return build_openai_error_response(status_code, message, error_type)
