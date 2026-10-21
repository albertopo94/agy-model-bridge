"""Unit tests for bridge/cli/ modules."""

import io
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

import tests  # noqa: F401

from bridge.cli.daemon import (
    handle_dashboard,
    handle_restart,
    handle_start,
    handle_status,
    handle_stop,
)
from bridge.cli.lifecycle import (
    handle_uninstall,
    handle_update,
)
from bridge.cli.server import handle_server
from bridge.i18n import t
from bridge.setup.base import ConfigPath
from bridge.cli.setup import (
    handle_restore_cli,
    handle_setup_claude,
    handle_setup_codex,
    handle_setup_cursor,
    handle_setup_gentle_shell,
    handle_setup_hermes,
    handle_setup_openclaw,
    handle_setup_opencode,
    handle_setup_pi,
)


class TestCliDaemonHandlers(unittest.TestCase):
    def test_handle_start_success(self):
        mock_start = MagicMock(return_value={"status": "started", "pid": 1234, "url": "http://127.0.0.1:24980/"})
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = handle_start(["--port", "24980"], prog_base="agy-bridge", start_fn=mock_start)
            self.assertEqual(ret, 0)
            self.assertIn("1234", out.getvalue())

    def test_handle_start_already_running(self):
        mock_start = MagicMock(return_value={"status": "already_running", "pid": 5678, "url": "http://127.0.0.1:24980/"})
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = handle_start([], prog_base="agy-bridge", start_fn=mock_start)
            self.assertEqual(ret, 0)
            self.assertIn("5678", out.getvalue())

    def test_handle_start_error(self):
        mock_start = MagicMock(return_value={"status": "error", "error": "Port conflict"})
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = handle_start([], prog_base="agy-bridge", start_fn=mock_start)
            self.assertEqual(ret, 1)
            self.assertIn("Port conflict", out.getvalue())

    def test_handle_stop_success(self):
        mock_stop = MagicMock(return_value={"status": "stopped", "pid": 1234})
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = handle_stop([], prog_base="agy-bridge", stop_fn=mock_stop)
            self.assertEqual(ret, 0)
            self.assertIn("1234", out.getvalue())

    def test_handle_stop_mismatch(self):
        mock_stop = MagicMock(return_value={"status": "host_mismatch", "error": "Host mismatch"})
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = handle_stop([], prog_base="agy-bridge", stop_fn=mock_stop)
            self.assertEqual(ret, 1)
            self.assertIn("Host mismatch", out.getvalue())

    def test_handle_stop_not_running(self):
        mock_stop = MagicMock(return_value={"status": "not_running"})
        with patch("sys.stdout", new=io.StringIO()):
            ret = handle_stop([], prog_base="agy-bridge", stop_fn=mock_stop)
            self.assertEqual(ret, 0)

    def test_handle_restart_success(self):
        mock_restart = MagicMock(return_value={"status": "started", "pid": 4321, "url": "http://127.0.0.1:24980/", "opened_browser": False})
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = handle_restart(["--no-open"], prog_base="agy-bridge", restart_fn=mock_restart)
            self.assertEqual(ret, 0)
            self.assertIn("4321", out.getvalue())

    def test_handle_restart_error(self):
        mock_restart = MagicMock(return_value={"status": "error", "error": "Restart failed"})
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = handle_restart([], prog_base="agy-bridge", restart_fn=mock_restart)
            self.assertEqual(ret, 1)
            self.assertIn("Restart failed", out.getvalue())

    def test_handle_status_running(self):
        mock_status = MagicMock(return_value={"running": True, "pid": 1234, "url": "http://127.0.0.1:24980/", "models_count": 8})
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = handle_status([], prog_base="agy-bridge", status_fn=mock_status)
            self.assertEqual(ret, 0)
            self.assertIn("1234", out.getvalue())

    def test_handle_status_stopped(self):
        mock_status = MagicMock(return_value={"running": False, "url": "http://127.0.0.1:24980/"})
        with patch("sys.stdout", new=io.StringIO()):
            ret = handle_status([], prog_base="agy-bridge", status_fn=mock_status)
            self.assertEqual(ret, 0)

    def test_handle_dashboard(self):
        mock_open = MagicMock()
        mock_status = MagicMock(return_value={"running": True, "url": "http://127.0.0.1:24980/"})
        with patch("sys.stdout", new=io.StringIO()):
            ret = handle_dashboard([], prog_base="agy-bridge", subcmd="dashboard", open_fn=mock_open, status_fn=mock_status)
            self.assertEqual(ret, 0)
            mock_open.assert_called_once_with(port=24980, host="127.0.0.1")


