"""Unit tests for the OpenCode backend (free-tier model discovery, execution, error mapping)."""

import json
from unittest.mock import MagicMock, patch

from bridge.errors import AuthenticationError, BridgeError, ForbiddenError
from bridge.opencode_backend import (
    OpencodeBackend,
    format_opencode_model_display_name,
    is_opencode_free_model,
    is_opencode_model,
    parse_run_events,
    resolve_opencode_model,
)
import unittest


MODELS_STDOUT = """opencode/pulse-alpha-free
opencode/beam-free
opencode/big-pickle
google/gemini-2.5-flash
openai/gpt-5.2
opencode/deepseek-v4.1-flash-free
"""


class TestModelIdPredicates(unittest.TestCase):
    """Free-tier classification and model id resolution (S2)."""

    def test_free_models_detected(self) -> None:
        self.assertTrue(is_opencode_free_model("opencode/pulse-alpha-free"))
        self.assertTrue(is_opencode_free_model("opencode/nemotron-3.5-super-vl-free"))

    def test_non_free_not_classified_as_free(self) -> None:
        self.assertFalse(is_opencode_free_model("opencode/big-pickle"))
        self.assertFalse(is_opencode_free_model("google/gemini-2.5-flash"))
        self.assertFalse(is_opencode_free_model("openai/gpt-5.2"))
        self.assertFalse(is_opencode_free_model(""))
        self.assertFalse(is_opencode_free_model("cursor/auto"))

    def test_is_opencode_model_accepts_prefixed_ids(self) -> None:
        self.assertTrue(is_opencode_model("opencode/pulse-alpha-free"))
        self.assertTrue(is_opencode_model("opencode/big-pickle"))
        self.assertFalse(is_opencode_model("google/gemini-2.5-flash"))
        self.assertFalse(is_opencode_model("cursor/auto"))
        self.assertFalse(is_opencode_model("gemini-2.5-pro"))
        self.assertFalse(is_opencode_model(""))

    def test_resolve_strips_provider_prefix(self) -> None:
        self.assertEqual(resolve_opencode_model("opencode/pulse-alpha-free"), "opencode/pulse-alpha-free")
        self.assertEqual(resolve_opencode_model("pulse-alpha-free"), "opencode/pulse-alpha-free")
        self.assertEqual(resolve_opencode_model(""), "opencode/pulse-alpha-free")


class TestDisplayNames(unittest.TestCase):
    """Source tag parity with Cursor display names (S3)."""

    def test_display_name_has_source_tag(self) -> None:
        self.assertEqual(
            format_opencode_model_display_name("opencode/pulse-alpha-free"),
            "Pulse Alpha Free [OpenCode]",
        )

    def test_display_name_other_models(self) -> None:
        self.assertEqual(
            format_opencode_model_display_name("opencode/beam-free"),
            "Beam Free [OpenCode]",
        )
        self.assertEqual(
            format_opencode_model_display_name("opencode/deepseek-v4.1-flash-free"),
            "DeepSeek V4.1 Flash Free [OpenCode]",
        )
        self.assertEqual(
            format_opencode_model_display_name("opencode/nemotron-3.5-super-vl-free"),
            "Nemotron 3.5 Super VL Free [OpenCode]",
        )

    def test_known_display_name_overrides_generation(self) -> None:
        # A curated name wins over the generated one but keeps the [OpenCode] tag.
        with patch("bridge.opencode_backend.OPENCODE_KNOWN_DISPLAY_NAMES", {"big-pickle": "Big Pickle"}):
            self.assertEqual(
                format_opencode_model_display_name("opencode/big-pickle"),
                "Big Pickle [OpenCode]",
            )


