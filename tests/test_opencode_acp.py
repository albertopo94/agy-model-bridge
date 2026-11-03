"""Unit tests for OpenCode ACP (Agent Client Protocol) client.

OpenCode's `opencode acp` server differs from Cursor's `agent acp`:
- Handshake is `initialize` -> `session/new` (no authenticate step).
- Model selection is per-prompt via `session/set_model` before `session/prompt`.
- Region/availability failures surface as JSON-RPC error -32603 with
  data.errorName == "APIError" and a human message (S5, opencode-upstream).
"""

import json
import queue
import unittest
from unittest.mock import MagicMock, patch

from bridge.errors import AuthenticationError, BridgeError, ForbiddenError
from bridge.opencode_acp import (
    OpencodeAcpClient,
    extract_opencode_error_message,
    is_opencode_region_error,
)


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


def _make_proc(session_id: str = "ses_test123"):
    """Builds a mocked Popen whose stdin writes answer ACP requests in order."""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.stderr = MagicMock()
    mock_stdout = MockPipe()
    mock_proc.stdout = mock_stdout
    state = {"model": None}

    def on_stdin_write(data: bytes) -> int:
        msg = json.loads(data.decode("utf-8").strip())
        req_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}
        if method == "initialize":
            mock_stdout.write_line(json.dumps({
                "jsonrpc": "2.0", "id": req_id,
                "result": {"protocolVersion": 1, "agentInfo": {"name": "OpenCode", "version": "1.19.5"}},
            }))
        elif method == "session/new":
            mock_stdout.write_line(json.dumps({
                "jsonrpc": "2.0", "id": req_id,
                "result": {"sessionId": session_id},
            }))
        elif method == "session/set_model":
            state["model"] = params.get("modelId")
            mock_stdout.write_line(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": {}}))
        elif method == "session/prompt":
            if state["model"] == "opencode/pulse-alpha-free":
                mock_stdout.write_line(json.dumps({
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {
                        "code": -32603,
                        "message": "Internal error: This model is not available in your country",
                        "data": {"service": "session", "errorName": "APIError"},
                    },
                }))
            elif state["model"] == "opencode/beam-free":
                mock_stdout.write_line(json.dumps({
                    "jsonrpc": "2.0", "method": "session/update",
                    "params": {"sessionId": session_id, "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "PONG"},
                    }},
                }))
                mock_stdout.write_line(json.dumps({
                    "jsonrpc": "2.0", "id": req_id, "result": {"stopReason": "end_turn"},
                }))
            else:
                mock_stdout.write_line(json.dumps({
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32000, "message": "Authentication required: provider authentication required",
                              "data": {"providerId": "google"}},
                }))
        return len(data)

    mock_proc.stdin = MagicMock()
    mock_proc.stdin.write.side_effect = on_stdin_write
    return mock_proc, mock_stdout


class TestOpencodeErrorHelpers(unittest.TestCase):
    """Tests for region/authentication error classification (S5)."""

    def test_region_error_detected_from_acp_error(self) -> None:
        err = {
            "code": -32603,
            "message": "Internal error: This model is not available in your country",
            "data": {"service": "session", "errorName": "APIError"},
        }
        self.assertTrue(is_opencode_region_error(err))

    def test_region_error_detected_from_run_stderr(self) -> None:
        text = '{"type":"error","data":{"message":"This model is not available in your country","statusCode":403}}'
        self.assertTrue(is_opencode_region_error(text))

    def test_auth_error_is_not_region_error(self) -> None:
        err = {"code": -32000, "message": "Authentication required: provider authentication required"}
        self.assertFalse(is_opencode_region_error(err))

    def test_generic_error_is_not_region_error(self) -> None:
        self.assertFalse(is_opencode_region_error({"code": -32603, "message": "Internal error: boom"}))
        self.assertFalse(is_opencode_region_error(None))
        self.assertFalse(is_opencode_region_error(""))

    def test_extract_message_from_dict_error(self) -> None:
        msg = extract_opencode_error_message({"message": "Internal error: This model is not available in your country"})
        self.assertIn("not available in your country", msg)

    def test_extract_message_from_json_string(self) -> None:
        msg = extract_opencode_error_message('{"error": {"data": {"message": "RegionError 403"}}}')
        self.assertIn("RegionError", msg)

    def test_extract_message_falls_back_to_raw_text(self) -> None:
        self.assertEqual(extract_opencode_error_message("plain text failure"), "plain text failure")
        self.assertEqual(extract_opencode_error_message(None), "")


