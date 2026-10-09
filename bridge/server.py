"""OpenAI-compatible HTTP server adapter for Google Cloud Code Assist."""

import http.server
import itertools
import json
import sys
import urllib.parse
import uuid
from typing import Any

from bridge import __version__
from bridge.auth import KeychainTokenProvider, AuthenticationError as AuthAuthenticationError
from bridge.client import (
    CloudCodeClient,
    BridgeError,
    AuthenticationError as ClientAuthenticationError,
    ForbiddenError,
    InvalidRequestError,
    ModelNotFoundError,
    RateLimitError,
    CapacityExhaustedError,
    UpstreamTimeoutError,
)
from bridge.transform import (
    openai_to_cloudcode_request,
    parse_cloudcode_sse_event,
    extract_text_delta,
    extract_thought_delta,
    extract_function_calls,
    extract_finish_reason,
    extract_usage,
    build_openai_chunk,
    build_openai_completion,
    build_openai_model_list,
    build_openai_error_response,
    check_sse_error,
    cache_thought_signature,
)
from bridge.dashboard import render_dashboard, get_status_data
from bridge.i18n import parse_accept_language
from bridge.security import validate_api_key, is_loopback_host
from bridge.anthropic import (
    _extract_event_thought_signature,
    anthropic_to_cloudcode_request,
    build_anthropic_message,
    build_anthropic_sse_events,
    build_anthropic_error_response,
)
from bridge.responses import (
    responses_to_cloudcode_request,
    build_responses_completion,
    build_responses_sse_events,
    build_responses_error_response,
)


