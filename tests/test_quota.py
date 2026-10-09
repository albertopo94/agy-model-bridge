"""Unit tests for Antigravity quota tracking and provider architecture."""

import json
from pathlib import Path
import subprocess
import threading
import time
import unittest
from unittest.mock import MagicMock

from bridge.quota import (
    AgyCliQuotaProvider,
    QuotaProvider,
    format_reset_countdown,
    parse_cli_version,
    parse_usage_stdout,
    stdout_shows_model_turn,
)

SAMPLE_REAL_AGY_STDOUT = """
{"conversation_id":"","status":"SUCCESS","response":"Gemini Models\\tWeekly Limit Remaining\\t29%\\t2026-10-14T05:02:23Z\\nGemini Models\\tFive Hour Limit Remaining\\t59%\\t2026-10-09T22:22:03Z\\nClaude and GPT models\\tWeekly Limit Remaining\\t91%\\t2026-10-14T19:09:28Z\\nClaude and GPT models\\tFive Hour Limit Remaining\\t100%\\t2026-10-10T00:02:09Z\\n","duration_seconds":0,"num_turns":0,"usage":{"input_tokens":0,"output_tokens":0,"thinking_tokens":0,"cache_read_tokens":0,"total_tokens":0},"command":{"name":"usage","data":{"description":"Within each group, models share a weekly limit and a 5-hour limit.","groups":[{"name":"Gemini Models","description":"Models within this group: Gemini Flash, Gemini Pro","buckets":[{"id":"gemini-weekly","name":"Weekly Limit Remaining","description":"You have used some of your weekly limit, it will fully refresh in 4 days, 10 hours.","window":"weekly","remaining_fraction":0.2882622480392456,"reset_time":"2026-10-14T05:02:23Z"},{"id":"gemini-5h","name":"Five Hour Limit Remaining","description":"You have used some of your 5-hour limit, it will fully refresh in 3 hours, 19 minutes.","window":"5h","remaining_fraction":0.5863403081893921,"reset_time":"2026-10-09T22:22:03Z"}]},{"name":"Claude and GPT models","description":"Models within this group: Claude Opus, Claude Sonnet, GPT-OSS","buckets":[{"id":"3p-weekly","name":"Weekly Limit Remaining","description":"You have used some of your weekly limit, it will fully refresh in 5 days.","window":"weekly","remaining_fraction":0.9147520065307617,"reset_time":"2026-10-14T19:09:28Z"},{"id":"3p-5h","name":"Five Hour Limit Remaining","window":"5h","remaining_fraction":1,"reset_time":"2026-10-10T00:02:09Z"}]}]}}}
"""


