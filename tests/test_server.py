import io
import json
import socket
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.request

from bridge.server import create_server, OpenAIRequestHandler
from bridge.client import (
    CloudCodeClient,
    BridgeError,
    AuthenticationError,
    ForbiddenError,
    RateLimitError,
    CapacityExhaustedError,
    ModelNotFoundError,
    UpstreamTimeoutError,
)


class MockCloudCodeClient:
    def __init__(self):
        self.models = [{"name": "models/gemini-2.5-pro"}, {"id": "gemini-2.5-flash"}]
        self.should_fail_with = None
        self.custom_stream_generator = None
        self.last_generation_config = None
        self.token_provider = MagicMock()

    def fetch_available_models(self, project: str):
        if self.should_fail_with:
            raise self.should_fail_with
        return self.models

    def stream_generate_content(
        self,
        project: str,
        model: str,
        contents: list,
        system_instruction=None,
        generation_config=None,
    ):
        self.last_generation_config = generation_config
        if self.should_fail_with:
            raise self.should_fail_with
        if self.custom_stream_generator:
            yield from self.custom_stream_generator()
            return
        yield 'data: {"candidates": [{"content": {"parts": [{"text": "Hello "}]}}]}\n'
        yield 'data: {"candidates": [{"content": {"parts": [{"thought": true, "text": "thinking..."}]}}]}\n'
        yield 'data: {"candidates": [{"content": {"parts": [{"text": "world!"}]}}], "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 7, "totalTokenCount": 12}}\n'
        yield 'data: {"candidates": [{"finishReason": "STOP"}]}\n'


class TestServerEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock_client = MockCloudCodeClient()
        cls.server = create_server(
            host="127.0.0.1",
            port=0,
            client=cls.mock_client,
            project="test-project",
        )
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=2.0)

    def setUp(self):
        self.mock_client.should_fail_with = None
        self.mock_client.custom_stream_generator = None

    def _http_get(self, path: str):
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, resp.headers, json.loads(body)

    def _http_get_raw(self, path: str):
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, resp.headers, body

    def _http_post(self, path: str, payload: dict, stream: bool = False):
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if stream:
            return urllib.request.urlopen(req, timeout=5.0)
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, resp.headers, json.loads(body)

    def test_healthz_endpoint(self):
        status, headers, body = self._http_get("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"status": "ok"})
        self.assertEqual(headers.get_content_type(), "application/json")

    def test_v1_models_endpoint(self):
        status, headers, body = self._http_get("/v1/models")
        self.assertEqual(status, 200)
        self.assertEqual(body["object"], "list")
        self.assertEqual(len(body["data"]), 2)
        self.assertEqual(body["data"][0]["id"], "gemini-2.5-pro")
        self.assertEqual(body["data"][0]["owned_by"], "google")

    def test_chat_completions_non_streaming(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False,
        }
        status, headers, body = self._http_post("/v1/chat/completions", payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["object"], "chat.completion")
        self.assertEqual(body["model"], "gemini-2.5-pro")
        self.assertEqual(len(body["choices"]), 1)
        self.assertEqual(body["choices"][0]["message"]["content"], "Hello world!")
        self.assertEqual(body["choices"][0]["finish_reason"], "stop")
        self.assertEqual(body["usage"]["prompt_tokens"], 5)
        self.assertEqual(body["usage"]["completion_tokens"], 7)

    def test_chat_completions_streaming(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }
        resp = self._http_post("/v1/chat/completions", payload, stream=True)
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers.get_content_type(), "text/event-stream")

        lines = []
        for raw_line in resp:
            line_str = raw_line.decode("utf-8")
            lines.append(line_str)
            if line_str.strip() == "data: [DONE]":
                break
        resp.close()

        # Non-empty lines
        non_empty = [l.strip() for l in lines if l.strip()]
        self.assertTrue(len(non_empty) >= 2)
        # Verify chunks
        deltas = []
        for line in non_empty:
            if line == "data: [DONE]":
                break
            self.assertTrue(line.startswith("data: "))
            chunk = json.loads(line[6:])
            self.assertEqual(chunk["object"], "chat.completion.chunk")
            content = chunk["choices"][0]["delta"].get("content")
            if content:
                deltas.append(content)

        self.assertEqual("".join(deltas), "Hello world!")
        self.assertEqual(non_empty[-1], "data: [DONE]")

    def test_chat_completions_invalid_payload_returns_400(self):
        # Missing messages
        url = f"{self.base_url}/v1/chat/completions"
        req = urllib.request.Request(
            url,
            data=b'{"model": "test"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        err = ctx.exception
        self.assertEqual(err.code, 400)
        body = json.loads(err.read().decode("utf-8"))
        self.assertEqual(body["error"]["type"], "invalid_request_error")

    def test_chat_completions_malformed_json_returns_400(self):
        url = f"{self.base_url}/v1/chat/completions"
        req = urllib.request.Request(
            url,
            data=b'{invalid json}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        err = ctx.exception
        self.assertEqual(err.code, 400)
        body = json.loads(err.read().decode("utf-8"))
        self.assertEqual(body["error"]["type"], "invalid_request_error")

    def test_unknown_path_returns_404(self):
        url = f"{self.base_url}/v1/unknown_endpoint"
        req = urllib.request.Request(url, method="GET")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        err = ctx.exception
        self.assertEqual(err.code, 404)
        body = json.loads(err.read().decode("utf-8"))
        self.assertEqual(body["error"]["type"], "invalid_request_error")

    def test_upstream_rate_limit_maps_to_429(self):
        self.mock_client.should_fail_with = RateLimitError("Rate limit exceeded")
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        url = f"{self.base_url}/v1/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        err = ctx.exception
        self.assertEqual(err.code, 429)
        body = json.loads(err.read().decode("utf-8"))
        self.assertEqual(body["error"]["type"], "rate_limit_error")

    def test_upstream_auth_error_maps_to_401(self):
        self.mock_client.should_fail_with = AuthenticationError("Auth failed")
        url = f"{self.base_url}/v1/models"
        req = urllib.request.Request(url, method="GET")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        err = ctx.exception
        self.assertEqual(err.code, 401)
        body = json.loads(err.read().decode("utf-8"))
        self.assertEqual(body["error"]["type"], "authentication_error")

    def test_upstream_forbidden_maps_to_403(self):
        self.mock_client.should_fail_with = ForbiddenError("Upstream forbidden (403): Access denied")
        url = f"{self.base_url}/v1/models"
        req = urllib.request.Request(url, method="GET")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        err = ctx.exception
        self.assertEqual(err.code, 403)
        body = json.loads(err.read().decode("utf-8"))
        self.assertEqual(body["error"]["type"], "permission_denied")

    def test_upstream_auth_error_invalidates_token(self):
        self.mock_client.token_provider.reset_mock()
        self.mock_client.should_fail_with = AuthenticationError("Auth failed")
        url = f"{self.base_url}/v1/models"
        req = urllib.request.Request(url, method="GET")
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(req)
        self.mock_client.token_provider.invalidate.assert_called_once()

    def test_options_cors_preflight(self):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("OPTIONS", "/v1/chat/completions")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 204)
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")
        self.assertEqual(resp.headers.get("Access-Control-Allow-Methods"), "GET, POST, OPTIONS")
        self.assertEqual(
            resp.headers.get("Access-Control-Allow-Headers"),
            "Content-Type, Authorization, x-api-key, anthropic-version, anthropic-beta, anthropic-auth-token, openai-beta, openai-organization, openai-project",
        )
        conn.close()

    def test_cors_header_on_get_and_streaming(self):
        status, headers, _ = self._http_get("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")

        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }
        resp = self._http_post("/v1/chat/completions", payload, stream=True)
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")
        resp.close()

    def test_content_length_invalid_returns_400(self):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.putrequest("POST", "/v1/chat/completions")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", "invalid_length")
        conn.endheaders()
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        body = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(body["error"]["type"], "invalid_request_error")
        conn.close()

    def test_content_length_too_large_returns_413(self):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.putrequest("POST", "/v1/chat/completions")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(11 * 1024 * 1024))
        conn.endheaders()
        resp = conn.getresponse()
        self.assertEqual(resp.status, 413)
        body = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], 413)
        conn.close()

    def test_chat_completions_streaming_includes_usage_and_finish_reason(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }
        resp = self._http_post("/v1/chat/completions", payload, stream=True)
        chunks = []
        for raw_line in resp:
            line_str = raw_line.decode("utf-8").strip()
            if line_str.startswith("data: ") and line_str != "data: [DONE]":
                chunks.append(json.loads(line_str[6:]))
        resp.close()

        # The last chunk should have finish_reason and usage
        last_chunk = chunks[-1]
        self.assertEqual(last_chunk["choices"][0]["finish_reason"], "stop")
        self.assertIn("usage", last_chunk)
        self.assertEqual(last_chunk["usage"]["prompt_tokens"], 5)
        self.assertEqual(last_chunk["usage"]["completion_tokens"], 7)

    def test_offline_startup_resilience(self):
        failing_client = MagicMock()
        failing_client.load_code_assist.side_effect = Exception("network unavailable")
        test_server = create_server(
            host="127.0.0.1",
            port=0,
            client=failing_client,
            project=None,
        )
        try:
            self.assertEqual(test_server.RequestHandlerClass.project, "aicode-consumers")
        finally:
            test_server.server_close()

    def test_streaming_broken_pipe_suppressed(self):
        handler = self.server.RequestHandlerClass.__new__(self.server.RequestHandlerClass)
        handler.client = self.mock_client
        handler.project = "test-project"
        handler.wfile = MagicMock()
        handler.wfile.write.side_effect = BrokenPipeError("Broken pipe")
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }
        # Should not raise BrokenPipeError or fail
        handler._handle_chat_completion(payload)
        self.assertTrue(getattr(handler, "close_connection", False))

    def test_non_streaming_broken_pipe_suppressed(self):
        handler = self.server.RequestHandlerClass.__new__(self.server.RequestHandlerClass)
        handler.client = self.mock_client
        handler.project = "test-project"
        handler.wfile = MagicMock()
        handler.wfile.write.side_effect = BrokenPipeError("Broken pipe")
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler._send_error = MagicMock()

        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False,
        }
        # Should silently ignore BrokenPipeError and not call _send_error
        handler._handle_chat_completion(payload)
        handler._send_error.assert_not_called()

    def test_chat_completions_non_dict_payload_returns_400(self):
        url = f"{self.base_url}/v1/chat/completions"
        for non_dict in (b'["array", "of", "items"]', b'12345', b'"a plain string"'):
            with self.subTest(payload=non_dict):
                req = urllib.request.Request(
                    url,
                    data=non_dict,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
                err = ctx.exception
                self.assertEqual(err.code, 400)
                body = json.loads(err.read().decode("utf-8"))
                self.assertEqual(body["error"]["message"], "Invalid request body: expected JSON object")
                self.assertEqual(body["error"]["type"], "invalid_request_error")

    def test_chat_completions_streaming_emits_assistant_role_on_first_chunk(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }
        resp = self._http_post("/v1/chat/completions", payload, stream=True)
        chunks = []
        for raw_line in resp:
            line_str = raw_line.decode("utf-8").strip()
            if line_str.startswith("data: ") and line_str != "data: [DONE]":
                chunks.append(json.loads(line_str[6:]))
        resp.close()

        # First chunk with content should have role: assistant
        first_content_chunk = next(c for c in chunks if c["choices"][0]["delta"].get("content"))
        self.assertEqual(first_content_chunk["choices"][0]["delta"].get("role"), "assistant")

        # Second chunk with content should NOT have role
        content_chunks = [c for c in chunks if c["choices"][0]["delta"].get("content")]
        if len(content_chunks) > 1:
            self.assertNotIn("role", content_chunks[1]["choices"][0]["delta"])

    def test_chat_completions_streaming_in_band_sse_error_pre_stream_maps_to_429(self):
        def error_gen():
            yield 'data: {"error": {"code": 429, "message": "Resource exhausted: quota exceeded", "status": "RESOURCE_EXHAUSTED"}}\n'

        self.mock_client.custom_stream_generator = error_gen
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }
        url = f"{self.base_url}/v1/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        err = ctx.exception
        self.assertEqual(err.code, 429)
        body = json.loads(err.read().decode("utf-8"))
        self.assertEqual(body["error"]["type"], "rate_limit_error")
        self.assertIn("quota exceeded", body["error"]["message"])

    def test_chat_completions_non_streaming_in_band_sse_error_maps_to_429(self):
        def error_gen():
            yield 'data: {"error": {"code": 429, "message": "Resource exhausted: quota exceeded", "status": "RESOURCE_EXHAUSTED"}}\n'

        self.mock_client.custom_stream_generator = error_gen
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False,
        }
        url = f"{self.base_url}/v1/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        err = ctx.exception
        self.assertEqual(err.code, 429)
        body = json.loads(err.read().decode("utf-8"))
        self.assertEqual(body["error"]["type"], "rate_limit_error")

    def test_streaming_generator_closed_on_client_disconnect(self):
        closed = False

        def tracking_gen():
            nonlocal closed
            try:
                yield 'data: {"candidates": [{"content": {"parts": [{"text": "Hello"}]}}]}\n'
                yield 'data: {"candidates": [{"content": {"parts": [{"text": " world"}]}}]}\n'
            finally:
                closed = True

        handler = self.server.RequestHandlerClass.__new__(self.server.RequestHandlerClass)
        handler.client = MagicMock()
        gen_instance = tracking_gen()
        handler.client.stream_generate_content.return_value = gen_instance
        handler.project = "test-project"
        handler.wfile = MagicMock()
        handler.wfile.write.side_effect = BrokenPipeError("Disconnected")
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }
        handler._handle_chat_completion(payload)
        self.assertTrue(closed)

    def test_streaming_mid_stream_error_cleanly_aborts(self):
        closed = False

        def failing_gen():
            nonlocal closed
            try:
                yield 'data: {"candidates": [{"content": {"parts": [{"text": "Part 1"}]}}]}\n'
                raise BridgeError("Mid stream upstream failure")
            finally:
                closed = True

        handler = self.server.RequestHandlerClass.__new__(self.server.RequestHandlerClass)
        handler.client = MagicMock()
        handler.client.stream_generate_content.return_value = failing_gen()
        handler.project = "test-project"
        handler.wfile = MagicMock()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }
        # Should not raise uncaught exception
        handler._handle_chat_completion(payload)
        self.assertTrue(closed)
        self.assertTrue(getattr(handler, "close_connection", False))

    def test_server_daemon_threads_set(self):
        server = create_server(host="127.0.0.1", port=0, client=self.mock_client, project="test-proj")
        try:
            self.assertTrue(server.daemon_threads)
        finally:
            server.server_close()

    def test_generation_config_forwarded_from_chat_completions(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 0.4,
            "max_tokens": 128,
            "top_p": 0.85,
            "stop": ["STOP_HERE"],
            "stream": True,
        }
        resp = self._http_post("/v1/chat/completions", payload, stream=True)
        resp.read()
        resp.close()

        self.assertEqual(
            self.mock_client.last_generation_config,
            {
                "temperature": 0.4,
                "maxOutputTokens": 128,
                "topP": 0.85,
                "stopSequences": ["STOP_HERE"],
                "thinkingConfig": {"thinkingBudget": 0},
            },
        )

    def test_streaming_mid_stream_unexpected_error_logged_to_stderr(self):
        def failing_gen():
            yield 'data: {"candidates": [{"content": {"parts": [{"text": "Part 1"}]}}]}\n'
            raise BridgeError("Mid stream upstream failure")

        handler = self.server.RequestHandlerClass.__new__(self.server.RequestHandlerClass)
        handler.client = MagicMock()
        handler.client.stream_generate_content.return_value = failing_gen()
        handler.project = "test-project"
        handler.wfile = MagicMock()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }

        with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
            handler._handle_chat_completion(payload)
            self.assertIn("Error during stream: Mid stream upstream failure", mock_stderr.getvalue())

    def test_streaming_broken_pipe_not_logged_to_stderr(self):
        handler = self.server.RequestHandlerClass.__new__(self.server.RequestHandlerClass)
        handler.client = self.mock_client
        handler.project = "test-project"
        handler.wfile = MagicMock()
        handler.wfile.write.side_effect = BrokenPipeError("Client disconnected")
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }

        with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
            handler._handle_chat_completion(payload)
            self.assertEqual(mock_stderr.getvalue(), "")

    def test_path_trailing_slash_normalization_get(self):
        status, _, body = self._http_get("/healthz/")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"status": "ok"})

        status, _, body = self._http_get("/v1/models/")
        self.assertEqual(status, 200)
        self.assertEqual(body["object"], "list")

    def test_path_trailing_slash_normalization_post(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False,
        }
        status, _, body = self._http_post("/v1/chat/completions/", payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["object"], "chat.completion")

    def test_invalid_content_length_connection_close_header(self):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.putrequest("POST", "/v1/chat/completions")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", "invalid_length")
        conn.endheaders()
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        self.assertEqual(resp.getheader("Connection"), "close")
        conn.close()

    def test_content_length_too_large_connection_close_header(self):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.putrequest("POST", "/v1/chat/completions")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(11 * 1024 * 1024))
        conn.endheaders()
        resp = conn.getresponse()
        self.assertEqual(resp.status, 413)
        self.assertEqual(resp.getheader("Connection"), "close")
        conn.close()

    def test_malformed_json_connection_close_header(self):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.putrequest("POST", "/v1/chat/completions")
        conn.putheader("Content-Type", "application/json")
        data = b"{invalid-json"
        conn.putheader("Content-Length", str(len(data)))
        conn.endheaders()
        conn.send(data)
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        self.assertEqual(resp.getheader("Connection"), "close")
        conn.close()

    def test_non_dict_payload_connection_close_header(self):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.putrequest("POST", "/v1/chat/completions")
        conn.putheader("Content-Type", "application/json")
        data = b"[1, 2, 3]"
        conn.putheader("Content-Length", str(len(data)))
        conn.endheaders()
        conn.send(data)
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        self.assertEqual(resp.getheader("Connection"), "close")
        conn.close()

    def test_request_handler_timeout_is_60(self):
        self.assertEqual(OpenAIRequestHandler.timeout, 60.0)

    def test_streaming_mid_stream_unexpected_error_sends_sse_error_chunk(self):
        def failing_gen():
            yield 'data: {"candidates": [{"content": {"parts": [{"text": "Part 1"}]}}]}\n'
            raise RuntimeError("Mid stream unexpected error")

        handler = self.server.RequestHandlerClass.__new__(self.server.RequestHandlerClass)
        handler.client = MagicMock()
        handler.client.stream_generate_content.return_value = failing_gen()
        handler.project = "test-project"
        written_chunks = []
        handler.wfile = MagicMock()
        handler.wfile.write.side_effect = lambda data: written_chunks.append(data.decode("utf-8") if isinstance(data, bytes) else data)
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }

        with patch("sys.stderr", new_callable=io.StringIO):
            handler._handle_chat_completion(payload)

        # Confirm an SSE error chunk was written to wfile
        error_chunks = [c for c in written_chunks if "error" in c and "Mid stream unexpected error" in c]
        self.assertTrue(len(error_chunks) > 0, f"Expected SSE error chunk in written_chunks: {written_chunks}")
        parsed_chunk = json.loads(error_chunks[0].replace("data: ", "").strip())
        self.assertEqual(parsed_chunk["error"]["code"], 500)
        self.assertEqual(parsed_chunk["error"]["type"], "api_error")
        self.assertEqual(parsed_chunk["error"]["message"], "Mid stream unexpected error")

    def test_root_dashboard_endpoint(self):
        status, headers, body = self._http_get_raw("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get_content_type())
        self.assertIn("AGY Model Bridge", body)
        self.assertIn("FreeLLMAPI", body)
        self.assertIn("Claude Code", body)
        self.assertIn("Codex", body)

    def test_api_status_endpoint(self):
        status, headers, body = self._http_get("/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get_content_type(), "application/json")
        self.assertIn("address", body)
        self.assertIn("auth", body)
        self.assertIn("models_count", body)

    def test_anthropic_messages_non_streaming(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello Claude"}],
        }
        status, headers, body = self._http_post("/v1/messages", payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["type"], "message")
        self.assertEqual(body["role"], "assistant")
        self.assertEqual(body["model"], "gemini-2.5-pro")
        self.assertIn("Hello world!", body["content"][0]["text"])

    def test_anthropic_messages_streaming(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello Claude"}],
            "stream": True,
        }
        resp = self._http_post("/v1/messages", payload, stream=True)
        self.assertEqual(resp.status, 200)
        self.assertIn("text/event-stream", resp.headers.get_content_type())
        raw_events = resp.read().decode("utf-8")
        resp.close()
        self.assertIn("event: message_start", raw_events)
        self.assertIn("event: content_block_delta", raw_events)
        self.assertIn("event: message_stop", raw_events)

    def test_anthropic_messages_validation_error(self):
        url = f"{self.base_url}/v1/messages"
        req = urllib.request.Request(
            url,
            data=b'{"messages": []}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5.0)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["type"], "error")
        self.assertEqual(body["error"]["type"], "invalid_request_error")

    def test_responses_non_streaming(self):
        payload = {
            "model": "gemini-2.5-pro",
            "input": ["Hello Codex"],
        }
        status, headers, body = self._http_post("/v1/responses", payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["object"], "response")
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["model"], "gemini-2.5-pro")
        self.assertIn("Hello world!", body["output"][0]["content"][0]["text"])

    def test_responses_streaming(self):
        payload = {
            "model": "gemini-2.5-pro",
            "input": ["Hello Codex"],
            "stream": True,
        }
        resp = self._http_post("/v1/responses", payload, stream=True)
        self.assertEqual(resp.status, 200)
        self.assertIn("text/event-stream", resp.headers.get_content_type())
        raw_events = resp.read().decode("utf-8")
        resp.close()
        self.assertIn("event: response.created", raw_events)
        self.assertIn("event: response.output_text.delta", raw_events)
        self.assertIn("event: response.completed", raw_events)

    def test_responses_validation_error(self):
        url = f"{self.base_url}/v1/responses"
        req = urllib.request.Request(
            url,
            data=b'{"model": "gemini-2.5-pro", "input": []}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5.0)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["type"], "invalid_request_error")

    def test_non_get_on_root_returns_404_or_405(self):
        url = f"{self.base_url}/"
        req = urllib.request.Request(
            url,
            data=b'{"test": 1}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5.0)
        self.assertIn(ctx.exception.code, (404, 405))


    def test_anthropic_streaming_in_band_sse_error_pre_stream_maps_to_429(self):
        def error_gen():
            yield 'data: {"error": {"code": 429, "message": "Resource exhausted: Anthropic quota exceeded", "status": "RESOURCE_EXHAUSTED"}}\n'

        self.mock_client.custom_stream_generator = error_gen
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }
        url = f"{self.base_url}/v1/messages"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        err = ctx.exception
        self.assertEqual(err.code, 429)
        body = json.loads(err.read().decode("utf-8"))
        self.assertEqual(body["type"], "error")
        self.assertEqual(body["error"]["type"], "rate_limit_error")

    def test_anthropic_streaming_empty_stream_returns_error_before_headers(self):
        def empty_gen():
            return
            yield

        self.mock_client.custom_stream_generator = empty_gen
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }
        url = f"{self.base_url}/v1/messages"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)

    def test_responses_streaming_in_band_sse_error_pre_stream_maps_to_429(self):
        def error_gen():
            yield 'data: {"error": {"code": 429, "message": "Resource exhausted: Responses quota exceeded", "status": "RESOURCE_EXHAUSTED"}}\n'

        self.mock_client.custom_stream_generator = error_gen
        payload = {
            "model": "gemini-2.5-pro",
            "input": ["Hello"],
            "stream": True,
        }
        url = f"{self.base_url}/v1/responses"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        err = ctx.exception
        self.assertEqual(err.code, 429)
        body = json.loads(err.read().decode("utf-8"))
        self.assertEqual(body["error"]["type"], "rate_limit_error")

    def test_responses_streaming_empty_stream_returns_error_before_headers(self):
        def empty_gen():
            return
            yield

        self.mock_client.custom_stream_generator = empty_gen
        payload = {
            "model": "gemini-2.5-pro",
            "input": ["Hello"],
            "stream": True,
        }
        url = f"{self.base_url}/v1/responses"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)

    def test_anthropic_non_streaming_generator_closed(self):
        closed = False

        def tracking_gen():
            nonlocal closed
            try:
                yield 'data: {"candidates": [{"content": {"parts": [{"text": "Hello"}]}}]}\n'
            finally:
                closed = True

        handler = self.server.RequestHandlerClass.__new__(self.server.RequestHandlerClass)
        handler.client = MagicMock()
        handler.client.stream_generate_content.return_value = tracking_gen()
        handler.project = "test-project"
        handler._send_json = MagicMock()

        handler._handle_anthropic_messages({"model": "gemini-2.5-pro", "messages": [{"role": "user", "content": "hi"}]})
        self.assertTrue(closed)

    def test_responses_non_streaming_generator_closed(self):
        closed = False

        def tracking_gen():
            nonlocal closed
            try:
                yield 'data: {"candidates": [{"content": {"parts": [{"text": "Hello"}]}}]}\n'
            finally:
                closed = True

        handler = self.server.RequestHandlerClass.__new__(self.server.RequestHandlerClass)
        handler.client = MagicMock()
        handler.client.stream_generate_content.return_value = tracking_gen()
        handler.project = "test-project"
        handler._send_json = MagicMock()

        handler._handle_responses({"model": "gemini-2.5-pro", "input": ["hi"]})
        self.assertTrue(closed)

    def test_anthropic_streaming_broken_pipe_suppressed(self):
        handler = self.server.RequestHandlerClass.__new__(self.server.RequestHandlerClass)
        handler.client = self.mock_client
        handler.project = "test-project"
        handler.wfile = MagicMock()
        handler.wfile.write.side_effect = BrokenPipeError("Broken pipe")
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }
        handler._handle_anthropic_messages(payload)
        self.assertTrue(getattr(handler, "close_connection", False))

    def test_responses_streaming_broken_pipe_suppressed(self):
        handler = self.server.RequestHandlerClass.__new__(self.server.RequestHandlerClass)
        handler.client = self.mock_client
        handler.project = "test-project"
        handler.wfile = MagicMock()
        handler.wfile.write.side_effect = BrokenPipeError("Broken pipe")
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        payload = {
            "model": "gemini-2.5-pro",
            "input": ["Hello"],
            "stream": True,
        }
        handler._handle_responses(payload)
        self.assertTrue(getattr(handler, "close_connection", False))

    def test_anthropic_streaming_mid_stream_unexpected_error_sends_sse_error_event(self):
        def failing_gen():
            yield 'data: {"candidates": [{"content": {"parts": [{"text": "Part 1"}]}}]}\n'
            raise RuntimeError("Mid-stream failure in Anthropic")

        handler = self.server.RequestHandlerClass.__new__(self.server.RequestHandlerClass)
        handler.client = MagicMock()
        handler.client.stream_generate_content.return_value = failing_gen()
        handler.project = "test-project"
        written_chunks = []
        handler.wfile = MagicMock()
        handler.wfile.write.side_effect = lambda data: written_chunks.append(data.decode("utf-8") if isinstance(data, bytes) else data)
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }

        with patch("sys.stderr", new_callable=io.StringIO):
            handler._handle_anthropic_messages(payload)

        # Confirm event: error\ndata: {"type": "error", "error": {"type": "api_error", "message": "..."}}\n\n
        error_chunks = [c for c in written_chunks if "event: error" in c and "Mid-stream failure in Anthropic" in c]
        self.assertTrue(len(error_chunks) > 0, f"Expected Anthropic error chunk: {written_chunks}")
        self.assertTrue(getattr(handler, "close_connection", False))

    def test_responses_streaming_mid_stream_unexpected_error_sends_response_failed_event(self):
        def failing_gen():
            yield 'data: {"candidates": [{"content": {"parts": [{"text": "Part 1"}]}}]}\n'
            raise RuntimeError("Mid-stream failure in Responses")

        handler = self.server.RequestHandlerClass.__new__(self.server.RequestHandlerClass)
        handler.client = MagicMock()
        handler.client.stream_generate_content.return_value = failing_gen()
        handler.project = "test-project"
        written_chunks = []
        handler.wfile = MagicMock()
        handler.wfile.write.side_effect = lambda data: written_chunks.append(data.decode("utf-8") if isinstance(data, bytes) else data)
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        payload = {
            "model": "gemini-2.5-pro",
            "input": ["Hello"],
            "stream": True,
        }

        with patch("sys.stderr", new_callable=io.StringIO):
            handler._handle_responses(payload)

        # Confirm event: response.failed\ndata: {"type": "response.failed", "response": {"status": "failed", ...}}\n\n
        error_chunks = [c for c in written_chunks if "event: response.failed" in c and "Mid-stream failure in Responses" in c]
        self.assertTrue(len(error_chunks) > 0, f"Expected Responses response.failed chunk: {written_chunks}")
        parsed_err = json.loads(error_chunks[0].split("data: ")[1].strip())
        self.assertTrue(parsed_err["response"]["id"].startswith("resp_"))
        self.assertTrue(getattr(handler, "close_connection", False))


if __name__ == "__main__":
    unittest.main()
