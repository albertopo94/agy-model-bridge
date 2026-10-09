"""Security utilities for AGY Model Bridge.

Manages persistent local API keys and authenticates incoming inference requests.
Pure Python 3 standard library: secrets, hmac, hashlib, os, pathlib.
"""

from __future__ import annotations

import hmac
import os
from pathlib import Path
import secrets
import stat
from typing import Any
import uuid

DEFAULT_DAEMON_DIR = Path(os.environ.get("AGY_BRIDGE_STATE_DIR", Path.home() / ".agy-bridge"))
DEFAULT_API_KEY_FILE = DEFAULT_DAEMON_DIR / "api_key"


def write_secret_file(path: Path, content: str | bytes, mode: int = 0o600, encoding: str = "utf-8") -> None:
    """Atomically writes secret content to path with requested permissions set at creation time.

    Avoids umask race conditions by opening with os.open(..., O_CREAT | O_WRONLY | O_TRUNC, mode),
    ensuring parent directory has 0o700 permissions, fsyncing data, and atomically renaming.
    """
    path = Path(path)
    parent = path.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(parent, 0o700)
        except OSError:
            pass

    tmp_path = parent / f"{path.name}.tmp.{uuid.uuid4().hex}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp_path, flags, mode)
    try:
        mode_str = "wb" if isinstance(content, bytes) else "w"
        kwargs = {} if isinstance(content, bytes) else {"encoding": encoding}
        with open(fd, mode_str, closefd=True, **kwargs) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp_path, mode)
        except OSError:
            pass
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def write_api_key(api_key: str, daemon_dir: Path | None = None) -> None:
    """Persists the API key to <daemon_dir>/api_key with 0o600 permissions."""
    target_dir = Path(daemon_dir) if daemon_dir is not None else DEFAULT_DAEMON_DIR
    target_file = target_dir / "api_key"
    write_secret_file(target_file, f"{api_key.strip()}\n", mode=0o600)


def get_or_create_api_key(daemon_dir: Path | None = None) -> str:
    """Retrieves existing API key or generates a new 48-char hex secret.

    Priority:
    1. AGY_API_KEY environment variable.
    2. Contents of <daemon_dir>/api_key.
    3. Generate new random token via secrets.token_hex(24) and persist with 0o600.
    """
    env_key = os.environ.get("AGY_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    target_dir = Path(daemon_dir) if daemon_dir is not None else DEFAULT_DAEMON_DIR
    target_file = target_dir / "api_key"

    if target_file.exists() and target_file.is_file():
        try:
            if stat.S_IMODE(target_file.stat().st_mode) != 0o600:
                os.chmod(target_file, 0o600)
            content = target_file.read_text(encoding="utf-8").strip()
            if content:
                return content
        except OSError:
            pass

    # Generate new key
    new_key = secrets.token_hex(24)
    write_api_key(new_key, daemon_dir=target_dir)
    return new_key


def _safe_compare(provided: str, expected: str) -> bool:
    try:
        return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))
    except Exception:
        return False


def validate_api_key(expected_key: str | None, headers: Any) -> bool:
    """Validates the incoming HTTP request against the expected API key.

    Returns True if:
    - expected_key is None or empty string (no-auth mode).
    - Authorization: Bearer <expected_key> matches.
    - x-api-key: <expected_key> matches.
    - anthropic-auth-token: <expected_key> matches.
    Uses constant-time hmac.compare_digest to prevent timing attacks.
    """
    if expected_key is None or not expected_key.strip():
        return True

    expected = expected_key.strip()

    # Extract headers flexibly from dict or HTTPMessage
    def get_header(name: str) -> str:
        if headers is None:
            return ""
        if hasattr(headers, "get"):
            val = headers.get(name) or ""
            return str(val).strip()
        return ""

    # Check Authorization: Bearer <token> (case-insensitive)
    auth = get_header("Authorization")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token and _safe_compare(token, expected):
            return True

    # Check x-api-key
    x_api_key = get_header("x-api-key")
    if x_api_key and _safe_compare(x_api_key, expected):
        return True

    # Check anthropic-auth-token
    anthropic_token = get_header("anthropic-auth-token")
    if anthropic_token and _safe_compare(anthropic_token, expected):
        return True

    return False


def is_loopback_host(host: str | None) -> bool:
    """Returns True if the given host string is a recognized loopback address."""
    if not host:
        return False
    h = host.strip().lower()
    return h in ("127.0.0.1", "localhost", "::1", "[::1]") or h.startswith("127.")
