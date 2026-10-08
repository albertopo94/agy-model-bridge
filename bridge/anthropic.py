"""Anthropic Messages API shim for Google Cloud Code Assist.

Translates Anthropic Messages requests, responses, and SSE event streams.
Zero external dependencies: pure Python standard library.
"""

import json
import uuid
from typing import Any, Iterator

from bridge.transform import (
    DUMMY_THOUGHT_SIGNATURE,
    build_thinking_config,
    cache_thought_signature,
    cache_tool_name,
    check_sse_error,
    extract_finish_reason,
    extract_function_calls,
    extract_text_delta,
    extract_thought_delta,
    extract_usage,
    get_thought_signature,
    get_tool_name,
    parse_cloudcode_sse_event,
    resolve_model_and_thinking,
    sanitize_schema_for_gemini,
)


def _extract_event_thought_signature(parsed: dict[str, Any]) -> str | None:
    """Extracts thought signature from Cloud Code SSE candidate or content parts if present."""
    if not isinstance(parsed, dict):
        return None
    resp = parsed.get("response") if isinstance(parsed.get("response"), dict) else parsed
    cands = resp.get("candidates") if isinstance(resp, dict) else None
    if not cands or not isinstance(cands, list):
        return None
    cand = cands[0]
    if not isinstance(cand, dict):
        return None
    sig = cand.get("thoughtSignature") or cand.get("thought_signature")
    if sig:
        return str(sig)
    content = cand.get("content")
    if isinstance(content, dict):
        sig = content.get("thoughtSignature") or content.get("thought_signature")
        if sig:
            return str(sig)
        parts = content.get("parts")
    else:
        parts = cand.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict):
                sig = part.get("thoughtSignature") or part.get("thought_signature")
                if sig:
                    return str(sig)
                fc = part.get("functionCall")
                if isinstance(fc, dict):
                    sig = fc.get("thoughtSignature") or fc.get("thought_signature")
                    if sig:
                        return str(sig)
    return None


