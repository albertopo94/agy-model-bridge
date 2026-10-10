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

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

from bridge import __version__

def get_default_daemon_dir() -> Path:
    state_dir = os.environ.get("AGY_BRIDGE_STATE_DIR")
    if state_dir:
        return Path(state_dir)
    return Path.home() / ".agy-bridge"


def get_default_pid_file() -> Path:
    return get_default_daemon_dir() / "bridge.pid"


def get_default_info_file() -> Path:
    return get_default_daemon_dir() / "bridge.json"


def get_default_log_file() -> Path:
    return get_default_daemon_dir() / "bridge.log"


def get_default_lock_file() -> Path:
    return get_default_daemon_dir() / "bridge.lock"


DEFAULT_DAEMON_DIR = get_default_daemon_dir()
DEFAULT_PID_FILE = get_default_pid_file()
DEFAULT_INFO_FILE = get_default_info_file()
DEFAULT_LOG_FILE = get_default_log_file()
DEFAULT_LOCK_FILE = get_default_lock_file()


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
    target = Path(pid_file) if pid_file is not None else get_default_pid_file()
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
    target = Path(pid_file) if pid_file is not None else get_default_pid_file()
    if not target.exists() or not target.is_file():
        return None
    try:
        content = target.read_text(encoding="utf-8").strip()
        return int(content)
    except (ValueError, OSError):
        return None


def remove_pid(pid_file: Path | None = None) -> None:
    """Removes the PID file if it exists."""
    target = Path(pid_file) if pid_file is not None else get_default_pid_file()
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def write_daemon_info(info: dict[str, Any], info_file: Path | None = None) -> None:
    """Writes the daemon descriptor JSON atomically with 0o600 permissions."""
    target = Path(info_file) if info_file is not None else get_default_info_file()
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
            json.dump(info, f, indent=2)
            f.write("\n")
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


def read_daemon_info(info_file: Path | None = None) -> dict[str, Any] | None:
    """Reads and parses daemon info from bridge.json. Returns None if invalid or missing."""
    target = Path(info_file) if info_file is not None else get_default_info_file()
    if not target.exists() or not target.is_file():
        return None
    try:
        content = target.read_text(encoding="utf-8").strip()
        data = json.loads(content)
        return data if isinstance(data, dict) else None
    except (ValueError, OSError, json.JSONDecodeError):
        return None


def remove_daemon_info(info_file: Path | None = None) -> None:
    """Removes the daemon info JSON file if it exists."""
    target = Path(info_file) if info_file is not None else get_default_info_file()
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def is_bridge_process(pid: int | None) -> bool:
    """Verifies that the process with the given PID is strictly an agy-bridge process."""
    if pid is None or pid <= 0:
        return False
    try:
        res = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=1.0,
        )
        if res.returncode != 0:
            return False
        cmdline = res.stdout.strip()
        if not cmdline:
            return False
        tokens = cmdline.split()
        if not tokens:
            return False

        has_m_bridge = (
            "-m" in tokens
            and (tokens.index("-m") + 1 < len(tokens) and tokens[tokens.index("-m") + 1] == "bridge")
        )
        if has_m_bridge:
            return True

        for token in tokens:
            if token == "agy-bridge" or token.endswith("/agy-bridge"):
                return True
            if token == "agy-model-bridge" or token.endswith("/agy-model-bridge"):
                return True
            if token == "bridge/__main__.py" or token.endswith("/bridge/__main__.py"):
                return True

        return False
    except Exception:
        return False


