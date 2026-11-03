"""OpenCode Agent Client Protocol (ACP) persistent client.

Zero external dependencies: pure standard library.
Maintains a warm background `opencode acp` process communicating over stdio
using JSON-RPC 2.0. Compared to Cursor's ACP server, OpenCode's handshake has
no authenticate step and model selection happens per prompt via
`session/set_model` before `session/prompt`.

Region/availability failures surface as JSON-RPC error -32603 with
`data.errorName == "APIError"` and a message like "This model is not
available in your country"; they are mapped to ForbiddenError (upstream 403)
with the model name in the message so clients see a readable cause instead
of a bare interrupted stream.
"""

from __future__ import annotations

from bridge import __version__
from bridge.errors import AuthenticationError, BridgeError, ForbiddenError, UpstreamTimeoutError
from collections.abc import Iterator
import contextlib
import dataclasses
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any


@dataclasses.dataclass
class _PendingRequest:
    event: threading.Event = dataclasses.field(default_factory=threading.Event)
    result: Any = None
    error: Any = None


REGION_MARKERS = ("not available in your country", "regionerror")
AUTH_MARKERS = ("authentication required", "auth required")


def find_opencode_binary() -> str:
    """Discovers the absolute path to the `opencode` executable."""
    found = shutil.which("opencode")
    if found:
        return found
    for candidate in (
        Path.home() / ".opencode" / "bin" / "opencode",
        Path.home() / ".local" / "bin" / "opencode",
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return "opencode"


def extract_opencode_error_message(err: Any) -> str:
    """Extracts a human-readable message from a JSON-RPC error, JSON string, or raw text."""
    if err is None:
        return ""
    if isinstance(err, dict):
        msg = err.get("message")
        if isinstance(msg, str) and msg:
            return msg
        data = err.get("data")
        if isinstance(data, dict):
            for key in ("message", "responseBody"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    return value
        return json.dumps(err)
    if isinstance(err, str):
        return err
    return str(err)


def is_opencode_region_error(err: Any) -> bool:
    """Detects region/availability blocking from an ACP error or `opencode run` payload."""
    text = extract_opencode_error_message(err).lower()
    return any(marker in text for marker in REGION_MARKERS)


def is_opencode_auth_error(err: Any) -> bool:
    """Detects provider authentication requirements from an ACP error or raw payload."""
    text = extract_opencode_error_message(err).lower()
    return any(marker in text for marker in AUTH_MARKERS)


class OpencodeAcpClient:
    """Manages a persistent JSON-RPC connection to the OpenCode ACP server (`opencode acp`)."""

    def __init__(
        self,
        binary_path: str | None = None,
        cwd: str | None = None,
    ) -> None:
        self.binary_path = binary_path or find_opencode_binary()
        self.cwd = cwd or tempfile.gettempdir()
        self._handshake_timeout = 15.0
        self._proc: subprocess.Popen[bytes] | None = None
        self._reader_thread: threading.Thread | None = None
        self._next_id: int = 1
        self._id_lock = threading.Lock()
        self._pending: dict[int, _PendingRequest] = {}
        self._pending_lock = threading.Lock()
        self._prompt_queue: queue.Queue[str | None] = queue.Queue()
        self._session_id: str | None = None
        self._client_lock = threading.Lock()
        self._closing = False

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def is_alive(self) -> bool:
        """Returns True if the background ACP process is alive and a session is ready."""
        return (
            self._proc is not None
            and self._proc.poll() is None
            and self._session_id is not None
        )

    def start(self) -> None:
        """Launches the ACP process and executes the initialization handshake."""
        with self._client_lock:
            if self.is_alive():
                return
            self._closing = False
            self._cleanup_process()

            cmd = [self.binary_path, "acp"]
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=self.cwd,
                )
            except FileNotFoundError as exc:
                raise BridgeError(
                    f"OpenCode CLI (opencode) not found at '{self.binary_path}'. "
                    "Install via: curl -fsSL https://opencode.ai/install -fsS | bash"
                ) from exc
            except OSError as exc:
                raise BridgeError(f"Failed to start OpenCode ACP server ({self.binary_path}): {exc}") from exc

            self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._reader_thread.start()

            # Handshake step 1: initialize (OpenCode has no authenticate step)
            init_res = self._send_request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                    },
                    "clientInfo": {"name": "agy-model-bridge", "version": __version__},
                },
                timeout=self._handshake_timeout,
            )
            if not isinstance(init_res, dict):
                raise BridgeError(f"OpenCode ACP initialize handshake failed: {init_res}")

            # Handshake step 2: create the warm session
            sess_res = self._send_request(
                "session/new",
                {"cwd": self.cwd, "mcpServers": []},
                timeout=self._handshake_timeout,
            )
            if isinstance(sess_res, dict) and "sessionId" in sess_res:
                self._session_id = str(sess_res["sessionId"])
            else:
                raise BridgeError(f"OpenCode ACP session creation failed: {sess_res}")

    def stream_prompt(
        self,
        prompt_text: str,
        model: str,
        timeout: float = 120.0,
    ) -> Iterator[str]:
        """Selects the model on the warm session, sends the prompt, and streams text chunks."""
        # start() acquires _client_lock itself; never hold it here or the
        # non-reentrant lock would deadlock when the session is cold.
        if not self.is_alive():
            self.start()

        # OpenCode selects the model per prompt on the shared warm session.
        self._send_request(
            "session/set_model",
            {"sessionId": self._session_id, "modelId": model},
            timeout=self._handshake_timeout,
        )

        # Clear any leftover items in the prompt queue
        while not self._prompt_queue.empty():
            try:
                self._prompt_queue.get_nowait()
            except queue.Empty:
                break

        with self._id_lock:
            prompt_id = self._next_id
            self._next_id += 1

        pending = _PendingRequest()
        with self._pending_lock:
            self._pending[prompt_id] = pending

        req_payload = {
            "jsonrpc": "2.0",
            "id": prompt_id,
            "method": "session/prompt",
            "params": {
                "sessionId": self._session_id,
                "prompt": [{"type": "text", "text": prompt_text}],
            },
        }
        self._write_json(req_payload)
        start_time = time.time()

        while True:
            if (time.time() - start_time) > timeout:
                self.close()
                raise UpstreamTimeoutError(f"OpenCode ACP prompt streaming timed out after {timeout}s")

            try:
                chunk = self._prompt_queue.get(timeout=min(0.5, max(0.1, timeout - (time.time() - start_time))))
                if chunk is None:
                    break
                yield chunk
            except queue.Empty:
                if pending.event.is_set():
                    while not self._prompt_queue.empty():
                        c = self._prompt_queue.get_nowait()
                        if c is not None:
                            yield c
                    break

        if pending.error is not None:
            raise self._map_prompt_error(model, pending.error)

    def close(self) -> None:
        """Closes the ACP connection and terminates the background process."""
        self._closing = True
        self._cleanup_process()

    def _map_prompt_error(self, model: str, err: Any) -> BridgeError:
        """Maps ACP prompt errors to the bridge exception hierarchy with readable messages."""
        message = extract_opencode_error_message(err)
        if is_opencode_region_error(err):
            return ForbiddenError(
                f"OpenCode model '{model}' is not available in your region "
                f"(upstream: {message or 'region blocked'})"
            )
        if is_opencode_auth_error(err):
            return AuthenticationError(
                f"OpenCode model '{model}' requires provider authentication "
                f"(upstream: {message or 'authentication required'})"
            )
        return BridgeError(f"OpenCode ACP error for model '{model}': {message or 'unknown error'}")

    def _cleanup_process(self) -> None:
        self._session_id = None
        if self._proc:
            try:
                self._proc.kill()
            except OSError:
                pass
            self._proc = None

        with self._pending_lock:
            for p in self._pending.values():
                p.error = "Client closed"
                p.event.set()
            self._pending.clear()

        self._prompt_queue.put(None)

    def _send_request(self, method: str, params: dict[str, Any], timeout: float = 15.0) -> Any:
        with self._id_lock:
            req_id = self._next_id
            self._next_id += 1

        pending = _PendingRequest()
        with self._pending_lock:
            self._pending[req_id] = pending

        self._write_json({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})

        if not pending.event.wait(timeout=timeout):
            with self._pending_lock:
                self._pending.pop(req_id, None)
            raise UpstreamTimeoutError(f"OpenCode ACP request '{method}' timed out after {timeout}s")

        if pending.error is not None:
            raise BridgeError(f"OpenCode ACP request '{method}' failed: {extract_opencode_error_message(pending.error)}")
        return pending.result

    def _write_json(self, data: dict[str, Any]) -> None:
        if not self._proc or not self._proc.stdin:
            raise BridgeError("OpenCode ACP process stdin unavailable")
        line = json.dumps(data) + "\n"
        try:
            self._proc.stdin.write(line.encode("utf-8"))
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise BridgeError(f"Failed to write to OpenCode ACP stdin: {exc}") from exc

    def _handle_incoming(self, msg: dict[str, Any]) -> None:
        """Processes an incoming server notification or request (also used directly in tests)."""
        method = msg.get("method")
        if method == "session/update":
            update = msg.get("params", {}).get("update", {})
            if update.get("sessionUpdate") == "agent_message_chunk":
                text = update.get("content", {}).get("text", "")
                if text:
                    self._prompt_queue.put(text)
        elif method == "session/request_permission":
            # Auto-approve tool permissions (equivalent to running with --auto)
            msg_id = msg.get("id")
            if msg_id is not None:
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"outcome": {"outcome": "selected", "optionId": "allow-once"}},
                }
                with contextlib.suppress(Exception):
                    self._write_json(resp)

    def _read_loop(self) -> None:
        """Background thread that reads JSON-RPC messages from the ACP stdout."""
        proc = self._proc
        if not proc or not proc.stdout:
            return

        for raw_line in proc.stdout:
            if self._closing:
                break
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            if not isinstance(msg, dict):
                continue

            if msg.get("method") is not None:
                self._handle_incoming(msg)
                continue

            msg_id = msg.get("id")
            if msg_id is not None:
                with self._pending_lock:
                    pending = self._pending.pop(msg_id, None)
                if pending:
                    if "result" in msg:
                        pending.result = msg["result"]
                    elif "error" in msg:
                        pending.error = msg["error"]
                    pending.event.set()
                    self._prompt_queue.put(None)
