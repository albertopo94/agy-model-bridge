"""Unit tests for Cursor ACP (Agent Client Protocol) client."""

import json
import queue
import subprocess
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from bridge.cursor_acp import CursorAcpClient
from bridge.errors import BridgeError, UpstreamTimeoutError


class MockPipe:
    """Simulates stdio pipe with thread-safe line streaming."""

    def __init__(self) -> None:
        self.q: queue.Queue[bytes | None] = queue.Queue()

    def write_line(self, line_str: str) -> None:
        self.q.put(f"{line_str}\n".encode("utf-8"))

    def close(self) -> None:
        self.q.put(None)

    def __iter__(self):
        while True:
            item = self.q.get()
            if item is None:
                break
            yield item


class TestCursorAcpClient(unittest.TestCase):
    """Test suite for persistent CursorAcpClient connection, JSON-RPC, and prompt streaming."""

    def test_init_state(self) -> None:
        client = CursorAcpClient(binary_path="/usr/local/bin/agent")
        self.assertFalse(client.is_alive())
        self.assertIsNone(client.session_id)

    @patch("subprocess.Popen")
    def test_start_handshake_success(self, mock_popen: MagicMock) -> None:
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stderr = MagicMock()
        mock_stdout = MockPipe()
        mock_proc.stdout = mock_stdout

        def on_stdin_write(data: bytes) -> int:
            msg = json.loads(data.decode("utf-8").strip())
            req_id = msg.get("id")
            method = msg.get("method")
            if method == "initialize":
                mock_stdout.write_line(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": 1}}))
            elif method == "authenticate":
                mock_stdout.write_line(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": {}}))
            elif method == "session/new":
                mock_stdout.write_line(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": {"sessionId": "test-session-123"}}))
            return len(data)

        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write.side_effect = on_stdin_write
        mock_popen.return_value = mock_proc

        client = CursorAcpClient(binary_path="/usr/local/bin/agent")
        client.start()
        self.assertTrue(client.is_alive())
        self.assertEqual(client.session_id, "test-session-123")
        client.close()
        mock_stdout.close()

    @patch("subprocess.Popen")
    def test_stream_prompt_receives_chunks(self, mock_popen: MagicMock) -> None:
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stderr = MagicMock()
        mock_stdout = MockPipe()
        mock_proc.stdout = mock_stdout

        def on_stdin_write(data: bytes) -> int:
            msg = json.loads(data.decode("utf-8").strip())
            req_id = msg.get("id")
            method = msg.get("method")
            if method == "initialize":
                mock_stdout.write_line(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": 1}}))
            elif method == "authenticate":
                mock_stdout.write_line(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": {}}))
            elif method == "session/new":
                mock_stdout.write_line(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": {"sessionId": "session-abc"}}))
            elif method == "session/prompt":
                # Emit chunks, permission request, and final result
                mock_stdout.write_line(json.dumps({
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": "session-abc",
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "Hello "},
                        },
                    },
                }))
                mock_stdout.write_line(json.dumps({
                    "jsonrpc": "2.0",
                    "id": 99,
                    "method": "session/request_permission",
                    "params": {"sessionId": "session-abc"},
                }))
                mock_stdout.write_line(json.dumps({
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": "session-abc",
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "world!"},
                        },
                    },
                }))
                mock_stdout.write_line(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": {"stopReason": "end_turn"}}))
            return len(data)

        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write.side_effect = on_stdin_write
        mock_popen.return_value = mock_proc

        client = CursorAcpClient(binary_path="/usr/local/bin/agent")
        client.start()

        chunks = list(client.stream_prompt("Say hello world"))
        self.assertEqual(chunks, ["Hello ", "world!"])

        # Verify auto-response for permission was written to stdin
        permission_response = {"jsonrpc": "2.0", "id": 99, "result": {"outcome": {"outcome": "selected", "optionId": "allow-once"}}}
        mock_proc.stdin.write.assert_any_call(json.dumps(permission_response).encode("utf-8") + b"\n")
        client.close()
        mock_stdout.close()

    @patch("subprocess.Popen")
    def test_start_binary_not_found(self, mock_popen: MagicMock) -> None:
        mock_popen.side_effect = FileNotFoundError("No such file: agent")
        client = CursorAcpClient(binary_path="nonexistent-agent")
        with self.assertRaises(BridgeError) as ctx:
            client.start()
        self.assertIn("Cursor CLI (agent) not found", str(ctx.exception))

    @patch("subprocess.Popen")
    def test_handshake_timeout_raises_upstream_timeout_error(self, mock_popen: MagicMock) -> None:
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stderr = MagicMock()
        mock_stdout = MockPipe()
        mock_proc.stdout = mock_stdout
        # stdin write does not respond -> causes timeout
        mock_proc.stdin = MagicMock()
        mock_popen.return_value = mock_proc

        client = CursorAcpClient(binary_path="/usr/local/bin/agent")
        client._proc = mock_proc
        with self.assertRaises(UpstreamTimeoutError):
            client._send_request("initialize", {}, timeout=0.05)
        mock_stdout.close()

    @patch("subprocess.Popen")
    def test_close_terminates_process_and_wakes_waiters(self, mock_popen: MagicMock) -> None:
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stderr = MagicMock()
        mock_stdout = MockPipe()
        mock_proc.stdout = mock_stdout
        mock_proc.stdin = MagicMock()
        mock_popen.return_value = mock_proc

        client = CursorAcpClient(binary_path="/usr/local/bin/agent")
        client._proc = mock_proc
        client._session_id = "test-sess"
        self.assertTrue(client.is_alive())

        client.close()
        self.assertFalse(client.is_alive())
        mock_proc.kill.assert_called_once()
        mock_stdout.close()


if __name__ == "__main__":
    unittest.main()
