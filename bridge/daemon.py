"""Background daemon lifecycle and process management for Antigravity Model Bridge.

Pure Python 3 standard library: PID tracking, health polling, and browser integration.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any
import urllib.error
import urllib.request
import uuid
import webbrowser

DEFAULT_DAEMON_DIR = Path.home() / ".agy-bridge"
DEFAULT_PID_FILE = DEFAULT_DAEMON_DIR / "bridge.pid"
DEFAULT_LOG_FILE = DEFAULT_DAEMON_DIR / "bridge.log"


def is_pid_alive(pid: int | None) -> bool:
    """Checks whether a process with the given PID is currently alive."""
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        # Process exists, but owned by another user or restricted
        return True
    except (ProcessLookupError, OSError):
        return False


def write_pid(pid: int, pid_file: Path | None = None) -> None:
    """Writes the process PID atomically to the PID file with 0o600 permissions."""
    target = Path(pid_file) if pid_file is not None else DEFAULT_PID_FILE
    parent = target.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(parent, 0o700)
        except OSError:
            pass

    tmp_file = parent / f"{target.name}.tmp.{uuid.uuid4().hex}"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(f"{pid}\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_file, 0o600)
        os.replace(tmp_file, target)
    finally:
        if tmp_file.exists():
            try:
                tmp_file.unlink()
            except OSError:
                pass


def read_pid(pid_file: Path | None = None) -> int | None:
    """Reads and parses the PID from the PID file. Returns None if invalid or missing."""
    target = Path(pid_file) if pid_file is not None else DEFAULT_PID_FILE
    if not target.exists() or not target.is_file():
        return None
    try:
        content = target.read_text(encoding="utf-8").strip()
        return int(content)
    except (ValueError, OSError):
        return None


def remove_pid(pid_file: Path | None = None) -> None:
    """Removes the PID file if it exists."""
    target = Path(pid_file) if pid_file is not None else DEFAULT_PID_FILE
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def is_bridge_process(pid: int | None) -> bool:
    """Verifies that the process with the given PID is actually an agy-bridge process."""
    if pid is None or pid <= 0:
        return False
    try:
        res = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=1.0,
        )
        if res.returncode == 0:
            cmdline = res.stdout.strip().lower()
            return "bridge" in cmdline or "agy" in cmdline or "python" in cmdline
    except Exception:
        pass
    return True


def check_server_healthy(host: str, port: int, timeout: float = 1.0) -> bool:
    """Checks if the bridge HTTP server is responding to /healthz."""
    url = f"http://{host}:{port}/healthz"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "agy-bridge/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def fetch_status_json(host: str, port: int, timeout: float = 1.0) -> dict[str, Any] | None:
    """Fetches the JSON status from /api/status if reachable."""
    url = f"http://{host}:{port}/api/status"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "agy-bridge/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, dict):
                    return data
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        pass
    return None


def start_daemon(
    port: int = 24980,
    host: str = "127.0.0.1",
    no_open: bool = False,
    project: str | None = None,
    base_url: str | None = None,
    pid_file: Path | None = None,
    log_file: Path | None = None,
    health_timeout: float = 5.0,
    api_key: str | None = None,
    no_auth: bool = False,
) -> dict[str, Any]:
    """Starts the bridge server as a background daemon process.

    Checks if already running, launches detached process via subprocess.Popen,
    polls health check, writes PID file, and opens default web browser.
    """
    target_pid_file = Path(pid_file) if pid_file is not None else DEFAULT_PID_FILE
    target_log_file = Path(log_file) if log_file is not None else DEFAULT_LOG_FILE
    dashboard_url = f"http://{host}:{port}/"

    existing_pid = read_pid(pid_file=target_pid_file)
    if existing_pid:
        if is_pid_alive(existing_pid) and is_bridge_process(existing_pid):
            return {
                "status": "already_running",
                "pid": existing_pid,
                "port": port,
                "url": dashboard_url,
                "opened_browser": False,
            }
        else:
            remove_pid(pid_file=target_pid_file)

    target_log_file.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-u",
        "-m",
        "bridge",
        "--port",
        str(port),
        "--host",
        host,
    ]
    if project:
        cmd.extend(["--project", project])
    if base_url:
        cmd.extend(["--base-url", base_url])
    if no_auth:
        cmd.append("--no-auth")
    elif api_key:
        cmd.extend(["--api-key", api_key])

    with open(target_log_file, "a", encoding="utf-8") as out:
        proc = subprocess.Popen(
            cmd,
            stdout=out,
            stderr=out,
            start_new_session=True,
        )

    pid = proc.pid
    write_pid(pid, pid_file=target_pid_file)

    deadline = time.time() + health_timeout
    healthy = False
    while time.time() < deadline:
        if check_server_healthy(host, port, timeout=0.5):
            healthy = True
            break
        if not is_pid_alive(pid):
            break
        time.sleep(0.05)

    if not healthy:
        try:
            proc.terminate()
        except OSError:
            pass
        remove_pid(pid_file=target_pid_file)
        return {
            "status": "error",
            "error": f"Timeout waiting for bridge server to respond on port {port}. Check log at {target_log_file}",
            "port": port,
            "url": dashboard_url,
            "opened_browser": False,
        }

    opened_browser = False
    if not no_open:
        try:
            opened_browser = bool(webbrowser.open(dashboard_url))
        except Exception:
            opened_browser = False

    return {
        "status": "started",
        "pid": pid,
        "port": port,
        "url": dashboard_url,
        "opened_browser": opened_browser,
    }


def stop_daemon(
    port: int = 24980,
    host: str = "127.0.0.1",
    pid_file: Path | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Gracefully terminates the background daemon process."""
    target_pid_file = Path(pid_file) if pid_file is not None else DEFAULT_PID_FILE
    pid = read_pid(pid_file=target_pid_file)

    if not pid or not is_pid_alive(pid):
        remove_pid(pid_file=target_pid_file)
        return {"status": "not_running", "pid": pid}

    if not is_bridge_process(pid):
        remove_pid(pid_file=target_pid_file)
        return {"status": "not_running", "pid": None}

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        remove_pid(pid_file=target_pid_file)
        return {"status": "not_running", "pid": pid}
    except OSError:
        pass

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_pid_alive(pid):
            break
        time.sleep(0.05)
    else:
        if is_pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    remove_pid(pid_file=target_pid_file)
    return {"status": "stopped", "pid": pid}