class TestCliLifecycleHandlers(unittest.TestCase):
    def test_handle_update_updated(self):
        mock_update = MagicMock(return_value={"status": "updated", "version": "0.28.4", "restarted_daemon": True})
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = handle_update([], prog_base="agy-bridge", subcmd="update", update_fn=mock_update)
            self.assertEqual(ret, 0)
            self.assertIn("0.28.4", out.getvalue())

    def test_handle_update_already_up_to_date(self):
        mock_update = MagicMock(return_value={"status": "already_up_to_date", "version": "0.28.4"})
        with patch("sys.stdout", new=io.StringIO()):
            ret = handle_update([], prog_base="agy-bridge", subcmd="update", update_fn=mock_update)
            self.assertEqual(ret, 0)

    def test_handle_update_error(self):
        mock_update = MagicMock(return_value={"status": "error", "message": "Failed to pull"})
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = handle_update([], prog_base="agy-bridge", subcmd="update", update_fn=mock_update)
            self.assertEqual(ret, 1)
            self.assertIn("Failed to pull", out.getvalue())

    def test_handle_uninstall_with_yes(self):
        mock_uninstall = MagicMock(return_value={"daemon_stopped": True, "binaries_removed": ["/bin/agy-bridge"]})
        with patch("sys.stdout", new=io.StringIO()):
            ret = handle_uninstall(["--yes"], prog_base="agy-bridge", uninstall_fn=mock_uninstall)
            self.assertEqual(ret, 0)
            mock_uninstall.assert_called_once_with(restore_configs=True, purge_backups=False)

    def test_handle_uninstall_cancelled(self):
        mock_uninstall = MagicMock()
        with patch("builtins.input", return_value="n"), patch("sys.stdout", new=io.StringIO()):
            ret = handle_uninstall([], prog_base="agy-bridge", uninstall_fn=mock_uninstall)
            self.assertEqual(ret, 0)
            mock_uninstall.assert_not_called()