def check_server_healthy(host: str, port: int, timeout: float = 1.0) -> bool:
    """Checks if the bridge HTTP server is responding to /healthz with correct service identity."""
    url = f"http://{host}:{port}/healthz"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "agy-bridge/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            return (
                isinstance(data, dict)
                and data.get("service") == "agy-model-bridge"
                and data.get("status") == "ok"
            )
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
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
    info_file: Path | None = None,
    log_file: Path | None = None,
    lock_file: Path | None = None,
    health_timeout: float = 5.0,
    api_key: str | None = None,
    no_auth: bool = False,
) -> dict[str, Any]:
    """Starts the bridge server as a background daemon process.

    Checks if already running, launches detached process via subprocess.Popen,
    polls health check, writes PID and daemon info files, and opens default web browser.
    """
    from bridge.security import is_loopback_host
    if no_auth and not is_loopback_host(host):
        return {
            "status": "error",
            "error": (
                f"Refusing to disable authentication (--no-auth) on non-loopback host '{host}'. "
                "--no-auth is only permitted on loopback addresses."
            ),
        }

    target_pid_file = Path(pid_file) if pid_file is not None else get_default_pid_file()
    target_info_file = Path(info_file) if info_file is not None else get_default_info_file()
    target_log_file = Path(log_file) if log_file is not None else get_default_log_file()
    if lock_file is not None:
        target_lock_file = Path(lock_file)
    else:
        target_lock_file = target_pid_file.parent / "bridge.lock"
    dashboard_url = f"http://{host}:{port}/"

    # Acquire file lock to prevent concurrent start races
    lock_fd = None
    if fcntl is not None:
        target_lock_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock_fd = os.open(target_lock_file, os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        except OSError:
            lock_fd = None

    try:
        existing_pid = read_pid(pid_file=target_pid_file)
        existing_info = read_daemon_info(info_file=target_info_file)
        if existing_pid:
            if is_pid_alive(existing_pid) and is_bridge_process(existing_pid):
                existing_port = existing_info.get("port") if existing_info else None
                existing_host = existing_info.get("host", "127.0.0.1") if existing_info else "127.0.0.1"
                if existing_port is not None and (existing_port != port or existing_host != host):
                    return {
                        "status": "conflict",
                        "error": (
                            f"Bridge daemon is already running on {existing_host}:{existing_port} "
                            f"(PID {existing_pid}). Stop it before starting on a different port/host."
                        ),
                        "pid": existing_pid,
                        "port": existing_port,
                        "host": existing_host,
                        "url": f"http://{existing_host}:{existing_port}/",
                        "opened_browser": False,
                    }
                return {
                    "status": "already_running",
                    "pid": existing_pid,
                    "port": existing_port or port,
                    "host": existing_host or host,
                    "url": f"http://{existing_host or host}:{existing_port or port}/",
                    "opened_browser": False,
                }
            else:
                remove_pid(pid_file=target_pid_file)
                remove_daemon_info(info_file=target_info_file)

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

        effective_key = api_key or os.environ.get("AGY_API_KEY")
        if effective_key:
            import bridge.security
            bridge.security.write_api_key(effective_key, daemon_dir=target_pid_file.parent)

        child_env = os.environ.copy()
        child_env.pop("AGY_API_KEY", None)

        with open(target_log_file, "a", encoding="utf-8") as out:
            proc = subprocess.Popen(
                cmd,
                stdout=out,
                stderr=out,
                env=child_env,
                cwd=str(target_pid_file.parent),
                start_new_session=True,
            )

        pid = proc.pid
        write_pid(pid, pid_file=target_pid_file)
        daemon_info = {
            "pid": pid,
            "host": host,
            "port": port,
            "service": "agy-model-bridge",
            "version": __version__,
            "started_at": int(time.time()),
            "project": project,
            "base_url": base_url,
            "no_auth": no_auth,
        }
        write_daemon_info(daemon_info, info_file=target_info_file)

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
            remove_daemon_info(info_file=target_info_file)
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
    finally:
        if fcntl is not None and lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
            except OSError:
                pass


def stop_daemon(
    port: int | None = None,
    host: str = "127.0.0.1",
    pid_file: Path | None = None,
    info_file: Path | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Gracefully terminates the background daemon process."""
    target_pid_file = Path(pid_file) if pid_file is not None else get_default_pid_file()
    target_info_file = Path(info_file) if info_file is not None else get_default_info_file()
    pid = read_pid(pid_file=target_pid_file)

    if not pid or not is_pid_alive(pid):
        remove_pid(pid_file=target_pid_file)
        remove_daemon_info(info_file=target_info_file)
        return {"status": "not_running", "pid": pid}

    if not is_bridge_process(pid):
        remove_pid(pid_file=target_pid_file)
        remove_daemon_info(info_file=target_info_file)
        return {"status": "not_running", "pid": None}

    info = read_daemon_info(info_file=target_info_file)
    if port is not None:
        if info and info.get("port") is not None and info.get("port") != port:
            return {
                "status": "port_mismatch",
                "error": f"Daemon PID {pid} is running on port {info.get('port')}, not requested port {port}.",
            }

    if host is not None and info:
        if info.get("host") is not None and info.get("host") != host and host not in ("0.0.0.0", ""):
            return {
                "status": "host_mismatch",
                "error": f"Daemon PID {pid} is running on host {info.get('host')}, not requested host {host}.",
            }

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        remove_pid(pid_file=target_pid_file)
        remove_daemon_info(info_file=target_info_file)
        return {"status": "not_running", "pid": pid}
    except OSError:
        pass

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_pid_alive(pid):
            break
        time.sleep(0.05)
    else:
        if is_pid_alive(pid) and is_bridge_process(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    remove_pid(pid_file=target_pid_file)
    remove_daemon_info(info_file=target_info_file)
    return {"status": "stopped", "pid": pid}


def get_daemon_status(
    port: int = 24980,
    host: str = "127.0.0.1",
    pid_file: Path | None = None,
    info_file: Path | None = None,
) -> dict[str, Any]:
    """Returns active daemon runtime status."""
    target_pid_file = Path(pid_file) if pid_file is not None else get_default_pid_file()
    target_info_file = Path(info_file) if info_file is not None else get_default_info_file()
    pid = read_pid(pid_file=target_pid_file)
    daemon_info = read_daemon_info(info_file=target_info_file)

    effective_port = daemon_info.get("port", port) if daemon_info else port
    effective_host = daemon_info.get("host", host) if daemon_info else host
    alive = (is_pid_alive(pid) and is_bridge_process(pid)) if pid else False
    dashboard_url = f"http://{effective_host}:{effective_port}/"

    if alive:
        status_data = fetch_status_json(effective_host, effective_port, timeout=1.0) or {}
        return {
            "running": True,
            "pid": pid,
            "port": effective_port,
            "host": effective_host,
            "url": dashboard_url,
            "models_count": status_data.get("models_count", 0),
            "auth": status_data.get("auth", {}),
        }
    else:
        unbound_status = fetch_status_json(effective_host, effective_port, timeout=0.5)
        if unbound_status and unbound_status.get("service") == "agy-model-bridge":
            return {
                "running": True,
                "pid": None,
                "port": effective_port,
                "host": effective_host,
                "url": dashboard_url,
                "models_count": unbound_status.get("models_count", 0),
                "auth": unbound_status.get("auth", {}),
            }
        if pid and not alive:
            remove_pid(pid_file=target_pid_file)
            remove_daemon_info(info_file=target_info_file)
        return {
            "running": False,
            "pid": None,
            "port": effective_port,
            "host": effective_host,
            "url": dashboard_url,
        }


def open_dashboard(port: int = 24980, host: str = "127.0.0.1") -> bool:
    """Opens the local dashboard URL in the default web browser."""
    url = f"http://{host}:{port}/"
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False
