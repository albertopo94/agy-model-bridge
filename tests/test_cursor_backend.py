"""Unit tests for Cursor backend adapter, message conversion, and subprocess execution."""

import json
import subprocess
import time
import unittest
from unittest.mock import MagicMock, patch

from bridge.cursor_backend import (
    CursorBackend,
    extract_text_content,
    is_cursor_model,
    messages_to_prompt,
    resolve_cursor_model,
)
from bridge.errors import BridgeError, ModelNotFoundError, UpstreamTimeoutError


class TestCursorBackend(unittest.TestCase):
    """Test suite for Cursor backend message formatting and execution."""

    def test_extract_text_content_string(self) -> None:
        self.assertEqual(extract_text_content("hello world"), "hello world")

    def test_extract_text_content_list(self) -> None:
        parts = [
            {"type": "text", "text": "hello "},
            {"type": "image_url", "image_url": {"url": "http://example.com/img.png"}},
            {"type": "text", "text": "world"},
        ]
        self.assertEqual(extract_text_content(parts), "hello world")

    def test_extract_text_content_empty_or_invalid(self) -> None:
        self.assertEqual(extract_text_content(None), "")
        self.assertEqual(extract_text_content(123), "")
        self.assertEqual(extract_text_content([]), "")

    def test_messages_to_prompt_single_user(self) -> None:
        messages = [{"role": "user", "content": "What is 2+2?"}]
        prompt = messages_to_prompt(messages)
        self.assertEqual(prompt, "What is 2+2?")

    def test_messages_to_prompt_multi_turn(self) -> None:
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi there! How can I help?"},
            {"role": "user", "content": "Write Python code."},
        ]
        prompt = messages_to_prompt(messages)
        expected = (
            "[System]\nYou are a helpful assistant.\n\n"
            "[User]\nHello!\n\n"
            "[Assistant]\nHi there! How can I help?\n\n"
            "[User]\nWrite Python code."
        )
        self.assertEqual(prompt, expected)

    def test_resolve_cursor_model(self) -> None:
        self.assertEqual(resolve_cursor_model("cursor/gpt-5.3-codex"), "gpt-5.3-codex")
        self.assertEqual(resolve_cursor_model("cursor-gpt-5.3-codex"), "gpt-5.3-codex")
        self.assertEqual(resolve_cursor_model("gpt-5.3-codex"), "gpt-5.3-codex")
        self.assertEqual(resolve_cursor_model("cursor/auto"), "auto")
        self.assertEqual(resolve_cursor_model("auto"), "auto")
        self.assertEqual(resolve_cursor_model(""), "auto")

    def test_is_cursor_model(self) -> None:
        self.assertTrue(is_cursor_model("cursor/gpt-5.3-codex"))
        self.assertTrue(is_cursor_model("cursor-opus-5-5-high"))
        self.assertTrue(is_cursor_model("cursor/claude-opus-5-5-high"))
        self.assertTrue(is_cursor_model("gpt-5.3-codex"))
        self.assertTrue(is_cursor_model("composer-2.5"))
        self.assertTrue(is_cursor_model("grok-4.7-high"))
        # Models shared with AGY without cursor/ prefix route to AGY
        self.assertFalse(is_cursor_model("claude-opus-5-5-high"))
        self.assertFalse(is_cursor_model("gemini-3.8-flash-high"))
        self.assertFalse(is_cursor_model("gemini-2.5-pro"))
        self.assertFalse(is_cursor_model("unknown-custom-model"))

    @patch("subprocess.Popen")
    def test_stream_chat_accumulated_chunks(self, mock_popen: MagicMock) -> None:
        lines = [
            json.dumps({"type": "system", "model": "gpt-5.3-codex"}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello"}]}}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello, how"}]}}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello, how can I help?"}]}}),
            json.dumps({"type": "result", "result": "Hello, how can I help?"}),
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = [f"{line}\n".encode("utf-8") for line in lines]
        mock_proc.stdin = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = b""
        mock_proc.wait.return_value = 0
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        backend = CursorBackend(binary_path="/usr/local/bin/agent")
        chunks = list(backend.stream_chat("Test prompt", model="gpt-5.3-codex"))
        self.assertEqual(chunks, ["Hello", ", how", " can I help?"])
        mock_proc.stdin.write.assert_called_with(b"Test prompt")
        mock_proc.stdin.close.assert_called()

    @patch("subprocess.Popen")
    def test_generate_chat_non_streaming(self, mock_popen: MagicMock) -> None:
        lines = [
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Complete answer."}]}}),
            json.dumps({"type": "result", "result": "Complete answer."}),
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = [f"{line}\n".encode("utf-8") for line in lines]
        mock_proc.stdin = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = b""
        mock_proc.wait.return_value = 0
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        backend = CursorBackend(binary_path="/usr/local/bin/agent")
        result = backend.generate_chat("Hello")
        self.assertEqual(result, "Complete answer.")

    @patch("subprocess.Popen")
    def test_stream_chat_command_not_found(self, mock_popen: MagicMock) -> None:
        mock_popen.side_effect = FileNotFoundError("No such file or directory: 'agent'")
        backend = CursorBackend(binary_path="agent")
        with self.assertRaises(BridgeError) as ctx:
            list(backend.stream_chat("Hello"))
        self.assertIn("Cursor CLI (agent) not found", str(ctx.exception))

    @patch("subprocess.Popen")
    def test_stream_chat_nonzero_exit_code(self, mock_popen: MagicMock) -> None:
        mock_proc = MagicMock()
        mock_proc.stdout = []
        mock_proc.stdin = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = b"Error: Not logged in"
        mock_proc.wait.return_value = 1
        mock_proc.poll.return_value = 1
        mock_popen.return_value = mock_proc

        backend = CursorBackend(binary_path="agent")
        with self.assertRaises(BridgeError) as ctx:
            list(backend.stream_chat("Hello"))
        self.assertIn("Error: Not logged in", str(ctx.exception))

    @patch("subprocess.run")
    def test_list_models_discovered(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Available models\n\nauto - Auto\ngpt-5.3-codex - Codex 5.3\ncomposer-2.5 - Composer 2.5\n",
            stderr="",
        )
        backend = CursorBackend(binary_path="agent")
        models = backend.list_models(force=True)
        model_ids = [m["id"] for m in models]
        self.assertIn("cursor/gpt-5.3-codex", model_ids)
        self.assertIn("cursor/composer-2.5", model_ids)
        self.assertEqual(models[0]["owned_by"], "cursor")

    @patch("subprocess.run")
    def test_list_models_fallback_on_error(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = Exception("CLI failed")
        backend = CursorBackend(binary_path="agent")
        models = backend.list_models(force=True)
        self.assertTrue(len(models) > 0)
        self.assertTrue(any(m["id"] == "cursor/gpt-5.3-codex" for m in models))


if __name__ == "__main__":
    unittest.main()
