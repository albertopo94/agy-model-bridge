"""Test package for agy-model-bridge with global filesystem isolation."""

import atexit
import os
from pathlib import Path
import pwd
import tempfile

# 1. Discover the real host system user directory
try:
    REAL_USER_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
except Exception:
    REAL_USER_HOME = Path(os.environ.get("HOME", "/tmp")).resolve()

# 2. Create an isolated global sandbox directory for tests
_SANDBOX_DIR = tempfile.TemporaryDirectory(prefix="agy_test_sandbox_")
SANDBOX_HOME = Path(_SANDBOX_DIR.name).resolve()

# 3. Patch Path.home and os.path.expanduser globally
_orig_home = Path.home
_orig_expanduser = os.path.expanduser


def _sandboxed_home(cls: type[Path] = Path) -> Path:
    return SANDBOX_HOME


def _sandboxed_expanduser(path: str | os.PathLike[str]) -> str:
    p_str = os.fspath(path)
    if p_str == "~" or p_str.startswith("~/"):
        rel = p_str[2:] if p_str.startswith("~/") else ""
        return str(SANDBOX_HOME / rel) if rel else str(SANDBOX_HOME)
    return _orig_expanduser(path)


Path.home = classmethod(_sandboxed_home)  # type: ignore[assignment]
os.path.expanduser = _sandboxed_expanduser  # type: ignore[assignment]


def ensure_sandbox() -> Path:
    """Ensures test execution environment is strictly confined to the sandbox directory."""
    os.environ["HOME"] = str(SANDBOX_HOME)
    # Clear any ambient host environment overrides that would escape the sandbox
    os.environ.pop("AGY_BRIDGE_STATE_DIR", None)
    os.environ.pop("GENTLE_SHELL_HOME", None)
    os.environ.pop("PI_CODING_AGENT_DIR", None)
    import sys
    if "bridge.daemon" in sys.modules:
        import bridge.daemon
        bridge.daemon.DEFAULT_DAEMON_DIR = bridge.daemon.get_default_daemon_dir()
        bridge.daemon.DEFAULT_PID_FILE = bridge.daemon.get_default_pid_file()
        bridge.daemon.DEFAULT_INFO_FILE = bridge.daemon.get_default_info_file()
        bridge.daemon.DEFAULT_LOG_FILE = bridge.daemon.get_default_log_file()
        bridge.daemon.DEFAULT_LOCK_FILE = bridge.daemon.get_default_lock_file()
    return SANDBOX_HOME


# Apply immediately upon package import
ensure_sandbox()


def _cleanup() -> None:
    Path.home = _orig_home  # type: ignore[assignment]
    os.path.expanduser = _orig_expanduser  # type: ignore[assignment]
    _SANDBOX_DIR.cleanup()


atexit.register(_cleanup)