class OpenAIRequestHandler(http.server.BaseHTTPRequestHandler):
    """Handles OpenAI REST endpoints and delegates to CloudCodeClient."""

    timeout = 60.0
    client: CloudCodeClient
    project: str
    api_key: str | None = None

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default HTTP request logging to stderr."""
        pass

    def _is_valid_host(self) -> bool:
        """Validates incoming Host header against allowed loopback/bound hosts to prevent DNS rebinding."""
        host_header = self.headers.get("Host", "").strip()
        if not host_header:
            return False

        if host_header.startswith("["):
            idx = host_header.find("]")
            if idx == -1:
                return False
            hostname = host_header[1:idx].lower()
        else:
            hostname = host_header.split(":")[0].strip().lower()

        allowed = {"127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0"}
        server_host = getattr(self.server, "server_address", [None])[0]
        if server_host and server_host not in ("0.0.0.0", "::"):
            allowed.add(server_host.lower())

        return hostname in allowed or hostname.startswith("127.")

    def _is_authenticated(self) -> bool:
        expected = getattr(self.server, "api_key", None)
        if expected is None:
            expected = getattr(self, "api_key", None)
        return validate_api_key(expected, self.headers)

    def do_OPTIONS(self) -> None:
        """Handles CORS preflight requests."""
        if not self._is_valid_host():
            self.send_response(421)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        parsed_path = urllib.parse.urlparse(self.path).path
        if parsed_path.startswith("/v1/") or parsed_path in ("/", "/api/status"):
            # Inference and admin endpoints forbid browser cross-origin preflight requests
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, x-api-key, anthropic-version, anthropic-beta, anthropic-auth-token, openai-beta, openai-organization, openai-project",
        )
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_json(
        self,
        status_code: int,
        data: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        req_path = urllib.parse.urlparse(getattr(self, "path", "")).path
        if not req_path.startswith("/v1/") and req_path not in ("/", "/api/status"):
            self.send_header("Access-Control-Allow-Origin", "*")
        sent_connection = False
        if headers:
            for k, v in headers.items():
                if k.lower() == "connection":
                    sent_connection = True
                self.send_header(k, v)
        if getattr(self, "close_connection", False) and not sent_connection:
            self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _get_error_details(self, exc: Exception) -> tuple[int, str]:
        if isinstance(exc, (InvalidRequestError, ValueError)):
            return 400, "invalid_request_error"
        if isinstance(exc, (ClientAuthenticationError, AuthAuthenticationError)) or exc.__class__.__name__ == "AuthenticationError":
            return 401, "authentication_error"
        if isinstance(exc, ForbiddenError):
            return 403, "permission_denied"
        if isinstance(exc, ModelNotFoundError):
            return 404, "invalid_request_error"
        if isinstance(exc, RateLimitError):
            return 429, "rate_limit_error"
        if isinstance(exc, CapacityExhaustedError):
            return 503, "api_error"
        if isinstance(exc, UpstreamTimeoutError):
            return 504, "api_error"
        return 500, "api_error"

    def _send_error(self, exc: Exception) -> None:
        status_code, error_type = self._get_error_details(exc)
        if status_code == 401:
            if hasattr(self, "client") and hasattr(self.client, "token_provider") and hasattr(self.client.token_provider, "invalidate"):
                try:
                    self.client.token_provider.invalidate()
                except Exception:
                    pass

        code, err_payload = build_openai_error_response(status_code, str(exc), error_type)
        self._send_json(code, err_payload)

    def do_GET(self) -> None:
        if not self._is_valid_host():
            self._send_json(
                421,
                {
                    "error": {
                        "message": f"Misdirected Request: host '{self.headers.get('Host', '')}' is not permitted",
                        "type": "misdirected_request",
                        "code": 421,
                    }
                },
            )
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        if not path:
            path = "/"

        if path == "/":
            query_params = urllib.parse.parse_qs(parsed.query)
            if "lang" in query_params and query_params["lang"]:
                param_lang = query_params["lang"][0].strip().lower()
                client_lang = "es" if param_lang.startswith("es") else "en"
            else:
                accept_lang = self.headers.get("Accept-Language", "")
                client_lang = parse_accept_language(accept_lang)

            host = self.server.server_address[0] if hasattr(self.server, "server_address") else "127.0.0.1"
            port = self.server.server_address[1] if hasattr(self.server, "server_address") else 24980
            status_data = get_status_data(self.client, self.project, host, port)
            html_content = render_dashboard(
                host=status_data["host"],
                port=status_data["port"],
                auth_status=status_data["auth"],
                models_count=status_data["models_count"],
                lang=client_lang,
                api_key="configured" if getattr(self.server, "api_key", None) else None,
            )
            encoded = html_content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return

        if path == "/api/status":
            host = self.server.server_address[0] if hasattr(self.server, "server_address") else "127.0.0.1"
            port = self.server.server_address[1] if hasattr(self.server, "server_address") else 24980
            status_data = get_status_data(self.client, self.project, host, port)
            self._send_json(200, status_data)
            return

        if path == "/healthz":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "service": "agy-model-bridge",
                    "version": __version__,
                },
            )
            return

        if path == "/v1/models":
            if not self._is_authenticated():
                code, err = build_openai_error_response(401, "Invalid or missing API key", "authentication_error")
                self._send_json(code, err)
                return
            try:
                models = self.client.fetch_available_models(self.project)
                resp_data = build_openai_model_list(models)
                self._send_json(200, resp_data)
            except Exception as exc:
                self._send_error(exc)
            return

        self._send_json(
            404,
            {
                "error": {
                    "message": f"Endpoint not found: {path}",
                    "type": "invalid_request_error",
                    "code": 404,
                }
            },
        )

    def do_POST(self) -> None:
        if not self._is_valid_host():
            self._send_json(
                421,
                {
                    "error": {
                        "message": f"Misdirected Request: host '{self.headers.get('Host', '')}' is not permitted",
                        "type": "misdirected_request",
                        "code": 421,
                    }
                },
            )
            return

        raw_content_length = self.headers.get("Content-Length")
        if raw_content_length is None:
            content_length = 0
        else:
            try:
                content_length = int(raw_content_length)
                if content_length < 0:
                    raise ValueError("Negative Content-Length")
            except (ValueError, TypeError):
                self.close_connection = True
                self._send_json(
                    400,
                    {
                        "error": {
                            "message": "Invalid Content-Length header",
                            "type": "invalid_request_error",
                            "code": 400,
                        }
                    },
                )
                return

        if content_length > 10 * 1024 * 1024:
            self.close_connection = True
            self._send_json(
                413,
                {
                    "error": {
                        "message": "Payload Too Large: maximum allowed body is 10MB",
                        "type": "invalid_request_error",
                        "code": 413,
                    }
                },
            )
            return

        path = urllib.parse.urlparse(self.path).path.rstrip("/")
        if not path:
            path = "/"

        if path not in ("/v1/chat/completions", "/v1/messages", "/v1/responses"):
            self._send_json(
                404,
                {
                    "error": {
                        "message": f"Endpoint not found: {path}",
                        "type": "invalid_request_error",
                        "code": 404,
                    }
                },
            )
            return

        if not self._is_authenticated():
            self.close_connection = True
            if path == "/v1/messages":
                code, err = build_anthropic_error_response(401, "Invalid or missing API key")
                self._send_json(code, err, headers={"Connection": "close"})
            else:
                code, err = build_openai_error_response(401, "Invalid or missing API key", "authentication_error")
                self._send_json(code, err, headers={"Connection": "close"})
            return

        raw_body = self.rfile.read(content_length) if content_length > 0 else b""
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception as e:
            self.close_connection = True
            if path == "/v1/messages":
                code, err = build_anthropic_error_response(400, f"Malformed JSON payload: {e}")
                self._send_json(code, err, headers={"Connection": "close"})
            else:
                self._send_json(
                    400,
                    {
                        "error": {
                            "message": f"Malformed JSON payload: {e}",
                            "type": "invalid_request_error",
                            "code": 400,
                        }
                    },
                    headers={"Connection": "close"},
                )
            return

        if not isinstance(payload, dict):
            self.close_connection = True
            if path == "/v1/messages":
                code, err = build_anthropic_error_response(400, "Invalid request body: expected JSON object")
                self._send_json(code, err, headers={"Connection": "close"})
            else:
                self._send_json(
                    400,
                    {
                        "error": {
                            "message": "Invalid request body: expected JSON object",
                            "type": "invalid_request_error",
                            "code": 400,
                        }
                    },
                    headers={"Connection": "close"},
                )
            return

        if path == "/v1/chat/completions":
            self._handle_chat_completion(payload)
        elif path == "/v1/messages":
            self._handle_anthropic_messages(payload)
        elif path == "/v1/responses":
            self._handle_responses(payload)

    def _send_anthropic_error(self, exc: Exception) -> None:
        status_code, _ = self._get_error_details(exc)
        if status_code == 401:
            if hasattr(self, "client") and hasattr(self.client, "token_provider") and hasattr(self.client.token_provider, "invalidate"):
                try:
                    self.client.token_provider.invalidate()
                except Exception:
                    pass
        code, err_payload = build_anthropic_error_response(status_code, str(exc))
        self._send_json(code, err_payload)

    def _handle_anthropic_messages(self, payload: dict[str, Any]) -> None:
        try:
            stream = bool(payload.get("stream", False))
            model, contents, system_instruction, generation_config, tools, tool_config = anthropic_to_cloudcode_request(
                payload, self.project
            )
        except ValueError as ve:
            code, err = build_anthropic_error_response(400, str(ve))
            self._send_json(code, err)
            return
        except Exception as exc:
            self._send_anthropic_error(exc)
            return

        extra_kwargs: dict[str, Any] = {}
        if generation_config is not None:
            extra_kwargs["generation_config"] = generation_config
        if tools is not None:
            extra_kwargs["tools"] = tools
        if tool_config is not None:
            extra_kwargs["tool_config"] = tool_config

        if stream:
            try:
                stream_gen = self.client.stream_generate_content(
                    self.project, model, contents, system_instruction, **extra_kwargs
                )
            except Exception as exc:
                self._send_anthropic_error(exc)
                return

            buffered_lines: list[str] = []
            found_valid_event = False
            try:
                for line in stream_gen:
                    buffered_lines.append(line)
                    stripped = line.strip()
                    if not stripped or stripped.startswith(":"):
                        continue
                    parsed = parse_cloudcode_sse_event(line)
                    if parsed is not None:
                        check_sse_error(parsed)
                        found_valid_event = True
                        break
                if not found_valid_event:
                    raise InvalidRequestError("Stream ended without data")
            except Exception as exc:
                if hasattr(stream_gen, "close"):
                    stream_gen.close()
                self._send_anthropic_error(exc)
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()

            combined_gen = itertools.chain(buffered_lines, stream_gen)

            try:
                try:
                    for event_str in build_anthropic_sse_events(combined_gen, model):
                        self.wfile.write(event_str.encode("utf-8"))
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as exc:
                    sys.stderr.write(f"Error during Anthropic stream: {exc}\n")
                    sys.stderr.flush()
                    try:
                        err_payload = json.dumps({"type": "error", "error": {"type": "api_error", "message": str(exc)}})
                        self.wfile.write(f"event: error\ndata: {err_payload}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    except Exception:
                        pass
            finally:
                if hasattr(stream_gen, "close"):
                    stream_gen.close()
                self.close_connection = True
            return

        try:
            stream_gen = self.client.stream_generate_content(
                self.project, model, contents, system_instruction, **extra_kwargs
            )
            try:
                collected_text: list[str] = []
                collected_thoughts: list[str] = []
                collected_tool_calls: list[dict[str, Any]] = []
                latest_thought_sig: str | None = None
                last_usage = None
                last_finish = "end_turn"
                event_count = 0
                has_finish_reason = False
                for line in stream_gen:
                    parsed = parse_cloudcode_sse_event(line)
                    if parsed is not None:
                        event_count += 1
                        check_sse_error(parsed)
                        sig = _extract_event_thought_signature(parsed)
                        if sig:
                            latest_thought_sig = sig
                        usage = extract_usage(parsed)
                        if usage:
                            last_usage = usage
                        fr = extract_finish_reason(parsed)
                        if fr:
                            has_finish_reason = True
                            if fr in ("length", "max_tokens"):
                                last_finish = "max_tokens"
                            elif fr in ("stop_sequence", "tool_use"):
                                last_finish = fr
                            else:
                                last_finish = "end_turn"
                        thought = extract_thought_delta(parsed)
                        if thought:
                            collected_thoughts.append(thought)
                        delta = extract_text_delta(parsed)
                        if delta:
                            collected_text.append(delta)
                        fc_list = extract_function_calls(parsed)
                        if fc_list:
                            collected_tool_calls.extend(fc_list)

                if (
                    event_count == 0
                    and not collected_text
                    and not collected_thoughts
                    and not collected_tool_calls
                    and not has_finish_reason
                ):
                    raise BridgeError("Stream ended without data")

                if collected_tool_calls:
                    last_finish = "tool_use"

                msg_id = f"msg_{uuid.uuid4().hex[:16]}"
                full_text = "".join(collected_text)
                full_thought = "".join(collected_thoughts) if collected_thoughts else None
                resp_obj = build_anthropic_message(
                    message_id=msg_id,
                    model=model,
                    text=full_text,
                    usage=last_usage,
                    stop_reason=last_finish,
                    thinking=full_thought,
                    tool_calls=collected_tool_calls if collected_tool_calls else None,
                    signature=latest_thought_sig,
                )
                try:
                    self._send_json(200, resp_obj)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            finally:
                if hasattr(stream_gen, "close"):
                    stream_gen.close()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self._send_anthropic_error(exc)

    def _handle_responses(self, payload: dict[str, Any]) -> None:
        try:
            stream = bool(payload.get("stream", False))
            model, contents, system_instruction, generation_config, tools = responses_to_cloudcode_request(
                payload, self.project
            )
        except ValueError as ve:
            code, err = build_responses_error_response(400, str(ve))
            self._send_json(code, err)
            return
        except Exception as exc:
            self._send_error(exc)
            return

        extra_kwargs: dict[str, Any] = {}
        if generation_config is not None:
            extra_kwargs["generation_config"] = generation_config
        if tools is not None:
            extra_kwargs["tools"] = tools

        if stream:
            try:
                stream_gen = self.client.stream_generate_content(
                    self.project, model, contents, system_instruction, **extra_kwargs
                )
            except Exception as exc:
                self._send_error(exc)
                return

            buffered_lines: list[str] = []
            found_valid_event = False
            try:
                for line in stream_gen:
                    buffered_lines.append(line)
                    stripped = line.strip()
                    if not stripped or stripped.startswith(":"):
                        continue
                    parsed = parse_cloudcode_sse_event(line)
                    if parsed is not None:
                        check_sse_error(parsed)
                        found_valid_event = True
                        break
                if not found_valid_event:
                    raise InvalidRequestError("Stream ended without data")
            except Exception as exc:
                if hasattr(stream_gen, "close"):
                    stream_gen.close()
                self._send_error(exc)
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()

            response_id = f"resp_{uuid.uuid4().hex[:16]}"
            combined_gen = itertools.chain(buffered_lines, stream_gen)

            try:
                try:
                    for event_str in build_responses_sse_events(combined_gen, model, response_id=response_id):
                        self.wfile.write(event_str.encode("utf-8"))
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as exc:
                    sys.stderr.write(f"Error during Responses stream: {exc}\n")
                    sys.stderr.flush()
                    try:
                        err_payload = json.dumps({
                            "type": "response.failed",
                            "response": {
                                "id": response_id,
                                "status": "failed",
                                "error": {"message": str(exc)},
                            },
                        })
                        self.wfile.write(f"event: response.failed\ndata: {err_payload}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    except Exception:
                        pass
            finally:
                if hasattr(stream_gen, "close"):
                    stream_gen.close()
                self.close_connection = True
            return

        try:
            stream_gen = self.client.stream_generate_content(
                self.project, model, contents, system_instruction, **extra_kwargs
            )
            try:
                collected_text: list[str] = []
                collected_tool_calls: list[dict[str, Any]] = []
                last_usage = None
                event_count = 0
                has_finish_reason = False
                for line in stream_gen:
                    parsed = parse_cloudcode_sse_event(line)
                    if parsed is not None:
                        event_count += 1
                        check_sse_error(parsed)
                        usage = extract_usage(parsed)
                        if usage:
                            last_usage = usage
                        fr = extract_finish_reason(parsed)
                        if fr:
                            has_finish_reason = True
                        delta = extract_text_delta(parsed)
                        if delta:
                            collected_text.append(delta)
                        fcs = extract_function_calls(parsed)
                        if fcs:
                            collected_tool_calls.extend(fcs)

                if event_count == 0 and not collected_text and not has_finish_reason and not collected_tool_calls:
                    raise BridgeError("Stream ended without data")

                resp_id = f"resp_{uuid.uuid4().hex[:16]}"
                full_text = "".join(collected_text)
                resp_obj = build_responses_completion(
                    response_id=resp_id,
                    model=model,
                    text=full_text,
                    usage=last_usage,
                    tool_calls=collected_tool_calls if collected_tool_calls else None,
                )
                try:
                    self._send_json(200, resp_obj)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            finally:
                if hasattr(stream_gen, "close"):
                    stream_gen.close()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self._send_error(exc)

    def _handle_chat_completion(self, payload: dict[str, Any]) -> None:
        try:
            stream = bool(payload.get("stream", False))
            model, contents, system_instruction, generation_config, tools = openai_to_cloudcode_request(
                payload, self.project
            )
        except ValueError as ve:
            self._send_json(
                400,
                {
                    "error": {
                        "message": str(ve),
                        "type": "invalid_request_error",
                        "code": 400,
                    }
                },
            )
            return
        except Exception as exc:
            self._send_error(exc)
            return

        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        extra_kwargs: dict[str, Any] = {}
        if generation_config is not None:
            extra_kwargs["generation_config"] = generation_config
        if tools is not None:
            extra_kwargs["tools"] = tools

        if stream:
            try:
                stream_gen = self.client.stream_generate_content(
                    self.project, model, contents, system_instruction, **extra_kwargs
                )
            except Exception as exc:
                self._send_error(exc)
                return

            buffered_lines: list[str] = []
            found_valid_event = False
            try:
                for line in stream_gen:
                    buffered_lines.append(line)
                    stripped = line.strip()
                    if not stripped or stripped.startswith(":"):
                        continue
                    parsed = parse_cloudcode_sse_event(line)
                    if parsed is not None:
                        check_sse_error(parsed)
                        found_valid_event = True
                        break
                if not found_valid_event:
                    raise InvalidRequestError("Stream ended without data")
            except Exception as exc:
                if hasattr(stream_gen, "close"):
                    stream_gen.close()
                self._send_error(exc)
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()

            last_finish_reason: str = "stop"
            last_usage: dict[str, int] | None = None
            is_first_chunk: bool = True
            tool_calls_emitted: bool = False
            tc_index: int = 0

            def process_line(line: str) -> None:
                nonlocal last_finish_reason, last_usage, is_first_chunk, tool_calls_emitted, tc_index
                parsed = parse_cloudcode_sse_event(line)
                if not parsed:
                    return
                check_sse_error(parsed)
                delta_text = extract_text_delta(parsed)
                reason = extract_finish_reason(parsed)
                if reason:
                    last_finish_reason = reason
                usage = extract_usage(parsed)
                if usage:
                    last_usage = usage

                fcs = extract_function_calls(parsed)
                delta_tool_calls = None
                if fcs:
                    tool_calls_emitted = True
                    delta_tool_calls = []
                    for fc in fcs:
                        tc_id = fc.get("id") or f"call_{uuid.uuid4().hex[:12]}"
                        if tc_id.startswith("toolu_"):
                            tc_id = f"call_{tc_id[6:]}"
                        args = fc.get("args", {})
                        args_str = json.dumps(args) if isinstance(args, (dict, list)) else str(args or "{}")
                        thought_sig = fc.get("thought_signature") or fc.get("thoughtSignature")
                        if thought_sig:
                            cache_thought_signature(call_id=tc_id, signature=thought_sig, name=fc.get("name"), args=args)
                        call_dict: dict[str, Any] = {
                            "index": tc_index,
                            "id": tc_id,
                            "type": "function",
                            "function": {
                                "name": fc.get("name", ""),
                                "arguments": args_str,
                            },
                        }
                        if thought_sig:
                            call_dict["thought_signature"] = thought_sig
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
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()

            try:
                try:
                    for line in buffered_lines:
                        process_line(line)

                    for line in stream_gen:
                        process_line(line)

                    if tool_calls_emitted:
                        last_finish_reason = "tool_calls"

                    stop_chunk = build_openai_chunk(
                        completion_id,
                        model,
                        finish_reason=last_finish_reason,
                        usage=last_usage,
                    )
                    self.wfile.write(stop_chunk.encode("utf-8"))
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as exc:
                    print(f"Error during stream: {exc}", file=sys.stderr)
                    try:
                        err_code, err_type = self._get_error_details(exc)
                        err_payload = json.dumps({"error": {"message": str(exc), "type": err_type, "code": err_code}})
                        self.wfile.write(f"data: {err_payload}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    except Exception:
                        pass

            finally:
                if hasattr(stream_gen, "close"):
                    stream_gen.close()
                self.close_connection = True
        else:
            try:
                stream_gen = self.client.stream_generate_content(
                    self.project, model, contents, system_instruction, **extra_kwargs
                )
                try:
                    text_parts: list[str] = []
                    collected_tool_calls: list[dict[str, Any]] = []
                    last_usage: dict[str, int] | None = None
                    last_finish_reason: str = "stop"
                    event_count = 0
                    has_finish_reason = False
                    for line in stream_gen:
                        parsed = parse_cloudcode_sse_event(line)
                        if not parsed:
                            continue
                        event_count += 1
                        check_sse_error(parsed)
                        delta = extract_text_delta(parsed)
                        if delta:
                            text_parts.append(delta)
                        reason = extract_finish_reason(parsed)
                        if reason:
                            has_finish_reason = True
                            last_finish_reason = reason
                        usage = extract_usage(parsed)
                        if usage:
                            last_usage = usage
                        fcs = extract_function_calls(parsed)
                        if fcs:
                            collected_tool_calls.extend(fcs)

                    if event_count == 0 and not text_parts and not has_finish_reason and not collected_tool_calls:
                        raise BridgeError("Stream ended without data")

                    formatted_tool_calls = None
                    if collected_tool_calls:
                        last_finish_reason = "tool_calls"
                        formatted_tool_calls = []
                        for fc in collected_tool_calls:
                            tc_id = fc.get("id") or f"call_{uuid.uuid4().hex[:12]}"
                            if tc_id.startswith("toolu_"):
                                tc_id = f"call_{tc_id[6:]}"
                            args = fc.get("args", {})
                            args_str = json.dumps(args) if isinstance(args, (dict, list)) else str(args or "{}")
                            thought_sig = fc.get("thought_signature") or fc.get("thoughtSignature")
                            if thought_sig:
                                cache_thought_signature(call_id=tc_id, signature=thought_sig, name=fc.get("name"), args=args)
                            call_dict: dict[str, Any] = {
                                "id": tc_id,
                                "type": "function",
                                "function": {
                                    "name": fc.get("name", ""),
                                    "arguments": args_str,
                                },
                            }
                            if thought_sig:
                                call_dict["thought_signature"] = thought_sig
                            formatted_tool_calls.append(call_dict)

                    full_text = "".join(text_parts)
                    completion_obj = build_openai_completion(
                        completion_id,
                        model,
                        full_text,
                        usage=last_usage,
                        finish_reason=last_finish_reason,
                        tool_calls=formatted_tool_calls,
                    )
                    try:
                        self._send_json(200, completion_obj)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                finally:
                    if hasattr(stream_gen, "close"):
                        stream_gen.close()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                self._send_error(exc)


def create_server(
    host: str = "127.0.0.1",
    port: int = 24980,
    client: Any | None = None,
    project: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    no_auth: bool = False,
) -> http.server.ThreadingHTTPServer:
    """Instantiates and configures a ThreadingHTTPServer instance."""
    if no_auth and not is_loopback_host(host):
        raise ValueError(
            f"Refusing to disable authentication (--no-auth) on non-loopback host '{host}'. "
            "--no-auth is only permitted on loopback addresses (127.0.0.1, localhost, ::1)."
        )

    if no_auth or api_key == "":
        api_key = None
    elif api_key is None:
        from bridge.security import get_or_create_api_key
        api_key = get_or_create_api_key()

    if client is None:
        token_provider = KeychainTokenProvider()
        kwargs: dict[str, Any] = {"token_provider": token_provider}
        if base_url:
            kwargs["base_url"] = base_url
        client = CloudCodeClient(**kwargs)
    if project is None:
        import os
        project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("ANTIGRAVITY_PROJECT")
        if not project:
            try:
                discovery = client.load_code_assist()
            except Exception as exc:
                raise RuntimeError(
                    f"Could not discover Google Cloud project ID: {exc}. "
                    "Ensure Antigravity is running and authenticated, or specify --project."
                ) from exc
            discovered = discovery.get("project")
            if not discovered:
                raise RuntimeError(
                    "Could not discover Google Cloud project ID. "
                    "Ensure Antigravity is running and authenticated, or specify --project."
                )
            project = discovered

    class ConfiguredHandler(OpenAIRequestHandler):
        pass

    ConfiguredHandler.client = client
    ConfiguredHandler.project = project
    ConfiguredHandler.api_key = api_key

    server = http.server.ThreadingHTTPServer((host, port), ConfiguredHandler)
    server.daemon_threads = True
    server.api_key = api_key
    return server


def run_server(
    host: str = "127.0.0.1",
    port: int = 24980,
    project: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    no_auth: bool = False,
) -> None:
    """Starts the ThreadingHTTPServer serving OpenAI-compatible endpoints."""
    server = create_server(
        host=host,
        port=port,
        project=project,
        base_url=base_url,
        api_key=api_key,
        no_auth=no_auth,
    )
    actual_port = server.server_address[1]
    print(f"Antigravity Model Bridge listening on http://{host}:{actual_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        server.server_close()
