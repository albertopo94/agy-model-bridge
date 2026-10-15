"""Cursor authentication and session management.

Zero external dependencies: pure standard library.
Extracts JWT access token from macOS Keychain ('cursor-access-token' / 'cursor-user')
or environment, decodes claims, and builds the WorkosCursorSessionToken cookie.
"""

import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Any
import urllib.parse

from bridge.errors import AuthenticationError


def get_security_binary() -> str:
    """Returns the absolute path to the macOS security binary or falls back to PATH/name."""
    if Path("/usr/bin/security").is_file():
        return "/usr/bin/security"
    return shutil.which("security") or "security"


SECURITY_PATH: str = get_security_binary()


@dataclass(frozen=True, slots=True)
class CursorSession:
    """Represents an active Cursor session token and its claims."""

    raw_token: str
    subject: str
    expiry: float
    email: str | None = None

    @property
    def cookie(self) -> str:
        """Returns the WorkosCursorSessionToken cookie string required by Cursor API."""
        encoded_sub = urllib.parse.quote(self.subject, safe="")
        return f"WorkosCursorSessionToken={encoded_sub}%3A%3A{self.raw_token}"

    @property
    def is_expired(self) -> bool:
        """Checks if the session token is expired or within the 60s safety margin."""
        return time.time() >= (self.expiry - 60.0)


def decode_cursor_jwt(token: str) -> tuple[str, float, str | None]:
    """Decodes claims from a Cursor JWT token.

    Returns:
        tuple of (subject, expiry_timestamp, email_or_none)
    Raises:
        AuthenticationError on invalid format or missing subject.
    """
    clean_token = token.strip()
    parts = clean_token.split(".")
    if len(parts) < 2:
        raise AuthenticationError("Invalid Cursor JWT token: expected at least header and payload segments")

    payload_b64 = parts[1]
    # Re-pad base64 url-safe string
    padded_b64 = payload_b64 + "=" * ((4 - len(payload_b64) % 4) % 4)

    try:
        decoded_bytes = base64.urlsafe_b64decode(padded_b64)
        payload = json.loads(decoded_bytes.decode("utf-8"))
    except Exception as exc:
        raise AuthenticationError(f"Failed to decode Cursor JWT payload: {exc}") from exc

    if not isinstance(payload, dict):
        raise AuthenticationError("Cursor JWT payload is not a valid JSON object")

    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub.strip():
        raise AuthenticationError("Missing or invalid 'sub' claim in Cursor JWT token")

    exp_raw = payload.get("exp")
    if isinstance(exp_raw, (int, float)) and exp_raw > 0:
        exp_ts = float(exp_raw)
    else:
        # Default fallback to 1 hour if exp is missing
        exp_ts = time.time() + 3600.0

    email: str | None = None
    raw_email = payload.get("email")
    if isinstance(raw_email, str) and raw_email.strip():
        email = raw_email.strip()

    return sub.strip(), exp_ts, email


class CursorAuthManager:
    """Manages thread-safe extraction and caching of Cursor credentials."""

    def __init__(
        self,
        service: str = "cursor-access-token",
        account: str = "cursor-user",
        ttl_margin_seconds: int = 60,
    ) -> None:
        self.service = service
        self.account = account
        self.ttl_margin_seconds = ttl_margin_seconds
        self._lock = threading.Lock()
        self._cached_session: CursorSession | None = None

    def invalidate(self) -> None:
        """Invalidates in-memory session cache."""
        with self._lock:
            self._cached_session = None

    def get_session(self, force_refresh: bool = False) -> CursorSession:
        """Retrieves an active CursorSession from cache, environment, or Keychain."""
        with self._lock:
            now = time.time()
            if (
                not force_refresh
                and self._cached_session is not None
                and now < (self._cached_session.expiry - self.ttl_margin_seconds)
            ):
                return self._cached_session

            # 1. Environment variable override
            env_token = os.environ.get("CURSOR_ACCESS_TOKEN", "").strip()
            if env_token:
                sub, exp, email = decode_cursor_jwt(env_token)
                session = CursorSession(raw_token=env_token, subject=sub, expiry=exp, email=email)
                self._cached_session = session
                return session

            # 2. macOS Keychain
            raw_token = self._read_keychain()
            sub, exp, email = decode_cursor_jwt(raw_token)
            session = CursorSession(raw_token=raw_token, subject=sub, expiry=exp, email=email)
            self._cached_session = session
            return session

    def _read_keychain(self) -> str:
        """Executes macOS security CLI to read stored generic password for Cursor."""
        cmd = [
            SECURITY_PATH,
            "find-generic-password",
            "-s",
            self.service,
            "-a",
            self.account,
            "-w",
        ]
        try:
            res = subprocess.run(
                cmd, capture_output=True, text=True, check=False, timeout=10.0
            )
        except subprocess.TimeoutExpired as exc:
            raise AuthenticationError(
                f"Failed to retrieve Cursor credentials from Keychain: command timed out after 10.0s "
                f"(service={self.service}, account={self.account})"
            ) from exc
        except OSError as exc:
            raise AuthenticationError(
                f"Failed to execute security CLI for Cursor (service={self.service}, account={self.account}): {exc}"
            ) from exc

        if res.returncode != 0:
            err_msg = res.stderr.strip()
            raise AuthenticationError(
                f"Failed to retrieve credentials from Keychain (service={self.service}, "
                f"account={self.account}). Ensure you are logged into Cursor (`agent login`). "
                f"Details: {err_msg}"
            )

        token = res.stdout.strip()
        if not token:
            raise AuthenticationError(
                f"Empty credential returned from Keychain for service={self.service}, account={self.account}"
            )
        return token
