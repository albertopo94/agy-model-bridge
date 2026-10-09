"""OpenAI-compatible HTTP server adapter for Google Cloud Code Assist."""

from collections.abc import Iterator
from dataclasses import dataclass, field
import http.server
import itertools
import json
import random
import re
import sys
import threading
import time
import urllib.parse
import uuid
from typing import Any

from bridge import __version__
from bridge.auth import KeychainTokenProvider
from bridge.client import CloudCodeClient
from bridge.errors import (
    AuthenticationError,
    BridgeError,
    CapacityExhaustedError,
    ForbiddenError,
    InvalidRequestError,
    ModelNotFoundError,
    RateLimitError,
    UpstreamTimeoutError,
    UpstreamError,
)
from bridge.events import parse_stream_event
from bridge.transform import (
    parse_cloudcode_sse_event,
    build_openai_model_list,
    build_openai_error_response,
    check_sse_error,
    cache_thought_signature,
    OpenAIProtocolAdapter,
    cache_tool_name,
)
from bridge.dashboard import render_dashboard, get_status_data
from bridge.i18n import parse_accept_language
from bridge.security import validate_api_key, is_loopback_host
from bridge.anthropic import (
    AnthropicProtocolAdapter,
    _extract_event_thought_signature,
    build_anthropic_error_response,
)
from bridge.responses import (
    ResponsesProtocolAdapter,
    build_responses_error_response,
)

SAFE_REQUEST_ID_REGEX = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def sanitize_request_id(request_id: str | None) -> str:
    """Returns the request ID if safe (alphanumeric, dot, underscore, dash, max 64 chars),
    or generates a fresh random request ID to prevent CRLF injection or header splitting.
    """
    if request_id:
        val = request_id.strip()
        if SAFE_REQUEST_ID_REGEX.match(val):
            return val
    return f"req_{uuid.uuid4().hex[:12]}"


@dataclass
class CollectedStreamData:
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] | None = None
    finish_reason: str = "stop"
    thoughts: str = ""
    thought_signature: str | None = None