class TestModelDiscovery(unittest.TestCase):
    """`opencode models` parsing, free-only filtering, caching, fallback (S1, S2)."""

    def _backend(self, stdout: str = MODELS_STDOUT, returncode: int = 0) -> OpencodeBackend:
        backend = OpencodeBackend(binary_path="/usr/bin/opencode")
        backend._acp_client = MagicMock()  # never spawn real processes here
        run = MagicMock()
        run.return_value = MagicMock(returncode=returncode, stdout=stdout, stderr="")
        self._run = run
        return backend

    def test_list_models_filters_free_only_and_tags_source(self) -> None:
        backend = self._backend()
        with patch("bridge.opencode_backend.subprocess.run", self._run):
            models = backend.list_models()
        ids = [m["id"] for m in models]
        self.assertEqual(
            ids,
            [
                "opencode/pulse-alpha-free",
                "opencode/beam-free",
                "opencode/deepseek-v4.1-flash-free",
            ],
        )
        for m in models:
            self.assertEqual(m["owned_by"], "opencode")
            self.assertEqual(m["slug"], m["id"])
            self.assertTrue(m["display_name"].endswith("[OpenCode]"))

    def test_list_models_falls_back_to_static_free_list(self) -> None:
        backend = self._backend(stdout="", returncode=1)
        with patch("bridge.opencode_backend.subprocess.run", self._run):
            models = backend.list_models()
        ids = [m["id"] for m in models]
        self.assertIn("opencode/pulse-alpha-free", ids)
        self.assertIn("opencode/beam-free", ids)
        # Fallback must never contain paid/other-provider models
        self.assertFalse(any(i.startswith(("google/", "openai/")) for i in ids))
        self.assertFalse(any(i == "opencode/big-pickle" for i in ids))

    def test_list_models_uses_cache_on_second_call(self) -> None:
        backend = self._backend()
        with patch("bridge.opencode_backend.subprocess.run", self._run):
            backend.list_models()
            backend.list_models()
        self.assertEqual(self._run.call_count, 1)

    def test_list_models_force_bypasses_cache(self) -> None:
        backend = self._backend()
        with patch("bridge.opencode_backend.subprocess.run", self._run):
            backend.list_models()
            backend.list_models(force=True)
        self.assertEqual(self._run.call_count, 2)

    def test_discovery_timeout_never_breaks_catalog(self) -> None:
        import subprocess as sp
        backend = self._backend()
        with patch("bridge.opencode_backend.subprocess.run", side_effect=sp.TimeoutExpired("opencode", 2)):
            models = backend.list_models()
        self.assertTrue(any(m["id"] == "opencode/pulse-alpha-free" for m in models))


class TestRunEventParser(unittest.TestCase):
    """`opencode run --format json` event parsing for the CLI fallback (S4)."""

    def test_extracts_text_deltas(self) -> None:
        events = [
            {"type": "step_start", "part": {"type": "step-start"}},
            {"type": "text", "part": {"type": "text", "text": "Hello "}},
            {"type": "text", "part": {"type": "text", "text": "Hello world"}},
            {"type": "step_finish", "part": {"type": "step-finish"}},
        ]
        lines = "\n".join(json.dumps(e) for e in events)
        self.assertEqual(
            "".join(t for k, t in parse_run_events(lines.splitlines()) if k == "text"),
            "Hello world",
        )

    def test_error_event_captured(self) -> None:
        err = {
            "type": "error",
            "error": {
                "name": "APIError",
                "data": {
                    "message": "This model is not available in your country",
                    "statusCode": 403,
                },
            },
        }
        events = list(parse_run_events([json.dumps(err)]))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "error")
        self.assertIn("not available in your country", events[0][1])

    def test_malformed_lines_ignored(self) -> None:
        events = [
            "not json at all",
            "",
            json.dumps({"type": "text", "part": {"type": "text", "text": "ok"}}),
        ]
        parsed = [e for e in parse_run_events(events) if e[0] == "text"]
        self.assertEqual("".join(t for _, t in parsed), "ok")