class TestOpencodeAcpClient(unittest.TestCase):
    """Lifecycle, handshake, model selection, streaming and error mapping."""

    def test_init_state(self) -> None:
        client = OpencodeAcpClient(binary_path="/usr/local/bin/opencode")
        self.assertFalse(client.is_alive())
        self.assertIsNone(client.session_id)

    @patch("subprocess.Popen")
    def test_start_handshake_no_authenticate_step(self, mock_popen: MagicMock) -> None:
        mock_proc, mock_stdout = _make_proc(session_id="ses_alpha")
        mock_popen.return_value = mock_proc

        client = OpencodeAcpClient(binary_path="/usr/local/bin/opencode")
        client.start()

        self.assertTrue(client.is_alive())
        self.assertEqual(client.session_id, "ses_alpha")

        methods = []
        for call in mock_proc.stdin.write.call_args_list:
            payload = json.loads(call.args[0].decode("utf-8").strip())
            methods.append(payload.get("method"))
        self.assertIn("initialize", methods)
        self.assertIn("session/new", methods)
        self.assertNotIn("authenticate", methods)

        client.close()
        mock_stdout.close()

    @patch("subprocess.Popen")
    def test_start_uses_opencode_acp_command(self, mock_popen: MagicMock) -> None:
        mock_proc, mock_stdout = _make_proc()
        mock_popen.return_value = mock_proc
        client = OpencodeAcpClient(binary_path="/usr/bin/opencode")
        client.start()
        cmd = mock_popen.call_args.args[0]
        self.assertEqual(cmd, ["/usr/bin/opencode", "acp"])
        client.close()
        mock_stdout.close()

    @patch("subprocess.Popen")
    def test_stream_prompt_selects_model_before_prompt(self, mock_popen: MagicMock) -> None:
        mock_proc, mock_stdout = _make_proc()
        mock_popen.return_value = mock_proc
        client = OpencodeAcpClient(binary_path="/usr/bin/opencode")

        chunks = list(client.stream_prompt("Say PONG", model="opencode/beam-free"))
        self.assertEqual("".join(chunks), "PONG")

        methods = []
        set_model_ids = []
        for call in mock_proc.stdin.write.call_args_list:
            payload = json.loads(call.args[0].decode("utf-8").strip())
            methods.append(payload.get("method"))
            if payload.get("method") == "session/set_model":
                set_model_ids.append(payload["params"]["modelId"])
        self.assertEqual(set_model_ids, ["opencode/beam-free"])
        self.assertLess(methods.index("session/set_model"), methods.index("session/prompt"))
        client.close()
        mock_stdout.close()

    @patch("subprocess.Popen")
    def test_stream_prompt_region_error_raises_forbidden(self, mock_popen: MagicMock) -> None:
        # Region blocking is a 403 upstream (statusCode 403 / RegionError), so it maps
        # to ForbiddenError which the server already renders as 403 for all protocols.
        mock_proc, mock_stdout = _make_proc()
        mock_popen.return_value = mock_proc
        client = OpencodeAcpClient(binary_path="/usr/bin/opencode")

        with self.assertRaises(ForbiddenError) as ctx:
            list(client.stream_prompt("Say PONG", model="opencode/pulse-alpha-free", timeout=10.0))
        self.assertIn("not available in your country", str(ctx.exception))
        client.close()
        mock_stdout.close()

    @patch("subprocess.Popen")
    def test_stream_prompt_auth_error_raises_authentication_error(self, mock_popen: MagicMock) -> None:
        mock_proc, mock_stdout = _make_proc()
        mock_popen.return_value = mock_proc
        client = OpencodeAcpClient(binary_path="/usr/bin/opencode")

        with self.assertRaises(AuthenticationError) as ctx:
            list(client.stream_prompt("Say PONG", model="google/gemini-2.5-flash", timeout=10.0))
        self.assertIn("Authentication required", str(ctx.exception))
        client.close()
        mock_stdout.close()

    @patch("subprocess.Popen")
    def test_permission_requests_are_auto_approved(self, mock_popen: MagicMock) -> None:
        mock_proc, mock_stdout = _make_proc()
        mock_popen.return_value = mock_proc
        client = OpencodeAcpClient(binary_path="/usr/bin/opencode")
        client.start()

        # Simulate an incoming permission request from the agent.
        perm = {
            "jsonrpc": "2.0", "id": 555, "method": "session/request_permission",
            "params": {"sessionId": client.session_id, "options": [{"optionId": "allow-once"}]},
        }
        client._handle_incoming(perm)

        responses = []
        for call in mock_proc.stdin.write.call_args_list:
            payload = json.loads(call.args[0].decode("utf-8").strip())
            if payload.get("id") == 555 and "result" in payload:
                responses.append(payload)
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["result"]["outcome"]["outcome"], "selected")
        client.close()
        mock_stdout.close()

    @patch("subprocess.Popen")
    def test_start_failure_binary_missing_raises_bridge_error(self, mock_popen: MagicMock) -> None:
        mock_popen.side_effect = FileNotFoundError("opencode")
        client = OpencodeAcpClient(binary_path="/no/such/opencode")
        with self.assertRaises(BridgeError) as ctx:
            client.start()
        self.assertIn("opencode", str(ctx.exception).lower())

    @patch("subprocess.Popen")
    def test_start_handshake_timeout_raises(self, mock_popen: MagicMock) -> None:
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stderr = MagicMock()
        mock_proc.stdout = MockPipe()
        mock_proc.stdin = MagicMock()  # never answers
        mock_popen.return_value = mock_proc

        client = OpencodeAcpClient(binary_path="/usr/bin/opencode")
        client._handshake_timeout = 0.4
        from bridge.errors import UpstreamTimeoutError
        with self.assertRaises(UpstreamTimeoutError):
            client.start()
        mock_proc.stdin = MagicMock()  # keep close() quiet
        client.close()


if __name__ == "__main__":
    unittest.main()