def anthropic_to_cloudcode_request(
    payload: dict[str, Any], project: str
) -> tuple[
    str,
    list[dict[str, Any]],
    dict[str, Any] | None,
    dict[str, Any] | None,
    list[dict[str, Any]] | None,
]:
    """Validates Anthropic Messages payload and transforms to Cloud Code parameters.

    Args:
        payload: Anthropic request payload matching /v1/messages schema.
        project: Upstream project identifier.

    Returns:
        tuple of (model_name, contents_list, system_instruction_dict_or_None, generation_config_dict_or_None, tools_list_or_None)

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

    # Parse message turns
    contents: list[dict[str, Any]] = []
    tool_names_by_call_id: dict[str, str] = {}

    def _add_part(turn_role: str, part: dict[str, Any]) -> None:
        if contents and contents[-1]["role"] == turn_role:
            contents[-1]["parts"].append(part)
        else:
            contents.append({"role": turn_role, "parts": [part]})

    for msg in messages:
        if not isinstance(msg, dict):
            raise ValueError("Each message must be a dictionary")
        role = msg.get("role")
        raw_content = msg.get("content")
        turn_thought_signature: str | None = None

        if role in ("system", "developer"):
            if isinstance(raw_content, str):
                if raw_content.strip():
                    system_texts.append(raw_content.strip())
            elif isinstance(raw_content, list):
                for item in raw_content:
                    if isinstance(item, dict) and (item.get("type") == "text" or "text" in item):
                        txt = str(item.get("text") or "")
                        if txt.strip():
                            system_texts.append(txt.strip())
                    elif isinstance(item, str) and item.strip():
                        system_texts.append(item.strip())
            continue

        if role in ("tool", "function"):
            call_id = msg.get("tool_call_id") or msg.get("name") or ""
            fn_name = msg.get("name") or tool_names_by_call_id.get(call_id) or get_tool_name(call_id) or "tool"
            tr_content = raw_content
            if isinstance(tr_content, list):
                extracted_texts = []
                for nb in tr_content:
                    if isinstance(nb, dict) and (nb.get("type") == "text" or "text" in nb):
                        extracted_texts.append(str(nb.get("text") or ""))
                    elif isinstance(nb, str):
                        extracted_texts.append(nb)
                tr_content = "\n".join(extracted_texts) if extracted_texts else json.dumps(tr_content)
            resp_payload = tr_content if isinstance(tr_content, dict) else {"output": tr_content}
            _add_part("user", {"functionResponse": {"name": fn_name, "response": resp_payload}})
            continue

        if isinstance(raw_content, list):
            parts_added = 0
            for block in raw_content:
                if isinstance(block, dict):
                    b_type = block.get("type")
                    if b_type == "thinking":
                        sig = (
                            block.get("signature")
                            or block.get("thoughtSignature")
                            or block.get("thought_signature")
                        )
                        if sig:
                            cache_thought_signature(signature=sig)
                            turn_thought_signature = sig
                            if contents and contents[-1]["role"] == "model":
                                for p in contents[-1]["parts"]:
                                    if "functionCall" in p and p.get("thoughtSignature") == DUMMY_THOUGHT_SIGNATURE:
                                        p["thoughtSignature"] = sig
                        thought_text = str(block.get("thinking") or block.get("text") or "")
                        part: dict[str, Any] = {"thought": True, "text": thought_text}
                        if sig:
                            part["thoughtSignature"] = sig
                        part_role = "model" if role == "assistant" else "user"
                        _add_part(part_role, part)
                        parts_added += 1
                    elif b_type == "tool_use":
                        call_id = block.get("id") or f"toolu_{uuid.uuid4().hex[:16]}"
                        name = block.get("name", "tool")
                        tool_names_by_call_id[call_id] = name
                        cache_tool_name(call_id, name)
                        args = block.get("input")
                        if args is None:
                            args = {}
                        elif isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                args = {"raw": args}
                        if not isinstance(args, dict):
                            args = {}
                        sig = (
                            block.get("thoughtSignature")
                            or block.get("thought_signature")
                            or turn_thought_signature
                            or get_thought_signature(call_id, name, args)
                        )
                        if sig:
                            cache_thought_signature(call_id=call_id, signature=sig, name=name, args=args)
                        part = {
                            "thoughtSignature": sig,
                            "functionCall": {"name": name, "args": args},
                        }
                        _add_part("model", part)
                        parts_added += 1
                    elif b_type == "tool_result":
                        call_id = block.get("tool_use_id", "")
                        name = tool_names_by_call_id.get(call_id) or get_tool_name(call_id) or "tool"
                        tr_content = block.get("content")
                        if tr_content is None:
                            tr_content = block.get("text", "")
                        if isinstance(tr_content, list):
                            extracted_texts = []
                            for nb in tr_content:
                                if isinstance(nb, dict) and (nb.get("type") == "text" or "text" in nb):
                                    extracted_texts.append(str(nb.get("text") or ""))
                                elif isinstance(nb, str):
                                    extracted_texts.append(nb)
                            tr_content = "\n".join(extracted_texts) if extracted_texts else json.dumps(tr_content)
                        response_payload = tr_content if isinstance(tr_content, dict) else {"output": tr_content}
                        part = {"functionResponse": {"name": name, "response": response_payload}}
                        _add_part("user", part)
                        parts_added += 1
                    elif b_type == "text" or "text" in block:
                        text_str = str(block.get("text") or "")
                        if text_str and text_str.strip():
                            part = {"text": text_str}
                            part_role = "model" if role == "assistant" else "user"
                            _add_part(part_role, part)
                            parts_added += 1
                elif isinstance(block, str) and block.strip():
                    part = {"text": block}
                    part_role = "model" if role == "assistant" else "user"
                    _add_part(part_role, part)
                    parts_added += 1
            if parts_added == 0:
                part_role = "model" if role == "assistant" else "user"
                _add_part(part_role, {"text": " "})
        elif isinstance(raw_content, str):
            text_str = raw_content if raw_content.strip() else " "
            part_role = "model" if role == "assistant" else "user"
            _add_part(part_role, {"text": text_str})
        elif raw_content is None:
            part_role = "model" if role == "assistant" else "user"
            _add_part(part_role, {"text": " "})
        else:
            text_str = str(raw_content)
            part_role = "model" if role == "assistant" else "user"
            _add_part(part_role, {"text": text_str if text_str.strip() else " "})

    system_instruction: dict[str, Any] | None = None
    if system_texts:
        system_instruction = {"parts": [{"text": "\n".join(system_texts)}]}

    # Alternation & turn order enforcement
    if not contents:
        contents.append({"role": "user", "parts": [{"text": "Hello"}]})
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

    # Tools translation
    raw_tools = payload.get("tools")
    tools: list[dict[str, Any]] | None = None
    if isinstance(raw_tools, list) and len(raw_tools) > 0:
        function_declarations: list[dict[str, Any]] = []
        for t in raw_tools:
            if not isinstance(t, dict):
                continue
            name = t.get("name")
            if not name:
                continue
            decl: dict[str, Any] = {"name": name}
            desc = t.get("description")
            if desc is not None:
                decl["description"] = desc
            params = t.get("input_schema") or t.get("parameters")
            if params is not None and isinstance(params, dict):
                decl["parameters"] = sanitize_schema_for_gemini(params)
            else:
                decl["parameters"] = {"type": "object", "properties": {}}
            function_declarations.append(decl)
        if function_declarations:
            tools = [{"functionDeclarations": function_declarations}]

    return model, contents, system_instruction, generation_config, tools


def build_anthropic_message(
    message_id: str,
    model: str,
    text: str = "",
    usage: dict[str, int] | None = None,
    stop_reason: str = "end_turn",
    thinking: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    signature: str | None = None,
) -> dict[str, Any]:
    """Constructs non-streaming Anthropic Messages response dictionary."""
    if tool_calls and stop_reason == "end_turn":
        stop_reason = "tool_use"
    elif stop_reason in ("length", "max_tokens"):
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

    content: list[dict[str, Any]] = []
    if thinking:
        sig = signature if signature is not None else (get_thought_signature() or "")
        content.append({
            "type": "thinking",
            "thinking": thinking,
            "signature": sig,
        })
    if text:
        content.append({
            "type": "text",
            "text": text,
        })
    if tool_calls:
        for call in tool_calls:
            call_id = call.get("id") or f"toolu_{uuid.uuid4().hex[:16]}"
            call_name = call.get("name", "")
            call_args = call.get("args")
            if call_args is None:
                call_args = {}
            elif isinstance(call_args, str):
                try:
                    call_args = json.loads(call_args)
                except Exception:
                    pass
            if call_id and call_name:
                cache_tool_name(call_id, call_name)
            thought_sig = call.get("thought_signature") or call.get("thoughtSignature")
            if thought_sig:
                cache_thought_signature(call_id=call_id, signature=thought_sig, name=call_name, args=call_args)
            content.append({
                "type": "tool_use",
                "id": call_id,
                "name": call_name,
                "input": call_args,
            })
    if not content:
        content.append({"type": "text", "text": ""})

    return {
        "id": message_id,
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
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
    upstream_stop_reason: str | None = None
    next_index = 0

    thinking_block_open = False
    thinking_block_index = -1

    text_block_open = False
    text_block_index = -1

    accumulated_tool_calls: list[dict[str, Any]] = []
    current_thought_sig: str | None = None

    def _close_thinking() -> Iterator[str]:
        nonlocal thinking_block_open
        sig = current_thought_sig or get_thought_signature() or ""
        sig_delta_payload = {
            "type": "content_block_delta",
            "index": thinking_block_index,
            "delta": {
                "type": "signature_delta",
                "signature": sig,
            },
        }
        yield f"event: content_block_delta\ndata: {json.dumps(sig_delta_payload)}\n\n"
        stop_payload = {
            "type": "content_block_stop",
            "index": thinking_block_index,
        }
        yield f"event: content_block_stop\ndata: {json.dumps(stop_payload)}\n\n"
        thinking_block_open = False

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

    # 2. Stream content deltas
    for line in lines_gen:
        parsed = parse_cloudcode_sse_event(line)
        if parsed is None:
            continue

        check_sse_error(parsed)

        ev_sig = _extract_event_thought_signature(parsed)
        if ev_sig:
            current_thought_sig = ev_sig

        usage = extract_usage(parsed)
        if usage:
            input_tokens = usage.get("prompt_tokens", input_tokens)
            output_tokens = usage.get("completion_tokens", output_tokens)

        finish_reason = extract_finish_reason(parsed)
        if finish_reason:
            if finish_reason in ("length", "max_tokens"):
                upstream_stop_reason = "max_tokens"
            elif finish_reason in ("stop_sequence", "tool_use"):
                upstream_stop_reason = finish_reason
            else:
                upstream_stop_reason = "end_turn"

        thought_delta = extract_thought_delta(parsed)
        if thought_delta:
            if text_block_open:
                yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': text_block_index})}\n\n"
                text_block_open = False

            if not thinking_block_open:
                thinking_block_index = next_index
                next_index += 1
                yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': thinking_block_index, 'content_block': {'type': 'thinking', 'thinking': ''}})}\n\n"
                thinking_block_open = True

            yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': thinking_block_index, 'delta': {'type': 'thinking_delta', 'thinking': thought_delta}})}\n\n"

        text_delta = extract_text_delta(parsed)
        if text_delta:
            if thinking_block_open:
                yield from _close_thinking()

            if not text_block_open:
                text_block_index = next_index
                next_index += 1
                yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': text_block_index, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
                text_block_open = True

            yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': text_block_index, 'delta': {'type': 'text_delta', 'text': text_delta}})}\n\n"

        fc_list = extract_function_calls(parsed)
        if fc_list:
            if thinking_block_open:
                yield from _close_thinking()

            if text_block_open:
                yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': text_block_index})}\n\n"
                text_block_open = False

            for fc in fc_list:
                call_id = fc.get("id") or f"toolu_{uuid.uuid4().hex[:16]}"
                fc["id"] = call_id
                name = fc.get("name", "")
                args = fc.get("args") or {}
                sig = fc.get("thought_signature") or fc.get("thoughtSignature")
                if not sig:
                    resp = parsed.get("response") if isinstance(parsed.get("response"), dict) else parsed
                    cands = resp.get("candidates") if isinstance(resp, dict) else None
                    if cands and isinstance(cands, list) and len(cands) > 0 and isinstance(cands[0], dict):
                        cand = cands[0]
                        sig = cand.get("thoughtSignature") or cand.get("thought_signature")
                        if not sig and isinstance(cand.get("content"), dict):
                            sig = cand["content"].get("thoughtSignature") or cand["content"].get("thought_signature")
                if sig:
                    fc["thought_signature"] = sig
                    cache_thought_signature(call_id=call_id, signature=sig, name=name, args=args)
                if call_id and name:
                    cache_tool_name(call_id, name)

            accumulated_tool_calls.extend(fc_list)

    # 3. Close open blocks
    if thinking_block_open:
        yield from _close_thinking()

    if text_block_open:
        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': text_block_index})}\n\n"
        text_block_open = False

    # 4. Emit accumulated tool calls
    for call in accumulated_tool_calls:
        tool_index = next_index
        next_index += 1
        call_id = call.get("id") or f"toolu_{uuid.uuid4().hex[:16]}"
        call_name = call.get("name", "")
        call_args = call.get("args")
        if call_args is None:
            call_args = {}
        if call_id and call_name:
            cache_tool_name(call_id, call_name)
        thought_sig = call.get("thought_signature") or call.get("thoughtSignature")
        if thought_sig:
            cache_thought_signature(call_id=call_id, signature=thought_sig, name=call_name, args=call_args)
        json_args = json.dumps(call_args) if not isinstance(call_args, str) else call_args

        block_start = {
            "type": "content_block_start",
            "index": tool_index,
            "content_block": {
                "type": "tool_use",
                "id": call_id,
                "name": call_name,
                "input": {},
            },
        }
        yield f"event: content_block_start\ndata: {json.dumps(block_start)}\n\n"

        block_delta = {
            "type": "content_block_delta",
            "index": tool_index,
            "delta": {
                "type": "input_json_delta",
                "partial_json": json_args,
            },
        }
        yield f"event: content_block_delta\ndata: {json.dumps(block_delta)}\n\n"

        block_stop = {
            "type": "content_block_stop",
            "index": tool_index,
        }
        yield f"event: content_block_stop\ndata: {json.dumps(block_stop)}\n\n"

    # If stream produced no thinking, text, or tools, ensure at least one empty text block
    if next_index == 0:
        yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': 0})}\n\n"

    # 5. Determine stop_reason
    if accumulated_tool_calls:
        final_stop_reason = "tool_use"
    elif upstream_stop_reason:
        final_stop_reason = upstream_stop_reason
    else:
        final_stop_reason = "end_turn"

    # 6. message_delta
    msg_delta_payload = {
        "type": "message_delta",
        "delta": {
            "stop_reason": final_stop_reason,
            "stop_sequence": None,
        },
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    }
    yield f"event: message_delta\ndata: {json.dumps(msg_delta_payload)}\n\n"

    # 7. message_stop
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