class TestBackendExecution(unittest.TestCase):
    """ACP-first execution with CLI fallback and readable error mapping (S4, S5)."""

    def test_stream_chat_prefers_acp_with_resolved_model(self) -> None:
        acp = MagicMock()
        acp.is_alive.return_value = True
        acp.stream_prompt.return_value = iter(["PO", "NG"])
        backend = OpencodeBackend(binary_path="/usr/bin/opencode", acp_client=acp)

        out = "".join(backend.stream_chat("Say PONG", model="pulse-alpha-free"))
        self.assertEqual(out, "PONG")
        kwargs = acp.stream_prompt.call_args.kwargs
        self.assertEqual(kwargs["model"], "opencode/pulse-alpha-free")

    def test_stream_chat_maps_acp_region_error_to_forbidden(self) -> None:
        acp = MagicMock()
        acp.is_alive.return_value = True

        def boom(*a, **k):
            raise ForbiddenError("OpenCode model 'opencode/pulse-alpha-free' is not available in your region (upstream: ...)")
            yield  # pragma: no cover

        acp.stream_prompt.side_effect = boom
        backend = OpencodeBackend(binary_path="/usr/bin/opencode", acp_client=acp)
        with self.assertRaises(ForbiddenError) as ctx:
            list(backend.stream_chat("hi", model="opencode/pulse-alpha-free", timeout=5.0))
        self.assertIn("pulse-alpha-free", str(ctx.exception))

    def test_stream_chat_falls_back_to_cli_when_acp_fails(self) -> None:
        acp = MagicMock()
        acp.is_alive.return_value = True

        def boom(*a, **k):
            raise BridgeError("ACP channel died")
            yield  # pragma: no cover

        acp.stream_prompt.side_effect = boom
        backend = OpencodeBackend(binary_path="/usr/bin/opencode", acp_client=acp)

        events = [
            json.dumps({"type": "text", "part": {"type": "text", "text": "CLI-OK"}}),
        ]
        proc = MagicMock()
        proc.stdout = iter((e + "\n") for e in events)
        proc.poll.return_value = 0
        proc.returncode = 0
        proc.stderr = MagicMock()
        proc.stderr.read.return_value = b""
        with patch("bridge.opencode_backend.subprocess.Popen", return_value=proc) as popen:
            out = "".join(backend.stream_chat("hi", model="opencode/beam-free", timeout=5.0))
        self.assertEqual(out, "CLI-OK")
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[:2], ["/usr/bin/opencode", "run"])
        self.assertIn("--format", cmd)
        self.assertIn("json", cmd)
        self.assertIn("--pure", cmd)
        idx = cmd.index("-m")
        self.assertEqual(cmd[idx + 1], "opencode/beam-free")

    def test_cli_region_error_maps_to_forbidden_with_model_name(self) -> None:
        backend = OpencodeBackend(binary_path="/usr/bin/opencode", use_acp=False)
        err_event = json.dumps({
            "type": "error",
            "error": {"name": "APIError", "data": {
                "message": "This model is not available in your country", "statusCode": 403}},
        })
        proc = MagicMock()
        proc.stdout = iter([err_event + "\n"])
        proc.poll.return_value = 1
        proc.returncode = 1
        proc.stderr = MagicMock()
        proc.stderr.read.return_value = b""
        with patch("bridge.opencode_backend.subprocess.Popen", return_value=proc):
            with self.assertRaises(ForbiddenError) as ctx:
                list(backend.stream_chat("hi", model="opencode/pulse-alpha-free", timeout=5.0))
        self.assertIn("pulse-alpha-free", str(ctx.exception))
        self.assertIn("region", str(ctx.exception).lower())

    def test_cli_auth_error_maps_to_authentication_error(self) -> None:
        backend = OpencodeBackend(binary_path="/usr/bin/opencode", use_acp=False)
        err_event = json.dumps({
            "type": "error",
            "error": {"name": "APIError", "data": {
                "message": "Authentication required: provider authentication required"}},
        })
        proc = MagicMock()
        proc.stdout = iter([err_event + "\n"])
        proc.poll.return_value = 1
        proc.returncode = 1
        proc.stderr = MagicMock()
        proc.stderr.read.return_value = b""
        with patch("bridge.opencode_backend.subprocess.Popen", return_value=proc):
            with self.assertRaises(AuthenticationError):
                list(backend.stream_chat("hi", model="opencode/beam-free", timeout=5.0))

    def test_cli_binary_missing_raises_bridge_error(self) -> None:
        backend = OpencodeBackend(binary_path="/no/such/opencode", use_acp=False)
        with patch("bridge.opencode_backend.subprocess.Popen", side_effect=FileNotFoundError()):
            with self.assertRaises(BridgeError) as ctx:
                list(backend.stream_chat("hi", model="opencode/beam-free", timeout=5.0))
        self.assertIn("opencode", str(ctx.exception).lower())

    def test_generate_chat_collects_stream(self) -> None:
        acp = MagicMock()
        acp.is_alive.return_value = True
        acp.stream_prompt.return_value = iter(["a", "b", "c"])
        backend = OpencodeBackend(binary_path="/usr/bin/opencode", acp_client=acp)
        self.assertEqual(backend.generate_chat("hi", model="opencode/beam-free", timeout=5.0), "abc")


class TestBackendWarmup(unittest.TestCase):
    """Warmup must be non-blocking and safe when ACP is disabled."""

    def test_warmup_disabled_is_noop(self) -> None:
        backend = OpencodeBackend(binary_path="/usr/bin/opencode", use_acp=False)
        backend.warmup()  # must not raise nor spawn
        self.assertIsNone(backend._acp_client)


if __name__ == "__main__":
    unittest.main()
