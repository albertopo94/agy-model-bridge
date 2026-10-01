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
    extract_function_calls,
    extract_text_delta,
    extract_usage,
    parse_cloudcode_sse_event,
    resolve_model_and_thinking,
    sanitize_schema_for_gemini,
)


def responses_to_cloudcode_request(
    payload: dict[str, Any], project: str = ""
) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]] | None]:
    """Validates OpenAI Responses payload and transforms to Cloud Code parameters.

    Args:
        payload: Request payload matching /v1/responses schema.
        project: Upstream project identifier.

    Returns:
        tuple of (model_name, contents_list, system_instruction_dict_or_None, generation_config_dict_or_None, tools_or_None)

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

    # Tools translation
    tools_raw = payload.get("tools")
    tools: list[dict[str, Any]] | None = None
    if isinstance(tools_raw, list) and tools_raw:
        function_declarations: list[dict[str, Any]] = []
        for tool in tools_raw:
            if not isinstance(tool, dict):
                continue
            fn = tool.get("function") if "function" in tool and isinstance(tool["function"], dict) else tool
            if not isinstance(fn, dict):
                continue
            name = fn.get("name")
            if not name or not isinstance(name, str):
                continue
            decl: dict[str, Any] = {"name": name}
            description = fn.get("description")
            if description and isinstance(description, str):
                decl["description"] = description
            parameters = fn.get("parameters")
            if parameters and isinstance(parameters, dict):
                decl["parameters"] = sanitize_schema_for_gemini(parameters)
            function_declarations.append(decl)
        if function_declarations:
            tools = [{"functionDeclarations": function_declarations}]

    return model, contents, system_instruction, generation_config, tools


def build_responses_completion(
    response_id: str,
    model: str,
    text: str,
    usage: dict[str, int] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Constructs non-streaming OpenAI Response object."""
    in_tok = 0
    out_tok = 0
    total_tok = 0
    if usage:
        in_tok = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        out_tok = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total_tok = int(usage.get("total_tokens") or (in_tok + out_tok))

    output: list[dict[str, Any]] = []
    if text:
        output.append({
            "id": f"msg_{uuid.uuid4().hex[:16]}",
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": text,
                }
            ],
        })
    if tool_calls:
        for tc in tool_calls:
            fc_id = f"fc_{uuid.uuid4().hex[:16]}"
            call_id = tc.get("id") or f"call_{uuid.uuid4().hex[:16]}"
            name = tc.get("name", "")
            args_val = tc.get("args", {})
            args_str = json.dumps(args_val) if isinstance(args_val, (dict, list)) else str(args_val or "")
            output.append({
                "id": fc_id,
                "type": "function_call",
                "status": "completed",
                "call_id": call_id,
                "name": name,
                "arguments": args_str,
            })
    if not output:
        output.append({
            "id": f"msg_{uuid.uuid4().hex[:16]}",
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": text,
                }
            ],
        })

    return {
        "id": response_id,
        "object": "response",
        "created": int(time.time()),
        "status": "completed",
        "model": model,
        "output": output,
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
    now = int(time.time())
    seq = 0

    def emit(event: str, payload: dict[str, Any]) -> str:
        nonlocal seq
        payload["type"] = event
        payload["sequence_number"] = seq
        seq += 1
        return f"event: {event}\ndata: {json.dumps(payload)}\n\n"

    # Initial response.created skeleton
    created_response = {
        "id": response_id,
        "object": "response",
        "created": now,
        "created_at": now,
        "status": "in_progress",
        "model": model,
        "output": [],
        "output_text": "",
        "usage": None,
    }
    yield emit("response.created", {"response": created_response})

    # Initial response.in_progress skeleton
    in_progress_response = {
        "id": response_id,
        "object": "response",
        "created": now,
        "created_at": now,
        "status": "in_progress",
        "model": model,
        "output": [],
        "output_text": "",
        "usage": None,
    }
    yield emit("response.in_progress", {"response": in_progress_response})

    output_index = 0
    text_item_id: str | None = None
    text_output_index: int = 0
    full_text = ""
    outputs: list[dict[str, Any]] = []

    in_tok = 0
    out_tok = 0
    total_tok = 0

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

        text_delta = extract_text_delta(parsed)
        if text_delta:
            if text_item_id is None:
                text_item_id = f"msg_{uuid.uuid4().hex[:16]}"
                text_output_index = output_index
                output_index += 1
                yield emit(
                    "response.output_item.added",
                    {
                        "response_id": response_id,
                        "output_index": text_output_index,
                        "item": {
                            "id": text_item_id,
                            "type": "message",
                            "status": "in_progress",
                            "role": "assistant",
                            "content": [],
                        },
                    },
                )
                yield emit(
                    "response.content_part.added",
                    {
                        "response_id": response_id,
                        "item_id": text_item_id,
                        "output_index": text_output_index,
                        "content_index": 0,
                        "part": {
                            "type": "output_text",
                            "text": "",
                            "annotations": [],
                        },
                    },
                )
            yield emit(
                "response.output_text.delta",
                {
                    "response_id": response_id,
                    "item_id": text_item_id,
                    "output_index": text_output_index,
                    "content_index": 0,
                    "delta": text_delta,
                },
            )
            full_text += text_delta

        function_calls = extract_function_calls(parsed)
        if function_calls:
            if text_item_id is not None:
                yield emit(
                    "response.output_text.done",
                    {
                        "response_id": response_id,
                        "item_id": text_item_id,
                        "output_index": text_output_index,
                        "content_index": 0,
                        "text": full_text,
                    },
                )
                yield emit(
                    "response.content_part.done",
                    {
                        "response_id": response_id,
                        "item_id": text_item_id,
                        "output_index": text_output_index,
                        "content_index": 0,
                        "part": {
                            "type": "output_text",
                            "text": full_text,
                            "annotations": [],
                        },
                    },
                )
                completed_text_item = {
                    "id": text_item_id,
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": full_text,
                            "annotations": [],
                        }
                    ],
                }
                yield emit(
                    "response.output_item.done",
                    {
                        "response_id": response_id,
                        "output_index": text_output_index,
                        "item": completed_text_item,
                    },
                )
                outputs.append(completed_text_item)
                text_item_id = None

            for fc in function_calls:
                fc_id = f"fc_{uuid.uuid4().hex[:16]}"
                call_id = fc.get("id") or f"call_{uuid.uuid4().hex[:16]}"
                name = fc.get("name", "")
                args_val = fc.get("args", {})
                args_str = json.dumps(args_val) if isinstance(args_val, (dict, list)) else str(args_val or "")
                fc_output_index = output_index
                output_index += 1

                yield emit(
                    "response.output_item.added",
                    {
                        "response_id": response_id,
                        "output_index": fc_output_index,
                        "item": {
                            "id": fc_id,
                            "type": "function_call",
                            "status": "in_progress",
                            "call_id": call_id,
                            "name": name,
                            "arguments": "",
                        },
                    },
                )
                yield emit(
                    "response.function_call_arguments.delta",
                    {
                        "response_id": response_id,
                        "item_id": fc_id,
                        "output_index": fc_output_index,
                        "delta": args_str,
                    },
                )
                yield emit(
                    "response.function_call_arguments.done",
                    {
                        "response_id": response_id,
                        "item_id": fc_id,
                        "output_index": fc_output_index,
                        "arguments": args_str,
                    },
                )
                completed_fc_item = {
                    "id": fc_id,
                    "type": "function_call",
                    "status": "completed",
                    "call_id": call_id,
                    "name": name,
                    "arguments": args_str,
                }
                yield emit(
                    "response.output_item.done",
                    {
                        "response_id": response_id,
                        "output_index": fc_output_index,
                        "item": completed_fc_item,
                    },
                )
                outputs.append(completed_fc_item)

    if text_item_id is not None:
        yield emit(
            "response.output_text.done",
            {
                "response_id": response_id,
                "item_id": text_item_id,
                "output_index": text_output_index,
                "content_index": 0,
                "text": full_text,
            },
        )
        yield emit(
            "response.content_part.done",
            {
                "response_id": response_id,
                "item_id": text_item_id,
                "output_index": text_output_index,
                "content_index": 0,
                "part": {
                    "type": "output_text",
                    "text": full_text,
                    "annotations": [],
                },
            },
        )
        completed_text_item = {
            "id": text_item_id,
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": full_text,
                    "annotations": [],
                }
            ],
        }
        yield emit(
            "response.output_item.done",
            {
                "response_id": response_id,
                "output_index": text_output_index,
                "item": completed_text_item,
            },
        )
        outputs.append(completed_text_item)
        text_item_id = None

    completed_payload = {
        "response": {
            "id": response_id,
            "object": "response",
            "created": now,
            "created_at": now,
            "status": "completed",
            "model": model,
            "output": outputs,
            "output_text": full_text,
            "usage": {
                "total_tokens": total_tok,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
            },
        },
    }
    yield emit("response.completed", completed_payload)


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