class TestQuotaParser(unittest.TestCase):
    def test_parse_usage_stdout_real_envelope(self):
        snapshot = parse_usage_stdout(SAMPLE_REAL_AGY_STDOUT, now=1728500000.0)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.status, "ok")
        self.assertIsNone(snapshot.error)
        self.assertIn("share a weekly limit", snapshot.description or "")
        self.assertEqual(len(snapshot.buckets), 4)

        b0 = snapshot.buckets[0]
        self.assertEqual(b0.id, "gemini-weekly")
        self.assertEqual(b0.group, "Gemini Models")
        self.assertEqual(b0.name, "Weekly Limit Remaining")
        self.assertEqual(b0.label, "Gemini Models · Weekly Limit Remaining")
        self.assertEqual(b0.window, "weekly")
        self.assertEqual(b0.used_percent, 71)  # round((1 - 0.2882) * 100)
        self.assertAlmostEqual(b0.remaining_fraction, 0.2882622480392456)
        self.assertIsNotNone(b0.resets_at)

        b3 = snapshot.buckets[3]
        self.assertEqual(b3.id, "3p-5h")
        self.assertEqual(b3.used_percent, 0)
        self.assertEqual(b3.remaining_fraction, 1.0)

        # Check most constrained weekly summary
        self.assertIsNotNone(snapshot.summary)
        self.assertEqual(snapshot.summary["weekly"]["used_percent"], 71)

    def test_parse_usage_stdout_with_log_noise(self):
        noisy_stdout = (
            "2026/10/09 20:00:00 [INFO] Starting language server...\n"
            + SAMPLE_REAL_AGY_STDOUT
            + "\n[DEBUG] Exiting with code 0\n"
        )
        snapshot = parse_usage_stdout(noisy_stdout, now=1728500000.0)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.status, "ok")
        self.assertEqual(len(snapshot.buckets), 4)

    def test_parse_usage_stdout_skips_disabled_buckets(self):
        envelope = {
            "conversation_id": "",
            "status": "SUCCESS",
            "command": {
                "name": "usage",
                "data": {
                    "groups": [
                        {
                            "name": "Gemini Models",
                            "buckets": [
                                {
                                    "id": "gemini-5h",
                                    "name": "Five Hour Limit Remaining",
                                    "remaining_fraction": 0.0,
                                    "disabled": True,
                                    "reset_time": "2026-10-14T05:02:23Z",
                                },
                                {
                                    "id": "gemini-weekly",
                                    "name": "Weekly Limit Remaining",
                                    "remaining_fraction": 0.5,
                                    "disabled": False,
                                    "reset_time": "2026-10-14T05:02:23Z",
                                },
                            ],
                        }
                    ]
                },
            },
        }
        snapshot = parse_usage_stdout(json.dumps(envelope), now=1728500000.0)
        self.assertIsNotNone(snapshot)
        self.assertEqual(len(snapshot.buckets), 1)
        self.assertEqual(snapshot.buckets[0].id, "gemini-weekly")

    def test_parse_usage_stdout_single_bucket_group_label(self):
        envelope = {
            "conversation_id": "",
            "status": "SUCCESS",
            "command": {
                "name": "usage",
                "data": {
                    "groups": [
                        {
                            "name": "Gemini Models",
                            "buckets": [
                                {
                                    "id": "gemini-weekly",
                                    "name": "Weekly Limit Remaining",
                                    "remaining_fraction": 0.5,
                                    "reset_time": "2026-10-14T05:02:23Z",
                                }
                            ],
                        }
                    ]
                },
            },
        }
        snapshot = parse_usage_stdout(json.dumps(envelope), now=1728500000.0)
        self.assertIsNotNone(snapshot)
        # Single bucket in group inherits group name alone
        self.assertEqual(snapshot.buckets[0].label, "Gemini Models")

    def test_parse_usage_stdout_invalid_status_returns_none(self):
        envelope = {"status": "FAILED", "command": {"name": "usage", "data": {}}}
        self.assertIsNone(parse_usage_stdout(json.dumps(envelope)))

    def test_parse_usage_stdout_wrong_command_returns_none(self):
        envelope = {"status": "SUCCESS", "command": {"name": "help", "data": {}}}
        self.assertIsNone(parse_usage_stdout(json.dumps(envelope)))

    def test_parse_usage_stdout_empty_or_non_json_returns_none(self):
        self.assertIsNone(parse_usage_stdout(""))
        self.assertIsNone(parse_usage_stdout("not json"))

    def test_stdout_shows_model_turn(self):
        turn_env_1 = '{"conversation_id": "conv_123", "status": "SUCCESS", "num_turns": 1}'
        turn_env_2 = '{"conversation_id": "", "status": "SUCCESS", "num_turns": 2}'
        no_turn_env = '{"conversation_id": "", "status": "SUCCESS", "num_turns": 0}'

        self.assertTrue(stdout_shows_model_turn(turn_env_1))
        self.assertTrue(stdout_shows_model_turn(turn_env_2))
        self.assertFalse(stdout_shows_model_turn(no_turn_env))
        self.assertFalse(stdout_shows_model_turn(SAMPLE_REAL_AGY_STDOUT))

    def test_parse_cli_version(self):
        self.assertEqual(parse_cli_version("Antigravity CLI 1.2.0"), (1, 2, 0))
        self.assertEqual(parse_cli_version("agy version 1.1.11-beta"), (1, 1, 11))
        self.assertEqual(parse_cli_version("1.0.0"), (1, 0, 0))
        self.assertIsNone(parse_cli_version("no version here"))

    def test_format_reset_countdown(self):
        self.assertEqual(format_reset_countdown(380000), "4d 9h")
        self.assertEqual(format_reset_countdown(12500), "3h 28m")
        self.assertEqual(format_reset_countdown(1500), "25m")
        self.assertEqual(format_reset_countdown(30), "now")
        self.assertEqual(format_reset_countdown(0), "now")
        self.assertEqual(format_reset_countdown(-10), "now")


