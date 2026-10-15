"""Cursor Agent Client Protocol (ACP) persistent client.

Zero external dependencies: pure standard library.
Maintains a warm background `agent --trust --yolo acp` process communicating
over stdio using JSON-RPC 2.0. This eliminates the 20-40s cold start overhead
of `agent -p` and achieves instant 2-5s prompt streaming.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from typing import Any

from bridge.cursor_backend import find_agent_binary
from bridge.errors import BridgeError, UpstreamTimeoutError


@dataclass
class _PendingRequest:
    event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: Any = None


class CursorAcpClient:
    """Manages a persistent JSON-RPC connection to Cursor's ACP server (`agent acp`)."""

    def __init__(
        self,
        binary_path: str | None = None,
        cwd: str | None = None,
    ) -> None:
        self.binary_path = binary_path or find_agent_binary()
        self.cwd = cwd or "/tmp"
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
        """Returns True if the background ACP process is alive and healthy."""
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

            cmd = [self.binary_path, "--trust", "--yolo", "acp"]
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
                    f"Cursor CLI (agent) not found at '{self.binary_path}'. "
                    "Install via: curl https://cursor.com/install -fsS | bash"
                ) from exc
            except OSError as exc:
                raise BridgeError(f"Failed to start Cursor ACP server ({self.binary_path}): {exc}") from exc

            self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._reader_thread.start()

            # Handshake step 1: initialize
            init_res = self._send_request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                        "terminal": False,
                    },
                    "clientInfo": {"name": "agy-model-bridge", "version": "0.27.1"},
                },
                timeout=15.0,
            )
            if not isinstance(init_res, dict):
                raise BridgeError(f"Cursor ACP initialize handshake failed: {init_res}")

            # Handshake step 2: authenticate
            self._send_request("authenticate", {"methodId": "cursor_login"}, timeout=15.0)

            # Handshake step 3: create default warm session
            sess_res = self._send_request(
                "session/new",
                {"cwd": self.cwd, "mcpServers": []},
                timeout=20.0,
            )
            if isinstance(sess_res, dict) and "sessionId" in sess_res:
                self._session_id = str(sess_res["sessionId"])
            else:
                raise BridgeError(f"Cursor ACP session creation failed: {sess_res}")

    def stream_prompt(
        self,
        prompt_text: str,
        timeout: float = 120.0,
    ) -> Iterator[str]:
        """Sends prompt_text over the live ACP session and streams content chunks in real time."""
        with self._client_lock:
            if not self.is_alive():
                self.start()

        # Clear any leftover items in prompt queue
        while not self._prompt_queue.empty():
            try:
                self._prompt_queue.get_nowait()
            except queue.Empty:
                break

        # Allocate prompt request ID
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

        # Stream chunks as they arrive in _prompt_queue
        while True:
            remaining_time = max(0.1, timeout - (time.time() - start_time))
            if (time.time() - start_time) > timeout:
                self.close()
                raise UpstreamTimeoutError(f"Cursor ACP prompt streaming timed out after {timeout}s")

            try:
                chunk = self._prompt_queue.get(timeout=min(remaining_time, 0.5))
                if chunk is None:
                    # Stream complete signal
                    break
                yield chunk
            except queue.Empty:
                if pending.event.is_set():
                    # Request finished, drain any remaining chunks
                    while not self._prompt_queue.empty():
                        c = self._prompt_queue.get_nowait()
                        if c is not None:
                            yield c
                    break

        if pending.error:
            raise BridgeError(f"Cursor ACP error: {pending.error}")

    def close(self) -> None:
        """Closes the ACP connection and terminates the background process."""
        self._closing = True
        self._cleanup_process()

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

        # Wake up any waiting stream
        self._prompt_queue.put(None)

    def _send_request(self, method: str, params: dict[str, Any], timeout: float = 15.0) -> Any:
        with self._id_lock:
            req_id = self._next_id
            self._next_id += 1

        pending = _PendingRequest()
        with self._pending_lock:
            self._pending[req_id] = pending

        req = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        self._write_json(req)

        if not pending.event.wait(timeout=timeout):
            with self._pending_lock:
                self._pending.pop(req_id, None)
            raise UpstreamTimeoutError(f"Cursor ACP request '{method}' timed out after {timeout}s")

        if pending.error is not None:
            raise BridgeError(f"Cursor ACP request '{method}' failed: {pending.error}")
        return pending.result

    def _write_json(self, data: dict[str, Any]) -> None:
        if not self._proc or not self._proc.stdin:
            raise BridgeError("Cursor ACP process stdin unavailable")
        line = json.dumps(data) + "\n"
        try:
            self._proc.stdin.write(line.encode("utf-8"))
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise BridgeError(f"Failed to write to Cursor ACP stdin: {exc}") from exc

    def _read_loop(self) -> None:
        """Background thread that reads JSON-RPC messages from ACP stdout."""
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

            msg_id = msg.get("id")
            method = msg.get("method")

            # 1. Server notifications and incoming requests
            if method:
                if method == "session/update":
                    update = msg.get("params", {}).get("update", {})
                    if update.get("sessionUpdate") == "agent_message_chunk":
                        text = update.get("content", {}).get("text", "")
                        if text:
                            self._prompt_queue.put(text)
                elif method == "session/request_permission":
                    # Automatically approve permissions (equivalent to --yolo)
                    if msg_id is not None:
                        resp = {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": {"outcome": {"outcome": "selected", "optionId": "allow-once"}},
                        }
                        try:
                            self._write_json(resp)
                        except Exception:
                            pass
                continue

            # 2. Response to a pending client request
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