class TestCliSetupHandlers(unittest.TestCase):
    def test_handle_setup_claude(self):
        mock_setup = MagicMock(return_value=Path("/tmp/settings.json"))
        with patch("sys.stdout", new=io.StringIO()):
            ret = handle_setup_claude(["--port", "24980", "--provider", "cursor"], prog_base="agy-bridge", setup_fn=mock_setup)
            self.assertEqual(ret, 0)
            mock_setup.assert_called_once()
            self.assertEqual(mock_setup.call_args.kwargs.get("provider"), "cursor")

    def test_handle_setup_codex(self):
        mock_setup = MagicMock(return_value=Path("/tmp/config.toml"))
        with patch("sys.stdout", new=io.StringIO()):
            ret = handle_setup_codex([], prog_base="agy-bridge", setup_fn=mock_setup)
            self.assertEqual(ret, 0)
            mock_setup.assert_called_once()

    def test_handle_setup_hermes(self):
        mock_setup = MagicMock(return_value=Path("/tmp/config.yaml"))
        with patch("sys.stdout", new=io.StringIO()):
            ret = handle_setup_hermes([], prog_base="agy-bridge", setup_fn=mock_setup)
            self.assertEqual(ret, 0)
            mock_setup.assert_called_once()

    def test_handle_setup_opencode(self):
        mock_setup = MagicMock(return_value=Path("/tmp/opencode.json"))
        with patch("sys.stdout", new=io.StringIO()):
            ret = handle_setup_opencode([], prog_base="agy-bridge", setup_fn=mock_setup)
            self.assertEqual(ret, 0)
            mock_setup.assert_called_once()

    def test_handle_setup_openclaw(self):
        mock_setup = MagicMock(return_value=Path("/tmp/openclaw.json"))
        with patch("sys.stdout", new=io.StringIO()):
            ret = handle_setup_openclaw([], prog_base="agy-bridge", setup_fn=mock_setup)
            self.assertEqual(ret, 0)
            mock_setup.assert_called_once()

    def test_handle_setup_cursor(self):
        mock_setup = MagicMock(return_value={"url": "http://127.0.0.1:24980/v1", "apiKey": "key", "model": "gemini-3.8-flash-high"})
        with patch("sys.stdout", new=io.StringIO()):
            ret = handle_setup_cursor([], prog_base="agy-bridge", setup_fn=mock_setup)
            self.assertEqual(ret, 0)
            mock_setup.assert_called_once()

    def test_handle_setup_pi(self):
        mock_setup = MagicMock(return_value=Path("/tmp/models.json"))
        with patch("sys.stdout", new=io.StringIO()):
            ret = handle_setup_pi(["--provider", "all"], prog_base="agy-bridge", setup_fn=mock_setup)
            self.assertEqual(ret, 0)
            mock_setup.assert_called_once()
            self.assertEqual(mock_setup.call_args.kwargs.get("provider"), "all")

    def test_handle_setup_gentle_shell(self):
        mock_setup = MagicMock(return_value=Path("/tmp/models.json"))
        with patch("sys.stdout", new=io.StringIO()):
            ret = handle_setup_gentle_shell(["--provider", "cursor"], prog_base="agy-bridge", subcmd="setup-gentle", setup_fn=mock_setup)
            self.assertEqual(ret, 0)
            mock_setup.assert_called_once()
            self.assertEqual(mock_setup.call_args.kwargs.get("provider"), "cursor")

    # --- Antigravity availability check in setup handlers ---

    def _availability_cases(self):
        return {
            "opencode": (handle_setup_opencode, [], "/tmp/opencode.json"),
            "openclaw": (handle_setup_openclaw, [], "/tmp/openclaw.json"),
            "pi": (handle_setup_pi, [], "/tmp/models.json"),
            "gentle": (handle_setup_gentle_shell, [], "/tmp/models.json"),
        }

    def _call(self, name, handler, extra, ret):
        mock_setup = MagicMock(return_value=ret)
        kwargs = {"prog_base": "agy-bridge", "setup_fn": mock_setup}
        if name == "gentle":
            kwargs["subcmd"] = "setup-gentle"
        with patch("sys.stdout", new=io.StringIO()) as out:
            rc = handler(extra, **kwargs)
        return rc, mock_setup, out.getvalue()

    def test_availability_catalog_reaches_setup_for_agy_provider(self):
        catalog = {"gemini-4-argon-high"}
        for name, (handler, extra, path) in self._availability_cases().items():
            with self.subTest(client=name), patch(
                "bridge.cli.setup.fetch_agy_available_models", return_value=catalog
            ):
                rc, mock_setup, _ = self._call(name, handler, extra, Path(path))
                self.assertEqual(rc, 0)
                self.assertEqual(mock_setup.call_args.kwargs.get("available_models"), catalog)

    def test_no_check_availability_skips_catalog_query(self):
        for name, (handler, extra, path) in self._availability_cases().items():
            with self.subTest(client=name), patch(
                "bridge.cli.setup.fetch_agy_available_models"
            ) as fetch:
                rc, mock_setup, _ = self._call(
                    name, handler, extra + ["--no-check-availability"], Path(path)
                )
                self.assertEqual(rc, 0)
                fetch.assert_not_called()
                self.assertIsNone(mock_setup.call_args.kwargs.get("available_models"))

    def test_cursor_provider_never_queries_catalog(self):
        for name, (handler, extra, path) in self._availability_cases().items():
            with self.subTest(client=name), patch(
                "bridge.cli.setup.fetch_agy_available_models"
            ) as fetch:
                rc, mock_setup, _ = self._call(
                    name, handler, extra + ["--provider", "cursor"], Path(path)
                )
                self.assertEqual(rc, 0)
                fetch.assert_not_called()

    def test_skipped_models_notice_is_printed(self):
        ret = ConfigPath("/tmp/models.json")
        ret.skipped_models = ["gemini-4-argon-low", "claude-sonnet-5-5-high"]
        for name, (handler, extra, _) in self._availability_cases().items():
            with self.subTest(client=name), patch(
                "bridge.cli.setup.fetch_agy_available_models", return_value=set()
            ):
                _, _, out = self._call(name, handler, extra, ret)
                self.assertIn("gemini-4-argon-low", out)
                self.assertIn("claude-sonnet-5-5-high", out)

    def test_unverified_notice_when_catalog_unavailable(self):
        for name, (handler, extra, path) in self._availability_cases().items():
            with self.subTest(client=name), patch(
                "bridge.cli.setup.fetch_agy_available_models", return_value=None
            ):
                _, _, out = self._call(name, handler, extra, Path(path))
                self.assertIn(t("setup_availability_unverified"), out)

    def test_no_notices_when_check_skipped_and_nothing_skipped(self):
        for name, (handler, extra, path) in self._availability_cases().items():
            with self.subTest(client=name), patch(
                "bridge.cli.setup.fetch_agy_available_models"
            ):
                _, _, out = self._call(
                    name, handler, extra + ["--no-check-availability"], Path(path)
                )
                self.assertNotIn(t("setup_availability_unverified"), out)

    def test_handle_restore_cli_no_backups(self):
        with patch("bridge.cli.setup.list_backups", return_value=[]), patch("sys.stdout", new=io.StringIO()):
            ret = handle_restore_cli("Claude Code", Path("/tmp/settings.json"), [], "agy-bridge restore-claude")
            self.assertEqual(ret, 1)

    def test_handle_restore_cli_factory_reset_flag(self):
        mock_cfg = MagicMock()
        mock_cfg.display_name = "Gentle Shell"
        mock_cfg.name = "gentle-shell"
        mock_cfg.factory_reset.return_value = True
        with patch("bridge.cli.setup.list_configurators", return_value=[mock_cfg]), patch("sys.stdout", new=io.StringIO()):
            ret = handle_restore_cli("Gentle Shell", Path("/tmp/models.json"), ["--factory-reset"], "agy-bridge restore-gentle-shell")
            self.assertEqual(ret, 0)
            mock_cfg.factory_reset.assert_called_once()

    def test_handle_restore_cli_interactive_choice_zero(self):
        mock_cfg = MagicMock()
        mock_cfg.display_name = "Gentle Shell"
        mock_cfg.name = "gentle-shell"
        mock_cfg.factory_reset.return_value = True
        fake_backup = Path("/tmp/models.json.backup-1")
        with (
            patch("bridge.cli.setup.list_configurators", return_value=[mock_cfg]),
            patch("bridge.cli.setup.list_backups", return_value=[fake_backup]),
            patch("bridge.cli.setup.describe_backup", return_value="FreeLLMAPI"),
            patch("builtins.input", return_value="0"),
            patch("sys.stdout", new=io.StringIO()),
        ):
            ret = handle_restore_cli("Gentle Shell", Path("/tmp/models.json"), [], "agy-bridge restore-gentle-shell")
            self.assertEqual(ret, 0)
            mock_cfg.factory_reset.assert_called_once()


class TestCliServerHandler(unittest.TestCase):
    def test_handle_server_rejects_no_auth_on_remote_host(self):
        mock_run = MagicMock()
        with patch("sys.stdout", new=io.StringIO()) as out:
            ret = handle_server(["--host", "192.168.1.100", "--no-auth"], prog_base="agy-bridge", run_server_fn=mock_run)
            self.assertEqual(ret, 1)
            self.assertIn("Refusing to disable authentication", out.getvalue())
            mock_run.assert_not_called()

    def test_handle_server_runs_on_loopback(self):
        mock_run = MagicMock()
        ret = handle_server(["--host", "127.0.0.1", "--port", "24980"], prog_base="agy-bridge", run_server_fn=mock_run)
        self.assertEqual(ret, 0)
        mock_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
