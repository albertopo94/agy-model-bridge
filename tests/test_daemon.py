"""Tests for daemon lifecycle and process management utilities."""

import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from bridge.daemon import (
    check_server_healthy,
    get_daemon_status,
    is_bridge_process,
    is_pid_alive,
    open_dashboard,
    read_daemon_info,
    read_pid,
    remove_daemon_info,
    remove_pid,
    start_daemon,
    stop_daemon,
    write_daemon_info,
    write_pid,
)


class TestPidManagement(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.pid_file = self.dir_path / "bridge.pid"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_write_and_read_pid(self):
        test_pid = 12345
        write_pid(test_pid, pid_file=self.pid_file)

        self.assertTrue(self.pid_file.exists())
        file_mode = stat.S_IMODE(self.pid_file.stat().st_mode)
        self.assertEqual(file_mode, 0o600)

        read_val = read_pid(pid_file=self.pid_file)
        self.assertEqual(read_val, test_pid)

    def test_read_pid_when_missing(self):
        self.assertFalse(self.pid_file.exists())
        self.assertIsNone(read_pid(pid_file=self.pid_file))

    def test_read_pid_invalid_content(self):
        self.pid_file.write_text("invalid_pid_string\n", encoding="utf-8")
        self.assertIsNone(read_pid(pid_file=self.pid_file))

    def test_remove_pid_existing_and_missing(self):
        write_pid(999, pid_file=self.pid_file)
        self.assertTrue(self.pid_file.exists())

        remove_pid(pid_file=self.pid_file)
        self.assertFalse(self.pid_file.exists())

        # Calling remove on non-existent file should be a no-op without error
        remove_pid(pid_file=self.pid_file)

    def test_is_pid_alive_active_current_process(self):
        current_pid = os.getpid()
        self.assertTrue(is_pid_alive(current_pid))

    def test_is_pid_alive_dead_pid(self):
        # PID 9999999 is virtually never a valid active process
        self.assertFalse(is_pid_alive(9999999))

    def test_is_pid_alive_none_or_negative(self):
        self.assertFalse(is_pid_alive(None))
        self.assertFalse(is_pid_alive(-1))
        self.assertFalse(is_pid_alive(0))


class TestDaemonLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.pid_file = self.dir_path / "bridge.pid"
        self.log_file = self.dir_path / "bridge.log"

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("bridge.daemon.webbrowser.open")
    @patch("bridge.daemon.check_server_healthy", return_value=True)
    @patch("bridge.daemon.subprocess.Popen")
    def test_start_daemon_success(self, mock_popen, mock_health, mock_browser):
        mock_proc = MagicMock()
        mock_proc.pid = 44444
        mock_popen.return_value = mock_proc

        res = start_daemon(
            port=24980,
            host="127.0.0.1",
            no_open=False,
            pid_file=self.pid_file,
            log_file=self.log_file,
        )

        self.assertEqual(res["status"], "started")
        self.assertEqual(res["pid"], 44444)
        self.assertEqual(res["port"], 24980)
        self.assertEqual(res["url"], "http://127.0.0.1:24980/")
        self.assertTrue(res["opened_browser"])

        self.assertEqual(read_pid(self.pid_file), 44444)
        mock_browser.assert_called_once_with("http://127.0.0.1:24980/")
        mock_popen.assert_called_once()
        cmd_args = mock_popen.call_args[0][0]
        self.assertIn("-m", cmd_args)
        self.assertIn("bridge", cmd_args)
        self.assertIn("--port", cmd_args)
        self.assertIn("24980", cmd_args)

    @patch("bridge.daemon.webbrowser.open")
    @patch("bridge.daemon.check_server_healthy", return_value=True)
    @patch("bridge.daemon.subprocess.Popen")
    def test_start_daemon_no_open(self, mock_popen, mock_health, mock_browser):
        mock_proc = MagicMock()
        mock_proc.pid = 44445
        mock_popen.return_value = mock_proc

        res = start_daemon(
            port=24980,
            host="127.0.0.1",
            no_open=True,
            pid_file=self.pid_file,
            log_file=self.log_file,
        )

        self.assertEqual(res["status"], "started")
        self.assertFalse(res["opened_browser"])
        mock_browser.assert_not_called()
        self.assertEqual(mock_popen.call_args[1].get("cwd"), str(self.pid_file.parent))

    @patch("bridge.daemon.webbrowser.open")
    @patch("bridge.daemon.check_server_healthy", return_value=True)
    @patch("bridge.daemon.subprocess.Popen")
    def test_start_daemon_with_api_key_persists_key_file_without_argv_or_env(self, mock_popen, mock_health, mock_browser):
        mock_proc = MagicMock()
        mock_proc.pid = 44447
        mock_popen.return_value = mock_proc

        res = start_daemon(
            port=24980,
            host="127.0.0.1",
            api_key="secret-token-xyz-123",
            no_open=True,
            pid_file=self.pid_file,
            log_file=self.log_file,
        )

        self.assertEqual(res["status"], "started")
        mock_popen.assert_called_once()
        cmd_args = mock_popen.call_args[0][0]
        # Must NEVER leak secret API key in argv
        self.assertNotIn("--api-key", cmd_args)
        self.assertNotIn("secret-token-xyz-123", cmd_args)

        # Must NEVER leak secret API key in child environment (zero environ exposure)
        call_kwargs = mock_popen.call_args[1]
        self.assertIn("env", call_kwargs)
        self.assertNotIn("AGY_API_KEY", call_kwargs["env"])
        self.assertEqual(call_kwargs.get("cwd"), str(self.pid_file.parent))

        # Must persist key file in daemon directory with 0o600 permissions
        key_file = self.pid_file.parent / "api_key"
        self.assertTrue(key_file.exists())
        self.assertEqual(stat.S_IMODE(key_file.stat().st_mode), 0o600)
        self.assertEqual(key_file.read_text(encoding="utf-8").strip(), "secret-token-xyz-123")

    @patch("bridge.daemon.webbrowser.open")
    @patch("bridge.daemon.check_server_healthy", return_value=True)
    @patch("bridge.daemon.subprocess.Popen")
    def test_start_daemon_strips_ambient_agy_api_key_from_env(self, mock_popen, mock_health, mock_browser):
        mock_proc = MagicMock()
        mock_proc.pid = 44448
        mock_popen.return_value = mock_proc

        with patch.dict(os.environ, {"AGY_API_KEY": "leaked-ambient-key"}):
            res = start_daemon(
                port=24980,
                host="127.0.0.1",
                no_open=True,
                pid_file=self.pid_file,
                log_file=self.log_file,
            )

        self.assertEqual(res["status"], "started")
        call_kwargs = mock_popen.call_args[1]
        self.assertNotIn("AGY_API_KEY", call_kwargs["env"])

        key_file = self.pid_file.parent / "api_key"
        self.assertTrue(key_file.exists())
        self.assertEqual(stat.S_IMODE(key_file.stat().st_mode), 0o600)
        self.assertEqual(key_file.read_text(encoding="utf-8").strip(), "leaked-ambient-key")

    @patch("bridge.daemon.check_server_healthy", return_value=True)
    @patch("bridge.daemon.subprocess.Popen")
    def test_start_daemon_already_running(self, mock_popen, mock_health):
        write_pid(33333, pid_file=self.pid_file)

        with patch("bridge.daemon.is_pid_alive", return_value=True), patch("bridge.daemon.is_bridge_process", return_value=True):
            res = start_daemon(
                port=24980,
                host="127.0.0.1",
                pid_file=self.pid_file,
                log_file=self.log_file,
            )

        self.assertEqual(res["status"], "already_running")
        self.assertEqual(res["pid"], 33333)
        mock_popen.assert_not_called()

    @patch("bridge.daemon.check_server_healthy", return_value=False)
    @patch("bridge.daemon.subprocess.Popen")
    def test_start_daemon_health_timeout(self, mock_popen, mock_health):
        mock_proc = MagicMock()
        mock_proc.pid = 44446
        mock_popen.return_value = mock_proc

        res = start_daemon(
            port=24980,
            host="127.0.0.1",
            pid_file=self.pid_file,
            log_file=self.log_file,
            health_timeout=0.1,
        )

        self.assertEqual(res["status"], "error")
        self.assertIn("Timeout", res["error"])
        mock_proc.terminate.assert_called_once()
        self.assertIsNone(read_pid(self.pid_file))

    @patch("bridge.daemon.os.kill")
    def test_stop_daemon_success(self, mock_kill):
        write_pid(55555, pid_file=self.pid_file)

        # First call is alive (in loop), second call is dead
        with patch("bridge.daemon.is_pid_alive", side_effect=[True, False]), patch("bridge.daemon.is_bridge_process", return_value=True):
            res = stop_daemon(pid_file=self.pid_file)

        self.assertEqual(res["status"], "stopped")
        self.assertEqual(res["pid"], 55555)
        self.assertIsNone(read_pid(self.pid_file))
        mock_kill.assert_called()

    @patch("bridge.daemon.os.kill")
    def test_stop_daemon_reverifies_bridge_process_before_sigkill(self, mock_kill):
        import signal
        write_pid(55556, pid_file=self.pid_file)

        # Process is alive during SIGTERM and during timeout loop.
        # But when timeout expires, is_bridge_process returns False (PID recycled).
        with patch("bridge.daemon.is_pid_alive", return_value=True), \
             patch("bridge.daemon.is_bridge_process", side_effect=[True, False]):
            res = stop_daemon(pid_file=self.pid_file, timeout=0.01)

        self.assertEqual(res["status"], "stopped")
        # SIGTERM was called once at start, but SIGKILL should NOT be called because it is no longer bridge process
        for call_args in mock_kill.call_args_list:
            self.assertNotEqual(call_args[0][1], signal.SIGKILL)

    def test_stop_daemon_not_running(self):
        res = stop_daemon(pid_file=self.pid_file)
        self.assertEqual(res["status"], "not_running")

    @patch("bridge.daemon.fetch_status_json")
    def test_get_daemon_status_running(self, mock_fetch):
        write_pid(55555, pid_file=self.pid_file)
        mock_fetch.return_value = {
            "auth": {"status": "Valid", "email": "test@example.com"},
            "models_count": 27,
        }

        with patch("bridge.daemon.is_pid_alive", return_value=True), patch("bridge.daemon.is_bridge_process", return_value=True):
            status = get_daemon_status(port=24980, host="127.0.0.1", pid_file=self.pid_file)

        self.assertTrue(status["running"])
        self.assertEqual(status["pid"], 55555)
        self.assertEqual(status["models_count"], 27)
        self.assertEqual(status["auth"]["status"], "Valid")
        self.assertEqual(status["url"], "http://127.0.0.1:24980/")

    @patch("bridge.daemon.fetch_status_json", return_value=None)
    def test_get_daemon_status_stopped(self, mock_fetch):
        status = get_daemon_status(port=24980, host="127.0.0.1", pid_file=self.pid_file)
        self.assertFalse(status["running"])
        self.assertIsNone(status["pid"])
        self.assertEqual(status["url"], "http://127.0.0.1:24980/")

    @patch("bridge.daemon.webbrowser.open", return_value=True)
    def test_open_dashboard(self, mock_open):
        res = open_dashboard(port=24980, host="127.0.0.1")
        self.assertTrue(res)
        mock_open.assert_called_once_with("http://127.0.0.1:24980/")


class TestDaemonCLI(unittest.TestCase):
    @patch("bridge.__main__.start_daemon")
    def test_cli_start_dispatches(self, mock_start):
        import io
        from bridge.__main__ import main
        mock_start.return_value = {
            "status": "started",
            "pid": 11111,
            "port": 9090,
            "url": "http://127.0.0.1:9090/",
            "opened_browser": True,
        }
        out = io.StringIO()
        with patch("sys.stdout", out):
            code = main(["start", "--port", "9090", "--no-open"])

        self.assertEqual(code, 0)
        mock_start.assert_called_once_with(
            port=9090,
            host="127.0.0.1",
            no_open=True,
            project=None,
            base_url=None,
            api_key=None,
            no_auth=False,
        )
        output = out.getvalue()
        self.assertIn("11111", output)
        self.assertIn("http://127.0.0.1:9090/", output)

    @patch("bridge.__main__.stop_daemon")
    def test_cli_stop_dispatches(self, mock_stop):
        import io
        from bridge.__main__ import main
        mock_stop.return_value = {"status": "stopped", "pid": 11111}
        out = io.StringIO()
        with patch("sys.stdout", out):
            code = main(["stop"])

        self.assertEqual(code, 0)
        mock_stop.assert_called_once()
        self.assertIn("11111", out.getvalue())

    @patch("bridge.__main__.stop_daemon")
    def test_cli_stop_host_mismatch_exits_with_error(self, mock_stop):
        import io
        from bridge.__main__ import main
        mock_stop.return_value = {
            "status": "host_mismatch",
            "error": "Daemon PID 99992 is running on host 127.0.0.1, not requested host 192.168.1.50.",
        }
        out = io.StringIO()
        with patch("sys.stdout", out):
            code = main(["stop", "--host", "192.168.1.50"])

        self.assertEqual(code, 1)
        mock_stop.assert_called_once_with(port=None, host="192.168.1.50")
        self.assertIn("Error: Daemon PID 99992 is running on host 127.0.0.1, not requested host 192.168.1.50.", out.getvalue())

    @patch("bridge.__main__.get_daemon_status")
    def test_cli_status_dispatches(self, mock_status):
        import io
        from bridge.__main__ import main
        mock_status.return_value = {
            "running": True,
            "pid": 11111,
            "port": 24980,
            "host": "127.0.0.1",
            "url": "http://127.0.0.1:24980/",
            "models_count": 27,
            "auth": {"status": "Valid"},
        }
        out = io.StringIO()
        with patch("sys.stdout", out):
            code = main(["status"])

        self.assertEqual(code, 0)
        output = out.getvalue()
        self.assertTrue("Activo" in output or "Active" in output)
        self.assertIn("11111", output)
        self.assertIn("27", output)

        out_es = io.StringIO()
        with patch("sys.stdout", out_es):
            code_es = main(["status", "--lang", "es"])
        self.assertEqual(code_es, 0)
        self.assertIn("Activo", out_es.getvalue())

        out_en = io.StringIO()
        with patch("sys.stdout", out_en):
            code_en = main(["status", "--lang", "en"])
        self.assertEqual(code_en, 0)
        self.assertIn("Active", out_en.getvalue())

    @patch("bridge.__main__.open_dashboard")
    @patch("bridge.__main__.get_daemon_status")
    def test_cli_dashboard_and_open_dispatches(self, mock_status, mock_open):
        import io
        from bridge.__main__ import main
        mock_status.return_value = {"running": True, "url": "http://127.0.0.1:24980/"}
        mock_open.return_value = True

        out = io.StringIO()
        with patch("sys.stdout", out):
            code1 = main(["dashboard"])
            code2 = main(["open"])

        self.assertEqual(code1, 0)
        self.assertEqual(code2, 0)
        self.assertEqual(mock_open.call_count, 2)

    @patch("bridge.__main__.start_daemon")
    def test_cli_start_with_auth_flags(self, mock_start):
        from bridge.__main__ import main
        mock_start.return_value = {"status": "started", "pid": 11111, "url": "http://127.0.0.1:24980/"}
        main(["start", "--api-key", "my-secret-key"])
        mock_start.assert_called_with(
            port=24980,
            host="127.0.0.1",
            no_open=False,
            project=None,
            base_url=None,
            api_key="my-secret-key",
            no_auth=False,
        )

        main(["start", "--no-auth"])
        mock_start.assert_called_with(
            port=24980,
            host="127.0.0.1",
            no_open=False,
            project=None,
            base_url=None,
            api_key=None,
            no_auth=True,
        )


class TestProcessIdentity(unittest.TestCase):
    def test_is_bridge_process_invalid_pids(self):
        self.assertFalse(is_bridge_process(None))
        self.assertFalse(is_bridge_process(0))
        self.assertFalse(is_bridge_process(-1))

    @patch("subprocess.run")
    def test_is_bridge_process_fails_closed_on_unrelated_python(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="/usr/bin/python3 -m unittest discover -s tests\n")
        self.assertFalse(is_bridge_process(12345))

    @patch("subprocess.run")
    def test_is_bridge_process_fails_closed_on_generic_python_script(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="/usr/bin/python3 /some/other/script.py\n")
        self.assertFalse(is_bridge_process(12345))

    @patch("subprocess.run")
    def test_is_bridge_process_fails_closed_on_ps_error(self, mock_run):
        mock_run.side_effect = OSError("ps binary not found")
        self.assertFalse(is_bridge_process(12345))

    @patch("subprocess.run")
    def test_is_bridge_process_fails_closed_on_non_zero_exit(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        self.assertFalse(is_bridge_process(12345))

    @patch("subprocess.run")
    def test_is_bridge_process_matches_bridge_module(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="/usr/bin/python3 -u -m bridge --port 24980 --host 127.0.0.1\n",
        )
        self.assertTrue(is_bridge_process(12345))

    @patch("subprocess.run")
    def test_is_bridge_process_matches_agy_bridge_binary(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="/usr/local/bin/agy-bridge start\n")
        self.assertTrue(is_bridge_process(12345))

    @patch("subprocess.run")
    def test_is_bridge_process_matches_agy_model_bridge_binary(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="/Users/user/.local/bin/agy-model-bridge start\n")
        self.assertTrue(is_bridge_process(12345))

    @patch("subprocess.run")
    def test_is_bridge_process_rejects_malicious_module_suffix(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="/usr/bin/python3 -m bridge-malicious\n")
        self.assertFalse(is_bridge_process(12345))

    @patch("subprocess.run")
    def test_is_bridge_process_rejects_similar_module_name(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="/usr/bin/python3 -m bridge_helper\n")
        self.assertFalse(is_bridge_process(12345))

    @patch("subprocess.run")
    def test_is_bridge_process_matches_main_script_token(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="/usr/bin/python3 /opt/bridge/__main__.py --port 24980\n")
        self.assertTrue(is_bridge_process(12345))

    @patch("subprocess.run")
    def test_is_bridge_process_matches_relative_main_script(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="python bridge/__main__.py\n")
        self.assertTrue(is_bridge_process(12345))


class TestHealthCheck(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_check_server_healthy_matches_valid_service_identity(self, mock_urlopen):
        resp = MagicMock()
        resp.status = 200
        resp.read.return_value = b'{"status": "ok", "service": "agy-model-bridge", "version": "0.21.1"}'
        resp.__enter__.return_value = resp
        mock_urlopen.return_value = resp

        self.assertTrue(check_server_healthy("127.0.0.1", 24980))

    @patch("urllib.request.urlopen")
    def test_check_server_healthy_rejects_unrelated_service_returning_200(self, mock_urlopen):
        resp = MagicMock()
        resp.status = 200
        resp.read.return_value = b'{"status": "ok"}'
        resp.__enter__.return_value = resp
        mock_urlopen.return_value = resp

        self.assertFalse(check_server_healthy("127.0.0.1", 24980))

    @patch("urllib.request.urlopen")
    def test_check_server_healthy_rejects_other_service_name(self, mock_urlopen):
        resp = MagicMock()
        resp.status = 200
        resp.read.return_value = b'{"status": "ok", "service": "nginx"}'
        resp.__enter__.return_value = resp
        mock_urlopen.return_value = resp

        self.assertFalse(check_server_healthy("127.0.0.1", 24980))

    @patch("urllib.request.urlopen")
    def test_check_server_healthy_rejects_html_or_non_json_200(self, mock_urlopen):
        resp = MagicMock()
        resp.status = 200
        resp.read.return_value = b'<html><body>OK</body></html>'
        resp.__enter__.return_value = resp
        mock_urlopen.return_value = resp

        self.assertFalse(check_server_healthy("127.0.0.1", 24980))


class TestDaemonDescriptorAndPortBinding(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.pid_file = self.dir_path / "bridge.pid"
        self.info_file = self.dir_path / "bridge.json"
        self.log_file = self.dir_path / "bridge.log"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_write_read_remove_daemon_info(self):
        info_data = {
            "pid": 54321,
            "host": "127.0.0.1",
            "port": 24980,
            "service": "agy-model-bridge",
            "version": "0.21.1",
        }
        write_daemon_info(info_data, info_file=self.info_file)
        self.assertTrue(self.info_file.exists())
        mode = stat.S_IMODE(self.info_file.stat().st_mode)
        self.assertEqual(mode, 0o600)

        read_data = read_daemon_info(info_file=self.info_file)
        self.assertIsNotNone(read_data)
        self.assertEqual(read_data["pid"], 54321)
        self.assertEqual(read_data["port"], 24980)
        self.assertEqual(read_data["service"], "agy-model-bridge")

        remove_daemon_info(info_file=self.info_file)
        self.assertFalse(self.info_file.exists())
        self.assertIsNone(read_daemon_info(info_file=self.info_file))

    @patch("bridge.daemon.webbrowser.open")
    @patch("bridge.daemon.check_server_healthy", return_value=True)
    @patch("bridge.daemon.subprocess.Popen")
    def test_start_daemon_persists_daemon_info(self, mock_popen, mock_health, mock_browser):
        mock_proc = MagicMock()
        mock_proc.pid = 65432
        mock_popen.return_value = mock_proc

        res = start_daemon(
            port=24980,
            host="127.0.0.1",
            no_open=True,
            pid_file=self.pid_file,
            log_file=self.log_file,
            info_file=self.info_file,
        )

        self.assertEqual(res["status"], "started")
        self.assertEqual(read_pid(self.pid_file), 65432)
        info = read_daemon_info(self.info_file)
        self.assertIsNotNone(info)
        self.assertEqual(info["pid"], 65432)
        self.assertEqual(info["port"], 24980)
        self.assertEqual(info["host"], "127.0.0.1")
        self.assertEqual(info["service"], "agy-model-bridge")

    @patch("bridge.daemon.check_server_healthy", return_value=True)
    def test_start_daemon_detects_port_conflict(self, mock_health):
        # A daemon is already running on 24980
        write_pid(11223, pid_file=self.pid_file)
        write_daemon_info(
            {
                "pid": 11223,
                "host": "127.0.0.1",
                "port": 24980,
                "service": "agy-model-bridge",
                "version": "0.21.1",
            },
            info_file=self.info_file,
        )

        with patch("bridge.daemon.is_pid_alive", return_value=True), patch("bridge.daemon.is_bridge_process", return_value=True):
            res = start_daemon(
                port=24981,
                host="127.0.0.1",
                pid_file=self.pid_file,
                info_file=self.info_file,
                log_file=self.log_file,
            )

        self.assertEqual(res["status"], "conflict")
        self.assertEqual(res["pid"], 11223)
        self.assertEqual(res["port"], 24980)
        self.assertIn("127.0.0.1:24980", res["error"])

    def test_start_daemon_rejects_no_auth_on_non_loopback(self):
        res = start_daemon(
            host="0.0.0.0",
            no_auth=True,
            pid_file=self.pid_file,
            info_file=self.info_file,
            log_file=self.log_file,
        )
        self.assertEqual(res["status"], "error")
        self.assertIn("Refusing to disable authentication", res["error"])

    @patch("bridge.daemon.os.kill")
    def test_stop_daemon_removes_daemon_info_and_pid(self, mock_kill):
        write_pid(77777, pid_file=self.pid_file)
        write_daemon_info(
            {
                "pid": 77777,
                "host": "127.0.0.1",
                "port": 24980,
                "service": "agy-model-bridge",
                "version": "0.21.1",
            },
            info_file=self.info_file,
        )

        with patch("bridge.daemon.is_pid_alive", side_effect=[True, False]), patch("bridge.daemon.is_bridge_process", return_value=True):
            res = stop_daemon(pid_file=self.pid_file, info_file=self.info_file)

        self.assertEqual(res["status"], "stopped")
        self.assertEqual(res["pid"], 77777)
        self.assertIsNone(read_pid(self.pid_file))
        self.assertIsNone(read_daemon_info(self.info_file))

    @patch("bridge.daemon.fetch_status_json")
    def test_get_daemon_status_uses_daemon_info(self, mock_fetch):
        write_pid(88888, pid_file=self.pid_file)
        write_daemon_info(
            {
                "pid": 88888,
                "host": "127.0.0.1",
                "port": 24999,
                "service": "agy-model-bridge",
                "version": "0.21.1",
            },
            info_file=self.info_file,
        )
        mock_fetch.return_value = {
            "service": "agy-model-bridge",
            "version": "0.21.1",
            "models_count": 5,
            "auth": {"status": "Valid"},
        }

        with patch("bridge.daemon.is_pid_alive", return_value=True), patch("bridge.daemon.is_bridge_process", return_value=True):
            status = get_daemon_status(pid_file=self.pid_file, info_file=self.info_file)

        self.assertTrue(status["running"])
        self.assertEqual(status["pid"], 88888)
        self.assertEqual(status["port"], 24999)
        self.assertEqual(status["url"], "http://127.0.0.1:24999/")

    @patch("bridge.daemon.webbrowser.open")
    @patch("bridge.daemon.check_server_healthy", return_value=True)
    @patch("bridge.daemon.subprocess.Popen")
    @patch("bridge.daemon.os.open")
    def test_start_daemon_uses_state_dir_lock_file_by_default(self, mock_os_open, mock_popen, mock_health, mock_browser):
        mock_proc = MagicMock()
        mock_proc.pid = 65433
        mock_popen.return_value = mock_proc
        mock_os_open.return_value = 99

        expected_lock = self.dir_path / "bridge.lock"

        res = start_daemon(
            port=24980,
            host="127.0.0.1",
            no_open=True,
            pid_file=self.pid_file,
            log_file=self.log_file,
            info_file=self.info_file,
        )

        self.assertEqual(res["status"], "started")
        # Verify os.open was called with self.dir_path / "bridge.lock"
        mock_os_open.assert_called()
        opened_path = mock_os_open.call_args[0][0]
        self.assertEqual(Path(opened_path), expected_lock)

    @patch("bridge.daemon.webbrowser.open")
    @patch("bridge.daemon.check_server_healthy", return_value=True)
    @patch("bridge.daemon.subprocess.Popen")
    @patch("bridge.daemon.os.open")
    def test_start_daemon_custom_lock_file(self, mock_os_open, mock_popen, mock_health, mock_browser):
        mock_proc = MagicMock()
        mock_proc.pid = 65434
        mock_popen.return_value = mock_proc
        mock_os_open.return_value = 100

        custom_lock = self.dir_path / "custom.lock"

        res = start_daemon(
            port=24980,
            host="127.0.0.1",
            no_open=True,
            pid_file=self.pid_file,
            log_file=self.log_file,
            info_file=self.info_file,
            lock_file=custom_lock,
        )

        self.assertEqual(res["status"], "started")
        mock_os_open.assert_called()
        opened_path = mock_os_open.call_args[0][0]
        self.assertEqual(Path(opened_path), custom_lock)

    @patch("bridge.daemon.webbrowser.open")
    @patch("bridge.daemon.check_server_healthy", return_value=True)
    @patch("bridge.daemon.subprocess.Popen")
    def test_start_daemon_records_runtime_options_in_info(self, mock_popen, mock_health, mock_browser):
        mock_proc = MagicMock()
        mock_proc.pid = 65435
        mock_popen.return_value = mock_proc

        res = start_daemon(
            port=24980,
            host="127.0.0.1",
            no_open=True,
            project="test-proj-123",
            base_url="https://custom.endpoint.pa",
            no_auth=True,
            pid_file=self.pid_file,
            log_file=self.log_file,
            info_file=self.info_file,
        )

        self.assertEqual(res["status"], "started")
        info = read_daemon_info(self.info_file)
        self.assertIsNotNone(info)
        self.assertEqual(info["project"], "test-proj-123")
        self.assertEqual(info["base_url"], "https://custom.endpoint.pa")
        self.assertTrue(info["no_auth"])

    @patch("bridge.daemon.os.kill")
    def test_stop_daemon_detects_port_mismatch(self, mock_kill):
        write_pid(99991, pid_file=self.pid_file)
        write_daemon_info(
            {
                "pid": 99991,
                "host": "127.0.0.1",
                "port": 24980,
                "service": "agy-model-bridge",
                "version": "0.21.1",
            },
            info_file=self.info_file,
        )

        with patch("bridge.daemon.is_pid_alive", return_value=True), patch("bridge.daemon.is_bridge_process", return_value=True):
            res = stop_daemon(port=24985, pid_file=self.pid_file, info_file=self.info_file)

        self.assertEqual(res["status"], "port_mismatch")
        self.assertIn("running on port 24980, not requested port 24985", res["error"])
        # Should not kill or delete PID
        mock_kill.assert_not_called()
        self.assertEqual(read_pid(self.pid_file), 99991)
        self.assertTrue(self.info_file.exists())

    @patch("bridge.daemon.os.kill")
    def test_stop_daemon_detects_host_mismatch(self, mock_kill):
        write_pid(99992, pid_file=self.pid_file)
        write_daemon_info(
            {
                "pid": 99992,
                "host": "127.0.0.1",
                "port": 24980,
                "service": "agy-model-bridge",
                "version": "0.21.1",
            },
            info_file=self.info_file,
        )

        with patch("bridge.daemon.is_pid_alive", return_value=True), patch("bridge.daemon.is_bridge_process", return_value=True):
            res = stop_daemon(host="192.168.1.50", pid_file=self.pid_file, info_file=self.info_file)

        self.assertEqual(res["status"], "host_mismatch")
        self.assertIn("running on host 127.0.0.1, not requested host 192.168.1.50", res["error"])
        # Should not kill or delete PID
        mock_kill.assert_not_called()
        self.assertEqual(read_pid(self.pid_file), 99992)
        self.assertTrue(self.info_file.exists())

    @patch("bridge.daemon.os.kill")
    def test_stop_daemon_allows_wildcard_host_and_matching_host(self, mock_kill):
        write_pid(99993, pid_file=self.pid_file)
        write_daemon_info(
            {
                "pid": 99993,
                "host": "127.0.0.1",
                "port": 24980,
                "service": "agy-model-bridge",
                "version": "0.21.1",
            },
            info_file=self.info_file,
        )

        # 0.0.0.0 wildcard host should not trigger host_mismatch
        with patch("bridge.daemon.is_pid_alive", side_effect=[True, False]), patch("bridge.daemon.is_bridge_process", return_value=True):
            res = stop_daemon(host="0.0.0.0", pid_file=self.pid_file, info_file=self.info_file)
        self.assertEqual(res["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