class OpenAIRequestHandler(http.server.BaseHTTPRequestHandler):
    """Handles OpenAI REST endpoints and delegates to CloudCodeClient."""

    timeout = 60.0
    client: CloudCodeClient
    project: str
    api_key: str | None = None
    request_id: str = ""
    command: str = ""
    path: str = ""
    start_time: float = 0.0
    concurrency_semaphore: threading.Semaphore | None = None
    concurrency_timeout: float = 5.0
    max_retries: int = 3
    initial_retry_delay: float = 0.5

    def parse_request(self) -> bool:
        if not super().parse_request():
            return False
        hdr_val = self.headers.get("X-Request-ID") if self.headers else None
        self.request_id = sanitize_request_id(hdr_val)
        self.start_time = time.monotonic()
        return True

    def _ensure_request_id(self) -> str:
        if not getattr(self, "request_id", ""):
            headers = getattr(self, "headers", None)
            hdr_val = headers.get("X-Request-ID") if headers else None
            self.request_id = sanitize_request_id(hdr_val)
        return self.request_id

    def _log_structured(
        self,
        status: int,
        latency_ms: int = 0,
        model: str = "",
        usage: dict[str, int] | None = None,
        error: str | None = None,
    ) -> None:
        self._ensure_request_id()
        start_t = getattr(self, "start_time", None)
        if latency_ms == 0 and start_t:
            latency_ms = int((time.monotonic() - float(start_t)) * 1000)
        command = getattr(self, "command", "") or "HTTP"
        path = getattr(self, "path", "") or "/"
        parts = [f"[{self.request_id}]", command, path, f"-> {status}", f"({latency_ms}ms)"]
        if model:
            parts.append(f"model={model}")
        if usage:
            parts.append(f"tokens={usage.get('total_tokens', 0)} ({usage.get('prompt_tokens', 0)}in/{usage.get('completion_tokens', 0)}out)")
        if error:
            parts.append(f"error={error}")
        msg = " ".join(parts) + "\n"
        sys.stderr.write(msg)
        sys.stderr.flush()

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

        return hostname in allowed or is_loopback_host(hostname)

    def _is_authenticated(self) -> bool:
        expected = getattr(self.server, "api_key", None)
        if expected is None:
            expected = getattr(self, "api_key", None)
        return validate_api_key(expected, self.headers)

    def do_OPTIONS(self) -> None:
        """Handles CORS preflight requests."""
        self._ensure_request_id()
        if not self._is_valid_host():
            self.send_response(421)
            self.send_header("X-Request-ID", self.request_id)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        parsed_path = urllib.parse.urlparse(self.path).path
        if parsed_path.startswith("/v1/") or parsed_path in ("/", "/api/status"):
            # Inference and admin endpoints forbid browser cross-origin preflight requests
            self.send_response(403)
            self.send_header("X-Request-ID", self.request_id)
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
        self.send_header("X-Request-ID", self.request_id)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_json(
        self,
        status_code: int,
        data: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        self._ensure_request_id()
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Request-ID", self.request_id)
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
        if isinstance(exc, AuthenticationError):
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
        if isinstance(exc, UpstreamError):
            return exc.status_code or 500, "api_error"
        if isinstance(exc, BridgeError):
            return 500, "api_error"
        return 500, "internal_server_error"

    def _send_error(self, exc: Exception) -> None:
        self._ensure_request_id()
        status_code, error_type = self._get_error_details(exc)
        if status_code == 401:
            if hasattr(self, "client") and hasattr(self.client, "token_provider") and hasattr(self.client.token_provider, "invalidate"):
                try:
                    self.client.token_provider.invalidate()
                except Exception:
                    pass

        if error_type == "internal_server_error":
            self._log_structured(status=500, error=str(exc))
            client_msg = f"Internal server error [{self.request_id}]"
        else:
            client_msg = str(exc)

        code, err_payload = build_openai_error_response(status_code, client_msg, error_type)
        headers: dict[str, str] = {}
        if status_code == 429:
            retry_after = getattr(exc, "retry_after", None) or 5
            headers["Retry-After"] = str(retry_after)
        self._send_json(code, err_payload, headers=headers)

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

            server_addr = getattr(self.server, "server_address", None)
            host = server_addr[0] if isinstance(server_addr, tuple) and len(server_addr) > 0 else "127.0.0.1"
            port = int(server_addr[1]) if isinstance(server_addr, tuple) and len(server_addr) > 1 else 24980
            status_data = get_status_data(self.client, self.project, str(host), port)
            html_content = render_dashboard(
                host=status_data["host"],
                port=status_data["port"],
                auth_status=status_data["auth"],
                models_count=status_data["models_count"],
                lang=client_lang,
                api_key="configured" if getattr(self.server, "api_key", None) else None,
            )
            encoded = html_content.encode("utf-8")
            self._ensure_request_id()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("X-Request-ID", self.request_id)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return

        if path == "/api/status":
            server_addr = getattr(self.server, "server_address", None)
            host = server_addr[0] if isinstance(server_addr, tuple) and len(server_addr) > 0 else "127.0.0.1"
            port = int(server_addr[1]) if isinstance(server_addr, tuple) and len(server_addr) > 1 else 24980
            status_data = get_status_data(self.client, self.project, str(host), port)
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
        self._ensure_request_id()
        status_code, error_type = self._get_error_details(exc)
        if status_code == 401:
            if hasattr(self, "client") and hasattr(self.client, "token_provider") and hasattr(self.client.token_provider, "invalidate"):
                try:
                    self.client.token_provider.invalidate()
                except Exception:
                    pass
        if error_type == "internal_server_error":
            self._log_structured(status=500, error=str(exc))
            client_msg = f"Internal server error [{self.request_id}]"
        else:
            client_msg = str(exc)
        code, err_payload = build_anthropic_error_response(status_code, client_msg)
        headers: dict[str, str] = {}
        if status_code == 429:
            retry_after = getattr(exc, "retry_after", None) or 5
            headers["Retry-After"] = str(retry_after)
        self._send_json(code, err_payload, headers=headers)

    def _prebuffer_stream(self, stream_gen: Iterator[str]) -> list[str]:
        """Reads lines from stream_gen until finding the first non-empty, non-comment line.

        Parses via parse_cloudcode_sse_event(line).
        If parsed is not None: calls check_sse_error(parsed) and returns buffered_lines.
        If EOF without finding valid event: raises InvalidRequestError("Stream ended without data").
        """
        buffered_lines: list[str] = []
        found_valid_event = False
        for line in stream_gen:
            buffered_lines.append(line)
            stripped = line.decode("utf-8").strip() if isinstance(line, (bytes, bytearray)) else line.strip()
            if not stripped or stripped.startswith(":"):
                continue
            parsed = parse_cloudcode_sse_event(line)
            if parsed is not None:
                check_sse_error(parsed)
                found_valid_event = True
                break
        if not found_valid_event:
            raise InvalidRequestError("Stream ended without data")
        return buffered_lines

    def _execute_upstream_call(
        self,
        model: str,
        contents: list[dict[str, Any]],
        system_instruction: dict[str, Any] | None = None,
        extra_kwargs: dict[str, Any] | None = None,
    ) -> tuple[Any, list[str]]:
        kwargs = extra_kwargs if extra_kwargs is not None else {}
        max_retries = getattr(self, "max_retries", 3)
        initial_delay = getattr(self, "initial_retry_delay", 0.5)

        for attempt in range(max_retries + 1):
            stream_gen = None
            try:
                stream_gen = self.client.stream_generate_content(
                    self.project, model, contents, system_instruction, **kwargs
                )
                buffered_lines = self._prebuffer_stream(stream_gen)
                return stream_gen, buffered_lines
            except (RateLimitError, CapacityExhaustedError):
                if stream_gen is not None and hasattr(stream_gen, "close"):
                    stream_gen.close()
                if attempt < max_retries:
                    delay = min(4.0, initial_delay * (2 ** attempt)) + random.uniform(0.01, 0.05)
                    time.sleep(delay)
                    continue
                raise
            except Exception:
                if stream_gen is not None and hasattr(stream_gen, "close"):
                    stream_gen.close()
                raise
        raise BridgeError("Upstream call failed without response")

    def _dispatch_stream(
        self,
        model: str,
        contents: list[dict[str, Any]],
        system_instruction: dict[str, Any] | None,
        extra_kwargs: dict[str, Any],
        stream_builder: Any,
        error_sender: Any,
        stream_error_formatter: Any = None,
    ) -> None:
        self._ensure_request_id()
        sem = getattr(self, "concurrency_semaphore", None)
        if sem is None and hasattr(self, "server"):
            sem = getattr(self.server, "concurrency_semaphore", None)
        acquired = True
        if sem is not None:
            acquired = sem.acquire(blocking=True, timeout=getattr(self, "concurrency_timeout", 5.0))
            if not acquired:
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.send_header("Retry-After", "1")
                self.send_header("X-Request-ID", self.request_id)
                self.end_headers()
                err = {
                    "error": {
                        "message": "Server concurrency limit reached, please retry later",
                        "type": "concurrency_limit_error",
                        "code": 429,
                    }
                }
                self.wfile.write(json.dumps(err).encode("utf-8"))
                return

        stream_gen = None
        try:
            try:
                stream_gen, buffered_lines = self._execute_upstream_call(
                    model=model,
                    contents=contents,
                    system_instruction=system_instruction,
                    extra_kwargs=extra_kwargs,
                )
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as exc:
                error_sender(exc)
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("X-Request-ID", self.request_id)
            self.end_headers()

            combined_gen = itertools.chain(buffered_lines, stream_gen)
            try:
                for chunk_str in stream_builder(combined_gen):
                    self.wfile.write(chunk_str.encode("utf-8") if isinstance(chunk_str, str) else chunk_str)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                sys.stderr.write(f"Error during stream: {exc}\n")
                sys.stderr.flush()
                if stream_error_formatter is not None:
                    try:
                        err_payload = stream_error_formatter(exc)
                        if err_payload:
                            self.wfile.write(
                                err_payload.encode("utf-8") if isinstance(err_payload, str) else err_payload
                            )
                            self.wfile.flush()
                    except Exception:
                        pass
        finally:
            if stream_gen is not None and hasattr(stream_gen, "close"):
                stream_gen.close()
            self.close_connection = True
            if sem is not None and acquired:
                sem.release()

    def _dispatch_non_streaming(
        self,
        model: str,
        contents: list[dict[str, Any]],
        system_instruction: dict[str, Any] | None,
        extra_kwargs: dict[str, Any],
        response_builder: Any,
        error_sender: Any = None,
    ) -> None:
        if error_sender is None:
            error_sender = self._send_error

        self._ensure_request_id()
        sem = getattr(self, "concurrency_semaphore", None)
        if sem is None and hasattr(self, "server"):
            sem = getattr(self.server, "concurrency_semaphore", None)
        acquired = True
        if sem is not None:
            acquired = sem.acquire(blocking=True, timeout=getattr(self, "concurrency_timeout", 5.0))
            if not acquired:
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.send_header("Retry-After", "1")
                self.send_header("X-Request-ID", self.request_id)
                self.end_headers()
                err = {
                    "error": {
                        "message": "Server concurrency limit reached, please retry later",
                        "type": "concurrency_limit_error",
                        "code": 429,
                    }
                }
                self.wfile.write(json.dumps(err).encode("utf-8"))
                return

        stream_gen = None
        try:
            try:
                stream_gen, buffered_lines = self._execute_upstream_call(
                    model=model,
                    contents=contents,
                    system_instruction=system_instruction,
                    extra_kwargs=extra_kwargs,
                )
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as exc:
                error_sender(exc)
                return

            try:
                text_parts: list[str] = []
                thought_parts: list[str] = []
                collected_tool_calls: list[dict[str, Any]] = []
                last_usage: dict[str, int] | None = None
                last_finish_reason: str = "stop"
                latest_thought_sig: str | None = None
                event_count = 0
                has_finish_reason = False

                combined_gen = itertools.chain(buffered_lines, stream_gen)
                for line in combined_gen:
                    parsed = parse_cloudcode_sse_event(line)
                    if parsed is None:
                        continue
                    event = parse_stream_event(parsed, check_error=True)
                    event_count += 1
                    sig = event.thought_signature or _extract_event_thought_signature(parsed)
                    if sig:
                        latest_thought_sig = sig
                    if event.usage:
                        last_usage = event.usage.to_dict()
                    if event.finish_reason:
                        has_finish_reason = True
                        last_finish_reason = event.finish_reason
                    if event.delta_thought:
                        thought_parts.append(event.delta_thought)
                    if event.delta_text:
                        text_parts.append(event.delta_text)
                    if event.tool_calls:
                        collected_tool_calls.extend(tc.to_dict() for tc in event.tool_calls)

                if (
                    event_count == 0
                    and not text_parts
                    and not thought_parts
                    and not collected_tool_calls
                    and not has_finish_reason
                ):
                    raise BridgeError("Stream ended without data")

                collected_data = CollectedStreamData(
                    text="".join(text_parts),
                    tool_calls=collected_tool_calls,
                    usage=last_usage,
                    finish_reason=last_finish_reason,
                    thoughts="".join(thought_parts),
                    thought_signature=latest_thought_sig,
                )

                resp_obj = response_builder(collected_data)
                try:
                    self._send_json(200, resp_obj)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            finally:
                if stream_gen is not None and hasattr(stream_gen, "close"):
                    stream_gen.close()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            error_sender(exc)
        finally:
            if sem is not None and acquired:
                sem.release()

    def _handle_anthropic_messages(self, payload: dict[str, Any]) -> None:
        try:
            stream = bool(payload.get("stream", False))
            model, contents, system_instruction, generation_config, tools, tool_config = (
                AnthropicProtocolAdapter.transform_request(payload, self.project)
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
            def anthropic_stream_error(exc: Exception) -> str:
                err_payload = json.dumps({"type": "error", "error": {"type": "api_error", "message": str(exc)}})
                return f"event: error\ndata: {err_payload}\n\n"

            self._dispatch_stream(
                model=model,
                contents=contents,
                system_instruction=system_instruction,
                extra_kwargs=extra_kwargs,
                stream_builder=lambda gen: AnthropicProtocolAdapter.build_stream(gen, model),
                error_sender=self._send_anthropic_error,
                stream_error_formatter=anthropic_stream_error,
            )
        else:
            def anthropic_response_builder(collected: CollectedStreamData) -> dict[str, Any]:
                stop_reason = "end_turn"
                if collected.finish_reason:
                    if collected.finish_reason in ("length", "max_tokens"):
                        stop_reason = "max_tokens"
                    elif collected.finish_reason in ("stop_sequence", "tool_use"):
                        stop_reason = collected.finish_reason
                    else:
                        stop_reason = "end_turn"
                if collected.tool_calls:
                    stop_reason = "tool_use"

                msg_id = f"msg_{uuid.uuid4().hex[:16]}"
                return AnthropicProtocolAdapter.build_response(
                    message_id=msg_id,
                    model=model,
                    text=collected.text,
                    usage=collected.usage,
                    stop_reason=stop_reason,
                    tool_calls=collected.tool_calls if collected.tool_calls else None,
                    thought=collected.thoughts if collected.thoughts else None,
                    thought_signature=collected.thought_signature,
                )

            self._dispatch_non_streaming(
                model=model,
                contents=contents,
                system_instruction=system_instruction,
                extra_kwargs=extra_kwargs,
                response_builder=anthropic_response_builder,
                error_sender=self._send_anthropic_error,
            )

    def _handle_responses(self, payload: dict[str, Any]) -> None:
        try:
            stream = bool(payload.get("stream", False))
            model, contents, system_instruction, generation_config, tools = (
                ResponsesProtocolAdapter.transform_request(payload, self.project)
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
            response_id = f"resp_{uuid.uuid4().hex[:16]}"

            def responses_stream_error(exc: Exception) -> str:
                err_payload = json.dumps({
                    "type": "response.failed",
                    "response": {
                        "id": response_id,
                        "status": "failed",
                        "error": {"message": str(exc)},
                    },
                })
                return f"event: response.failed\ndata: {err_payload}\n\n"

            self._dispatch_stream(
                model=model,
                contents=contents,
                system_instruction=system_instruction,
                extra_kwargs=extra_kwargs,
                stream_builder=lambda gen: ResponsesProtocolAdapter.build_stream(gen, model, response_id=response_id),
                error_sender=self._send_error,
                stream_error_formatter=responses_stream_error,
            )
        else:
            def responses_response_builder(collected: CollectedStreamData) -> dict[str, Any]:
                resp_id = f"resp_{uuid.uuid4().hex[:16]}"
                return ResponsesProtocolAdapter.build_response(
                    response_id=resp_id,
                    model=model,
                    text=collected.text,
                    usage=collected.usage,
                    tool_calls=collected.tool_calls if collected.tool_calls else None,
                )

            self._dispatch_non_streaming(
                model=model,
                contents=contents,
                system_instruction=system_instruction,
                extra_kwargs=extra_kwargs,
                response_builder=responses_response_builder,
            )

    def _handle_chat_completion(self, payload: dict[str, Any]) -> None:
        try:
            stream = bool(payload.get("stream", False))
            model, contents, system_instruction, generation_config, tools = (
                OpenAIProtocolAdapter.transform_request(payload, self.project)
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
            def chat_stream_error(exc: Exception) -> str:
                err_code, err_type = self._get_error_details(exc)
                err_payload = json.dumps({"error": {"message": str(exc), "type": err_type, "code": err_code}})
                return f"data: {err_payload}\n\n"

            self._dispatch_stream(
                model=model,
                contents=contents,
                system_instruction=system_instruction,
                extra_kwargs=extra_kwargs,
                stream_builder=lambda gen: OpenAIProtocolAdapter.build_stream(gen, model, completion_id=completion_id),
                error_sender=self._send_error,
                stream_error_formatter=chat_stream_error,
            )
        else:
            def chat_response_builder(collected: CollectedStreamData) -> dict[str, Any]:
                formatted_tool_calls = None
                finish_reason = collected.finish_reason
                if collected.tool_calls:
                    finish_reason = "tool_calls"
                    formatted_tool_calls = []
                    for fc in collected.tool_calls:
                        tc_id = fc.get("id") or f"call_{uuid.uuid4().hex[:12]}"
                        if tc_id.startswith("toolu_"):
                            tc_id = f"call_{tc_id[6:]}"
                        args = fc.get("args", {})
                        args_str = json.dumps(args) if isinstance(args, (dict, list)) else str(args or "{}")
                        thought_sig = fc.get("thought_signature") or fc.get("thoughtSignature")
                        if thought_sig:
                            cache_thought_signature(call_id=tc_id, signature=thought_sig, name=fc.get("name"), args=args)
                        if fc.get("name") and tc_id:
                            cache_tool_name(tc_id, str(fc["name"]))
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

                return OpenAIProtocolAdapter.build_response(
                    completion_id,
                    model,
                    collected.text,
                    usage=collected.usage,
                    finish_reason=finish_reason,
                    tool_calls=formatted_tool_calls,
                )

            self._dispatch_non_streaming(
                model=model,
                contents=contents,
                system_instruction=system_instruction,
                extra_kwargs=extra_kwargs,
                response_builder=chat_response_builder,
            )



def create_server(
    host: str = "127.0.0.1",
    port: int = 24980,
    client: Any | None = None,
    project: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    no_auth: bool = False,
    max_concurrency: int = 16,
    max_retries: int = 3,
    initial_retry_delay: float = 0.5,
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

    concurrency_semaphore = threading.Semaphore(max_concurrency)

    ConfiguredHandler.client = client
    ConfiguredHandler.project = project
    ConfiguredHandler.api_key = api_key
    ConfiguredHandler.concurrency_semaphore = concurrency_semaphore
    ConfiguredHandler.max_retries = max_retries
    ConfiguredHandler.initial_retry_delay = initial_retry_delay

    server = http.server.ThreadingHTTPServer((host, port), ConfiguredHandler)
    server.daemon_threads = True
    setattr(server, "api_key", api_key)
    setattr(server, "concurrency_semaphore", concurrency_semaphore)
    setattr(server, "max_concurrency", max_concurrency)
    setattr(server, "max_retries", max_retries)
    setattr(server, "initial_retry_delay", initial_retry_delay)
    return server


def run_server(
    host: str = "127.0.0.1",
    port: int = 24980,
    project: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    no_auth: bool = False,
    max_concurrency: int = 16,
    max_retries: int = 3,
    initial_retry_delay: float = 0.5,
) -> None:
    """Starts the ThreadingHTTPServer serving OpenAI-compatible endpoints."""
    server = create_server(
        host=host,
        port=port,
        project=project,
        base_url=base_url,
        api_key=api_key,
        no_auth=no_auth,
        max_concurrency=max_concurrency,
        max_retries=max_retries,
        initial_retry_delay=initial_retry_delay,
    )
    actual_port = server.server_address[1]
    print(f"Antigravity Model Bridge listening on http://{host}:{actual_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        server.server_close()
