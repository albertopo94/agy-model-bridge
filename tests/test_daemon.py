"""Tests for daemon lifecycle and process management utilities."""

import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from bridge.daemon import (
    get_daemon_status,
    is_pid_alive,
    open_dashboard,
    read_pid,
    remove_pid,
    start_daemon,
    stop_daemon,
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

    @patch("bridge.daemon.check_server_healthy", return_value=True)
    @patch("bridge.daemon.subprocess.Popen")
    def test_start_daemon_already_running(self, mock_popen, mock_health):
        write_pid(33333, pid_file=self.pid_file)

        with patch("bridge.daemon.is_pid_alive", return_value=True):
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
        with patch("bridge.daemon.is_pid_alive", side_effect=[True, False]):
            res = stop_daemon(pid_file=self.pid_file)

        self.assertEqual(res["status"], "stopped")
        self.assertEqual(res["pid"], 55555)
        self.assertIsNone(read_pid(self.pid_file))
        mock_kill.assert_called()

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

        with patch("bridge.daemon.is_pid_alive", return_value=True):
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
        self.assertIn("Activo", output)
        self.assertIn("11111", output)
        self.assertIn("27", output)

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


if __name__ == "__main__":
    unittest.main()