class TestAgyCliQuotaProvider(unittest.TestCase):
    def test_isinstance_quota_provider(self):
        provider = AgyCliQuotaProvider()
        self.assertIsInstance(provider, QuotaProvider)

    def test_missing_binary_returns_unavailable(self):
        provider = AgyCliQuotaProvider(
            which=lambda cmd: None,
            fallback_paths=[],
        )
        snapshot = provider.fetch()
        self.assertEqual(snapshot.status, "unavailable")
        self.assertIn("not found", snapshot.error or "")

    def test_fallback_path_resolution(self):
        custom_bin = Path("/tmp/mock_agy_bin")
        mock_runner = MagicMock()
        mock_runner.side_effect = [
            # version probe
            MagicMock(returncode=0, stdout="Antigravity CLI 1.2.11\n", stderr=""),
            # usage call
            MagicMock(returncode=0, stdout=SAMPLE_REAL_AGY_STDOUT, stderr=""),
        ]

        provider = AgyCliQuotaProvider(
            which=lambda cmd: None,
            fallback_paths=[custom_bin],
            is_file_fn=lambda p: p == custom_bin,
            is_executable_fn=lambda p: p == custom_bin,
            runner=mock_runner,
        )
        snapshot = provider.fetch()
        self.assertEqual(snapshot.status, "ok")
        self.assertEqual(len(snapshot.buckets), 4)
        # Check command path was the fallback
        self.assertEqual(mock_runner.call_args_list[0][0][0][0], str(custom_bin))

    def test_old_version_blocks_usage_and_returns_unavailable(self):
        mock_runner = MagicMock()
        mock_runner.return_value = MagicMock(returncode=0, stdout="Antigravity CLI 1.0.9\n", stderr="")

        provider = AgyCliQuotaProvider(
            which=lambda cmd: "/bin/agy",
            runner=mock_runner,
        )
        snapshot = provider.fetch()
        self.assertEqual(snapshot.status, "unavailable")
        self.assertIn("1.1.11 or newer", snapshot.error or "")
        # Verified: Only the version check was run; usage was NEVER called!
        self.assertEqual(mock_runner.call_count, 1)

    def test_ttl_cache_returns_cached_snapshot_without_spawning(self):
        mock_runner = MagicMock()
        mock_runner.side_effect = [
            MagicMock(returncode=0, stdout="Antigravity CLI 1.2.11\n", stderr=""),
            MagicMock(returncode=0, stdout=SAMPLE_REAL_AGY_STDOUT, stderr=""),
        ]
        clock = 1000.0

        provider = AgyCliQuotaProvider(
            which=lambda cmd: "/bin/agy",
            runner=mock_runner,
            clock=lambda: clock,
            ttl_seconds=60.0,
        )

        res1 = provider.fetch()
        self.assertEqual(res1.status, "ok")
        self.assertEqual(mock_runner.call_count, 2)

        # Call again within TTL
        clock = 1030.0
        res2 = provider.fetch()
        self.assertEqual(res2.status, "ok")
        self.assertEqual(mock_runner.call_count, 2)  # Zero additional calls!

        # Force refresh bypasses TTL
        mock_runner.side_effect = [
            MagicMock(returncode=0, stdout="Antigravity CLI 1.2.11\n", stderr=""),
            MagicMock(returncode=0, stdout=SAMPLE_REAL_AGY_STDOUT, stderr=""),
        ]
        res3 = provider.fetch(force=True)
        self.assertEqual(res3.status, "ok")
        self.assertEqual(mock_runner.call_count, 4)

    def test_model_turn_latches_provider_permanently(self):
        mock_runner = MagicMock()
        mock_runner.side_effect = [
            MagicMock(returncode=0, stdout="Antigravity CLI 1.2.11\n", stderr=""),
            # Prompt returned conversation_id and num_turns: 1!
            MagicMock(
                returncode=0,
                stdout='{"conversation_id": "leak_123", "status": "SUCCESS", "num_turns": 1}\n',
                stderr="",
            ),
        ]

        provider = AgyCliQuotaProvider(
            which=lambda cmd: "/bin/agy",
            runner=mock_runner,
        )
        res1 = provider.fetch()
        self.assertEqual(res1.status, "unavailable")
        self.assertIn("spent quota", res1.error or "")

        # Second fetch should be latched and make ZERO subprocess calls!
        res2 = provider.fetch(force=True)
        self.assertEqual(res2.status, "unavailable")
        self.assertEqual(mock_runner.call_count, 2)

    def test_signed_out_classification(self):
        mock_runner = MagicMock()
        mock_runner.side_effect = [
            MagicMock(returncode=0, stdout="Antigravity CLI 1.2.11\n", stderr=""),
            MagicMock(returncode=1, stdout="", stderr="Error: not logged into antigravity"),
        ]

        provider = AgyCliQuotaProvider(
            which=lambda cmd: "/bin/agy",
            runner=mock_runner,
        )
        snapshot = provider.fetch()
        self.assertEqual(snapshot.status, "unavailable")
        self.assertIn("Sign in with `agy`", snapshot.error or "")

    def test_stale_on_error_preserves_previous_buckets(self):
        mock_runner = MagicMock()
        mock_runner.side_effect = [
            # first fetch OK
            MagicMock(returncode=0, stdout="Antigravity CLI 1.2.11\n", stderr=""),
            MagicMock(returncode=0, stdout=SAMPLE_REAL_AGY_STDOUT, stderr=""),
            # second fetch fails with timeout
            MagicMock(returncode=0, stdout="Antigravity CLI 1.2.11\n", stderr=""),
            subprocess.TimeoutExpired(cmd=["agy"], timeout=20.0),
        ]
        clock = 1000.0

        provider = AgyCliQuotaProvider(
            which=lambda cmd: "/bin/agy",
            runner=mock_runner,
            clock=lambda: clock,
            ttl_seconds=60.0,
        )

        res1 = provider.fetch()
        self.assertEqual(res1.status, "ok")
        self.assertIsNone(res1.error)

        clock = 1100.0  # past TTL
        res2 = provider.fetch()
        # Stale buckets preserved with status 'ok' and warning in error
        self.assertEqual(res2.status, "ok")
        self.assertEqual(len(res2.buckets), 4)
        self.assertIn("timed out", res2.error or "")

    def test_single_flight_concurrent_fetch(self):
        mock_runner = MagicMock()
        calls = []

        def slow_runner(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("cmd")
            calls.append(cmd)
            time.sleep(0.05)
            if "--version" in cmd:
                return MagicMock(returncode=0, stdout="Antigravity CLI 1.2.11\n", stderr="")
            return MagicMock(returncode=0, stdout=SAMPLE_REAL_AGY_STDOUT, stderr="")

        mock_runner.side_effect = slow_runner
        provider = AgyCliQuotaProvider(
            which=lambda cmd: "/bin/agy",
            runner=mock_runner,
            ttl_seconds=60.0,
        )

        threads = []
        results = [None, None]

        def worker(idx):
            results[idx] = provider.fetch()

        for i in range(2):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(results[0].status, "ok")
        self.assertEqual(results[1].status, "ok")
        # Exactly 1 version check + 1 usage call despite 2 concurrent threads!
        self.assertEqual(len(calls), 2)

    def test_never_adds_disable_slash_commands(self):
        mock_runner = MagicMock()
        mock_runner.side_effect = [
            MagicMock(returncode=0, stdout="Antigravity CLI 1.2.11\n", stderr=""),
            MagicMock(returncode=0, stdout=SAMPLE_REAL_AGY_STDOUT, stderr=""),
        ]

        provider = AgyCliQuotaProvider(
            which=lambda cmd: "/bin/agy",
            runner=mock_runner,
        )
        provider.fetch()
        usage_cmd = mock_runner.call_args_list[1][0][0]
        self.assertNotIn("--disable-slash-commands", usage_cmd)
        self.assertIn("-p", usage_cmd)
        self.assertIn("/usage", usage_cmd)


if __name__ == "__main__":
    unittest.main()
