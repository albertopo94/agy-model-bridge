"""Keychain authentication provider and thread-safe TTL token cache."""

import base64
from datetime import datetime, timezone
import json
import re
import subprocess
import threading
import time
from typing import Any


class AuthenticationError(Exception):
    """Raised when Keychain reading or token decoding fails."""

    pass


class KeychainTokenProvider:
    """Extracts, parses, and caches access tokens from macOS Keychain."""

    def __init__(
        self,
        service: str = "gemini",
        account: str = "antigravity",
        ttl_margin_seconds: int = 60,
    ) -> None:
        self.service = service
        self.account = account
        self.ttl_margin_seconds = ttl_margin_seconds
        self._lock = threading.Lock()
        self._cached_token: str | None = None
        self._cached_expiry: float = 0.0

    def get_token(self, force_refresh: bool = False) -> str:
        """Retrieves a valid access token from cache or Keychain."""
        with self._lock:
            now = time.time()
            if (
                not force_refresh
                and self._cached_token is not None
                and now < (self._cached_expiry - self.ttl_margin_seconds)
            ):
                return self._cached_token

            raw_secret = self._read_keychain()
            token, expiry = self._decode_credentials(raw_secret)
            self._cached_token = token
            self._cached_expiry = expiry
            return token

    def invalidate(self) -> None:
        """Invalidates the in-memory token cache."""
        with self._lock:
            self._cached_token = None
            self._cached_expiry = 0.0

    def _read_keychain(self) -> str:
        """Executes macOS security CLI to read stored generic password."""
        cmd = [
            "security",
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
        except subprocess.TimeoutExpired as e:
            raise AuthenticationError(
                f"Failed to retrieve credentials from Keychain: command timed out after 10.0s "
                f"(service={self.service}, account={self.account})"
            ) from e
        except OSError as e:
            raise AuthenticationError(
                f"Failed to execute security CLI (service={self.service}, account={self.account}): {e}"
            ) from e

        if res.returncode != 0:
            err_msg = res.stderr.strip()
            raise AuthenticationError(
                f"Failed to retrieve credentials from Keychain (service={self.service}, "
                f"account={self.account}). Ensure you are logged into Antigravity (`agy login`). "
                f"Details: {err_msg}"
            )
        return res.stdout.strip()

    def _decode_credentials(self, raw_secret: str) -> tuple[str, float]:
        """Decodes base64 payload from Keychain and extracts token and expiry timestamp."""
        secret_data = raw_secret.strip()
        if secret_data.startswith("go-keyring-base64:"):
            secret_data = secret_data[len("go-keyring-base64:"):]

        try:
            decoded_bytes = base64.b64decode(secret_data)
            json_obj = json.loads(decoded_bytes.decode("utf-8"))
        except Exception as e:
            raise AuthenticationError(
                f"Corrupted or invalid base64/JSON credential payload from Keychain: {e}"
            ) from e

        if not isinstance(json_obj, dict):
            raise AuthenticationError("Decoded Keychain payload is not a JSON object")

        token_obj: Any = json_obj.get("token")
        if not isinstance(token_obj, dict):
            token_obj = json_obj

        access_token = token_obj.get("access_token")
        if not access_token or not isinstance(access_token, str):
            raise AuthenticationError("Missing 'access_token' in Keychain credentials")

        raw_expiry = token_obj.get("expiry")
        expiry_ts: float = 0.0
        if isinstance(raw_expiry, (int, float)):
            expiry_ts = float(raw_expiry)
        elif isinstance(raw_expiry, str):
            try:
                clean_iso = (
                    raw_expiry.replace("Z", "+00:00")
                    if raw_expiry.endswith("Z")
                    else raw_expiry
                )
                clean_iso = re.sub(r"\.(\d{6})\d+", r".\1", clean_iso)
                dt = datetime.fromisoformat(clean_iso)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                expiry_ts = dt.timestamp()
            except Exception:
                expiry_ts = time.time() + 3600.0
        else:
            expiry_ts = time.time() + 3600.0

        return access_token, expiry_ts