def get_daemon_status(
    port: int = 24980,
    host: str = "127.0.0.1",
    pid_file: Path | None = None,
) -> dict[str, Any]:
    """Returns active daemon runtime status."""
    target_pid_file = Path(pid_file) if pid_file is not None else DEFAULT_PID_FILE
    pid = read_pid(pid_file=target_pid_file)
    alive = (is_pid_alive(pid) and is_bridge_process(pid)) if pid else False
    dashboard_url = f"http://{host}:{port}/"

    if alive:
        status_data = fetch_status_json(host, port, timeout=1.0) or {}
        return {
            "running": True,
            "pid": pid,
            "port": port,
            "host": host,
            "url": dashboard_url,
            "models_count": status_data.get("models_count", 0),
            "auth": status_data.get("auth", {}),
        }
    else:
        status_data = fetch_status_json(host, port, timeout=0.5)
        if status_data:
            return {
                "running": True,
                "pid": None,
                "port": port,
                "host": host,
                "url": dashboard_url,
                "models_count": status_data.get("models_count", 0),
                "auth": status_data.get("auth", {}),
            }
        if pid and not alive:
            remove_pid(pid_file=target_pid_file)
        return {
            "running": False,
            "pid": None,
            "port": port,
            "host": host,
            "url": dashboard_url,
        }


def open_dashboard(port: int = 24980, host: str = "127.0.0.1") -> bool:
    """Opens the local dashboard URL in the default web browser."""
    url = f"http://{host}:{port}/"
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False
