import http.client
import io
import json
import socket
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from bridge.client import (
    CloudCodeClient,
    BridgeError,
    AuthenticationError,
    ForbiddenError,
    InvalidRequestError,
    ModelNotFoundError,
    RateLimitError,
    CapacityExhaustedError,
    UpstreamTimeoutError,
)


class DummyTokenProvider:
    def __init__(self, token: str = "ya29.initial_token"):
        self.token = token
        self.invalidated = False
        self.call_count = 0

    def get_token(self, force_refresh: bool = False) -> str:
        self.call_count += 1
        if force_refresh:
            self.token = "ya29.refreshed_token"
        return self.token

    def invalidate(self) -> None:
        self.invalidated = True


class TestCloudCodeClient(unittest.TestCase):
    def setUp(self):
        self.token_provider = DummyTokenProvider()
        self.client = CloudCodeClient(
            token_provider=self.token_provider,
            base_url="https://daily-cloudcode-pa.googleapis.com",
            timeout=10.0,
        )

    @patch("urllib.request.urlopen")
    def test_request_headers_and_payload(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "ok"}).encode("utf-8")
        mock_urlopen.return_value = mock_resp

        self.client._request("/v1internal:testEndpoint", {"key": "val"})

        self.assertTrue(mock_urlopen.called)
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://daily-cloudcode-pa.googleapis.com/v1internal:testEndpoint")
        self.assertEqual(req.headers["Authorization"], "Bearer ya29.initial_token")
        self.assertEqual(req.headers["Content-type"], "application/json")
        self.assertEqual(req.headers["User-agent"], "antigravity/1.0")
        self.assertEqual(json.loads(req.data.decode("utf-8")), {"key": "val"})

    @patch("urllib.request.urlopen")
    def test_load_code_assist(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "cloudaicompanionProject": "projects/aicode-consumers",
            "tier": "TIER_ENTERPRISE",
        }).encode("utf-8")
        mock_urlopen.return_value = mock_resp

        result = self.client.load_code_assist()
        self.assertEqual(result["project"], "aicode-consumers")
        self.assertEqual(result["tier"], "TIER_ENTERPRISE")

        req = mock_urlopen.call_args[0][0]
        self.assertIn("/v1internal:loadCodeAssist", req.full_url)
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload, {
            "metadata": {
                "ideType": "ANTIGRAVITY",
                "platform": "PLATFORM_UNSPECIFIED",
                "pluginType": "GEMINI",
            }
        })

    @patch("urllib.request.urlopen")
    def test_fetch_available_models(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "models": [
                {"name": "models/gemini-2.5-pro"},
                {"name": "models/gemini-2.5-flash"},
            ]
        }).encode("utf-8")
        mock_urlopen.return_value = mock_resp

        models = self.client.fetch_available_models(project="aicode-consumers")
        self.assertEqual(len(models), 2)
        self.assertEqual(models[0]["name"], "models/gemini-2.5-pro")

        req = mock_urlopen.call_args[0][0]
        self.assertIn("/v1internal:fetchAvailableModels", req.full_url)
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["project"], "aicode-consumers")

    @patch("urllib.request.urlopen")
    def test_stream_generate_content_yields_lines(self, mock_urlopen):
        sse_lines = [
            b'data: {"candidates": [{"content": {"parts": [{"text": "Hello"}]}}]}\n',
            b'\n',
            b'data: {"candidates": [{"content": {"parts": [{"text": " world"}]}}]}\n',
            b'data: [DONE]\n',
        ]
        mock_resp = MagicMock()
        mock_resp.__iter__.return_value = iter(sse_lines)
        mock_urlopen.return_value = mock_resp

        lines = list(self.client.stream_generate_content(
            project="aicode-consumers",
            model="gemini-2.5-pro",
            contents=[{"role": "user", "parts": [{"text": "Hi"}]}],
            system_instruction={"parts": [{"text": "Be brief."}]},
        ))

        self.assertEqual(len(lines), 4)
        self.assertTrue(lines[0].startswith('data: {"candidates"'))

        req = mock_urlopen.call_args[0][0]
        self.assertIn("/v1internal:streamGenerateContent?alt=sse", req.full_url)
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["project"], "aicode-consumers")
        self.assertEqual(payload["model"], "gemini-2.5-pro")
        self.assertEqual(payload["request"]["contents"], [{"role": "user", "parts": [{"text": "Hi"}]}])
        self.assertEqual(payload["request"]["systemInstruction"], {"parts": [{"text": "Be brief."}]})

    @patch("urllib.request.urlopen")
    def test_stream_generate_content_with_generation_config(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.__iter__.return_value = iter([b'data: {"candidates": []}\n'])
        mock_urlopen.return_value = mock_resp

        gen_cfg = {
            "temperature": 0.5,
            "maxOutputTokens": 100,
            "topP": 0.9,
            "stopSequences": ["STOP"],
        }
        lines = list(
            self.client.stream_generate_content(
                project="aicode-consumers",
                model="gemini-2.5-pro",
                contents=[{"role": "user", "parts": [{"text": "Hi"}]}],
                generation_config=gen_cfg,
            )
        )
        self.assertEqual(len(lines), 1)

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["request"]["generationConfig"], gen_cfg)

    @patch("urllib.request.urlopen")
    def test_stream_generate_content_with_tools_and_tool_config(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.__iter__.return_value = iter([b'data: {"candidates": []}\n'])
        mock_urlopen.return_value = mock_resp

        tools_val = [{"functionDeclarations": [{"name": "test_tool", "parameters": {}}]}]
        tool_cfg_val = {"functionCallingConfig": {"mode": "AUTO"}}
        lines = list(
            self.client.stream_generate_content(
                project="aicode-consumers",
                model="gemini-2.5-pro",
                contents=[{"role": "user", "parts": [{"text": "Hi"}]}],
                tools=tools_val,
                tool_config=tool_cfg_val,
            )
        )
        self.assertEqual(len(lines), 1)

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["request"]["tools"], tools_val)
        self.assertEqual(payload["request"]["toolConfig"], tool_cfg_val)

    @patch("urllib.request.urlopen")
    def test_stream_generate_content_closes_response_on_exit(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.__iter__.return_value = iter([b"data: 1\n", b"data: 2\n"])
        mock_urlopen.return_value = mock_resp

        gen = self.client.stream_generate_content(
            project="aicode-consumers",
            model="gemini-2.5-pro",
            contents=[{"role": "user", "parts": [{"text": "Hi"}]}],
        )
        first_line = next(gen)
        self.assertEqual(first_line, "data: 1\n")
        gen.close()
        mock_resp.close.assert_called_once()

    @patch("urllib.request.urlopen")
    def test_stream_generate_content_timeout_raises_upstream_timeout_error(self, mock_urlopen):
        def timeout_gen():
            yield b"data: 1\n"
            raise socket.timeout("read timeout")

        mock_resp = MagicMock()
        mock_resp.__iter__.return_value = timeout_gen()
        mock_urlopen.return_value = mock_resp

        gen = self.client.stream_generate_content(
            project="aicode-consumers",
            model="gemini-2.5-pro",
            contents=[{"role": "user", "parts": [{"text": "Hi"}]}],
        )
        self.assertEqual(next(gen), "data: 1\n")
        with self.assertRaises(UpstreamTimeoutError):
            next(gen)
        mock_resp.close.assert_called_once()

    @patch("urllib.request.urlopen")
    def test_stream_generate_content_mid_stream_network_error_raises_bridge_error(self, mock_urlopen):
        network_errors = [
            ConnectionResetError("Connection reset"),
            http.client.RemoteDisconnected("Remote disconnected"),
            urllib.error.URLError("URLError mid-stream"),
        ]
        for err in network_errors:
            with self.subTest(err=err):
                def err_gen(e=err):
                    yield b"data: 1\n"
                    raise e

                mock_resp = MagicMock()
                mock_resp.__iter__.return_value = err_gen()
                mock_urlopen.return_value = mock_resp

                gen = self.client.stream_generate_content(
                    project="aicode-consumers",
                    model="gemini-2.5-pro",
                    contents=[{"role": "user", "parts": [{"text": "Hi"}]}],
                )
                self.assertEqual(next(gen), "data: 1\n")
                with self.assertRaises(BridgeError) as ctx:
                    next(gen)
                self.assertIn("Upstream stream error", str(ctx.exception))
                mock_resp.close.assert_called()

    @patch("urllib.request.urlopen")
    def test_stream_generate_content_utf8_replacement(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.__iter__.return_value = iter([b"data: invalid-\xff\xfe-utf8\n"])
        mock_urlopen.return_value = mock_resp

        lines = list(
            self.client.stream_generate_content(
                project="aicode-consumers",
                model="gemini-2.5-pro",
                contents=[{"role": "user", "parts": [{"text": "Hi"}]}],
            )
        )
        self.assertEqual(len(lines), 1)
        self.assertIn("\ufffd", lines[0])

    @patch("urllib.request.urlopen")
    def test_401_closes_http_error_before_retry(self, mock_urlopen):
        err_body = b'{"error": {"message": "Unauthorized"}}'
        http_401 = urllib.error.HTTPError(
            url="https://test",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=io.BytesIO(err_body),
        )
        http_401.close = MagicMock()

        success_resp = MagicMock()
        success_resp.read.return_value = json.dumps({"status": "ok"}).encode("utf-8")
        mock_urlopen.side_effect = [http_401, success_resp]

        self.client._request("/test", {})
        http_401.close.assert_called_once()
        self.assertEqual(mock_urlopen.call_count, 2)

    @patch("urllib.request.urlopen")
    def test_fetch_available_models_dict_format(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "models": {
                "gemini-2.5-pro": {"displayName": "Gemini 2.5 Pro"},
                "gemini-2.5-flash": "some_string_meta",
            }
        }).encode("utf-8")
        mock_urlopen.return_value = mock_resp

        models = self.client.fetch_available_models(project="aicode-consumers")
        self.assertEqual(len(models), 2)
        pro_model = next(m for m in models if m["id"] == "gemini-2.5-pro")
        self.assertEqual(pro_model["displayName"], "Gemini 2.5 Pro")
        flash_model = next(m for m in models if m["id"] == "gemini-2.5-flash")
        self.assertEqual(flash_model["id"], "gemini-2.5-flash")

    @patch("urllib.request.urlopen")
    def test_error_mapping_status_codes(self, mock_urlopen):
        test_cases = [
            (400, InvalidRequestError),
            (401, AuthenticationError),
            (403, ForbiddenError),
            (404, ModelNotFoundError),
            (429, RateLimitError),
            (503, CapacityExhaustedError),
        ]

        for code, expected_exc in test_cases:
            with self.subTest(status_code=code):
                err_body = json.dumps({"error": {"message": f"Error {code}"}}).encode("utf-8")
                http_err = urllib.error.HTTPError(
                    url="https://test",
                    code=code,
                    msg=f"Error {code}",
                    hdrs={},
                    fp=io.BytesIO(err_body),
                )
                mock_urlopen.side_effect = http_err

                with self.assertRaises(expected_exc):
                    self.client.load_code_assist()

    @patch("urllib.request.urlopen")
    def test_timeout_raises_upstream_timeout_error(self, mock_urlopen):
        mock_urlopen.side_effect = socket.timeout("timed out")
        with self.assertRaises(UpstreamTimeoutError):
            self.client.load_code_assist()

        mock_urlopen.side_effect = urllib.error.URLError(socket.timeout("timed out"))
        with self.assertRaises(UpstreamTimeoutError):
            self.client.load_code_assist()

    @patch("urllib.request.urlopen")
    def test_401_triggers_token_refresh_and_retry(self, mock_urlopen):
        # 1st call fails with 401, 2nd call succeeds
        err_body = b'{"error": {"message": "Unauthorized"}}'
        http_401 = urllib.error.HTTPError(
            url="https://test",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=io.BytesIO(err_body),
        )
        success_resp = MagicMock()
        success_resp.read.return_value = json.dumps({"project": "aicode-consumers"}).encode("utf-8")

        mock_urlopen.side_effect = [http_401, success_resp]

        res = self.client._request("/test", {})
        self.assertEqual(json.loads(res.decode("utf-8")), {"project": "aicode-consumers"})
        self.assertTrue(self.token_provider.invalidated)
        self.assertEqual(mock_urlopen.call_count, 2)

    @patch("urllib.request.urlopen")
    def test_401_retry_exhaustion_raises_authentication_error(self, mock_urlopen):
        # 1st call fails with 401, 2nd retry also fails with 401
        err_body = b'{"error": {"message": "Unauthorized"}}'
        mock_urlopen.side_effect = [
            urllib.error.HTTPError("https://test", 401, "Unauthorized", {}, io.BytesIO(err_body)),
            urllib.error.HTTPError("https://test", 401, "Unauthorized", {}, io.BytesIO(err_body)),
        ]

        with self.assertRaises(AuthenticationError) as ctx:
            self.client._request("/test", {})
        self.assertIn("authentication", str(ctx.exception).lower())
        self.assertEqual(mock_urlopen.call_count, 2)

    @patch("urllib.request.urlopen")
    def test_non_streaming_urlopen_closes_response(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "ok"}'
        mock_urlopen.return_value = mock_resp

        self.client._request("/test", {}, stream=False)
        mock_resp.close.assert_called_once()

    @patch("urllib.request.urlopen")
    def test_401_retry_non_streaming_closes_response(self, mock_urlopen):
        err_body = b'{"error": {"message": "Unauthorized"}}'
        http_401 = urllib.error.HTTPError(
            url="https://test",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=io.BytesIO(err_body),
        )
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "ok"}'
        mock_urlopen.side_effect = [http_401, mock_resp]

        self.client._request("/test", {}, stream=False)
        mock_resp.close.assert_called_once()

    @patch("urllib.request.urlopen")
    def test_raw_http_exception_wrapped_in_bridge_error(self, mock_urlopen):
        mock_urlopen.side_effect = http.client.RemoteDisconnected("Remote disconnected")
        with self.assertRaises(BridgeError) as ctx:
            self.client._request("/test", {})
        self.assertIn("Upstream connection error", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_raw_os_error_wrapped_in_bridge_error(self, mock_urlopen):
        mock_urlopen.side_effect = ConnectionResetError("Connection reset by peer")
        with self.assertRaises(BridgeError) as ctx:
            self.client._request("/test", {})
        self.assertIn("Upstream connection error", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_401_retry_raw_os_error_wrapped_in_bridge_error(self, mock_urlopen):
        err_body = b'{"error": {"message": "Unauthorized"}}'
        http_401 = urllib.error.HTTPError(
            url="https://test",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=io.BytesIO(err_body),
        )
        mock_urlopen.side_effect = [http_401, ConnectionResetError("Connection reset on retry")]
        with self.assertRaises(BridgeError) as ctx:
            self.client._request("/test", {})
        self.assertIn("Upstream connection error", str(ctx.exception))

    def test_map_http_error_closes_err_on_all_status_codes(self):
        codes = [400, 401, 403, 404, 429, 500, 503]
        for code in codes:
            with self.subTest(code=code):
                err_fp = io.BytesIO(b'{"error": "something"}')
                http_err = urllib.error.HTTPError(
                    url="https://test",
                    code=code,
                    msg=f"HTTP {code}",
                    hdrs={},
                    fp=err_fp,
                )
                http_err.close = MagicMock()
                self.client._map_http_error(http_err)
                http_err.close.assert_called_once()

    def test_map_http_error_handles_string_error_payload(self):
        err_body = json.dumps({"error": "Quota exceeded for project"}).encode("utf-8")
        http_err = urllib.error.HTTPError(
            url="https://test",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=io.BytesIO(err_body),
        )
        exc = self.client._map_http_error(http_err)
        self.assertIsInstance(exc, RateLimitError)
        self.assertIn("Quota exceeded for project", str(exc))

    def test_map_http_error_handles_dict_error_payload(self):
        err_body = json.dumps({"error": {"message": "Invalid argument provided"}}).encode("utf-8")
        http_err = urllib.error.HTTPError(
            url="https://test",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=io.BytesIO(err_body),
        )
        exc = self.client._map_http_error(http_err)
        self.assertIsInstance(exc, InvalidRequestError)
        self.assertIn("Invalid argument provided", str(exc))


if __name__ == "__main__":

    unittest.main()
