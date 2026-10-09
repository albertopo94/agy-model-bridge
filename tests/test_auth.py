import unittest
from unittest.mock import patch, MagicMock
import subprocess
import base64
import json
import time
from datetime import datetime, timezone, timedelta
import threading

from bridge.auth import (
    KeychainTokenProvider,
    TokenProvider,
    AuthenticationError,
    SECURITY_PATH,
    get_security_binary,
)


class TestKeychainTokenProvider(unittest.TestCase):
    def setUp(self):
        self.provider = KeychainTokenProvider(
            service="gemini",
            account="antigravity",
            ttl_margin_seconds=60,
        )

    def _encode_secret(self, token_dict: dict, prefix: bool = True) -> str:
        raw_json = json.dumps(token_dict)
        b64 = base64.b64encode(raw_json.encode("utf-8")).decode("utf-8")
        return f"go-keyring-base64:{b64}" if prefix else b64

    @patch("subprocess.run")
    def test_successful_keychain_extraction_with_prefix(self, mock_run):
        future_iso = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        payload = {
            "token": {
                "access_token": "ya29.test_token_123",
                "token_type": "Bearer",
                "expiry": future_iso,
            }
        }
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=self._encode_secret(payload, prefix=True) + "\n",
            stderr="",
        )

        token = self.provider.get_token()
        self.assertEqual(token, "ya29.test_token_123")
        mock_run.assert_called_once_with(
            [SECURITY_PATH, "find-generic-password", "-s", "gemini", "-a", "antigravity", "-w"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10.0,
        )

    @patch("subprocess.run")
    def test_successful_keychain_extraction_numeric_expiry(self, mock_run):
        future_epoch = time.time() + 1800
        payload = {
            "token": {
                "access_token": "ya29.numeric_token_456",
                "expiry": future_epoch,
            }
        }
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=self._encode_secret(payload, prefix=False),
            stderr="",
        )

        token = self.provider.get_token()
        self.assertEqual(token, "ya29.numeric_token_456")

    @patch("subprocess.run")
    def test_missing_keychain_entry_raises_authentication_error(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=44,  # errSecItemNotFound in macOS security CLI
            stdout="",
            stderr="security: SecKeychainSearchCopyNext: The specified item could not be found in the keychain.\n",
        )

        with self.assertRaises(AuthenticationError) as ctx:
            self.provider.get_token()
        self.assertIn("keychain", str(ctx.exception).lower())

    @patch("subprocess.run")
    def test_corrupted_secret_raises_authentication_error(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="go-keyring-base64:not-valid-base64!!!\n",
            stderr="",
        )

        with self.assertRaises(AuthenticationError):
            self.provider.get_token()

    @patch("subprocess.run")
    def test_rfc3339nano_subsecond_parsing(self, mock_run):
        # 9 fractional digits (nanoseconds)
        nano_iso = "2028-09-25T15:46:04.123456789Z"
        payload = {
            "token": {
                "access_token": "ya29.nano_token",
                "expiry": nano_iso,
            }
        }
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=self._encode_secret(payload),
            stderr="",
        )

        token = self.provider.get_token()
        self.assertEqual(token, "ya29.nano_token")
        expected_dt = datetime.fromisoformat("2028-09-25T15:46:04.123456+00:00")
        self.assertAlmostEqual(self.provider._cached_expiry, expected_dt.timestamp(), places=3)

    @patch("subprocess.run")
    def test_unparseable_iso_expiry_falls_back_to_one_hour(self, mock_run):
        payload = {
            "token": {
                "access_token": "ya29.fallback_token",
                "expiry": "invalid-iso-string",
            }
        }
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=self._encode_secret(payload),
            stderr="",
        )

        before = time.time()
        token = self.provider.get_token()
        self.assertEqual(token, "ya29.fallback_token")
        self.assertTrue(self.provider._cached_expiry >= before + 3500.0)

    @patch("subprocess.run")
    def test_keychain_subprocess_timeout_raises_authentication_error(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["security"], timeout=10.0)

        with self.assertRaises(AuthenticationError) as ctx:
            self.provider.get_token()
        self.assertIn("timed out", str(ctx.exception).lower())

    @patch("subprocess.run")
    def test_missing_access_token_field_raises_authentication_error(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=self._encode_secret({"token": {"expiry": time.time() + 600}}),
            stderr="",
        )

        with self.assertRaises(AuthenticationError) as ctx:
            self.provider.get_token()
        self.assertIn("access_token", str(ctx.exception).lower())

    @patch("subprocess.run")
    def test_ttl_caching_avoids_redundant_subprocess(self, mock_run):
        future_epoch = time.time() + 600
        payload = {
            "token": {
                "access_token": "ya29.cached_token",
                "expiry": future_epoch,
            }
        }
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=self._encode_secret(payload),
            stderr="",
        )

        # First call loads into cache
        token1 = self.provider.get_token()
        # Second call should reuse cache
        token2 = self.provider.get_token()

        self.assertEqual(token1, "ya29.cached_token")
        self.assertEqual(token2, "ya29.cached_token")
        self.assertEqual(mock_run.call_count, 1)

    @patch("subprocess.run")
    def test_expired_token_refreshes_from_keychain(self, mock_run):
        # Expiry within 60s margin (e.g. 30s in the future)
        soon_expired = time.time() + 30
        payload1 = {
            "token": {
                "access_token": "ya29.expiring_token",
                "expiry": soon_expired,
            }
        }
        fresh_epoch = time.time() + 3600
        payload2 = {
            "token": {
                "access_token": "ya29.fresh_token",
                "expiry": fresh_epoch,
            }
        }
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=self._encode_secret(payload1), stderr=""),
            MagicMock(returncode=0, stdout=self._encode_secret(payload2), stderr=""),
        ]

        token1 = self.provider.get_token()
        self.assertEqual(token1, "ya29.expiring_token")
        self.assertEqual(mock_run.call_count, 1)

        # Second call sees expiry <= now + 60s, triggers refresh
        token2 = self.provider.get_token()
        self.assertEqual(token2, "ya29.fresh_token")
        self.assertEqual(mock_run.call_count, 2)

    @patch("subprocess.run")
    def test_invalidate_forces_keychain_reload(self, mock_run):
        future_epoch = time.time() + 1200
        payload = {
            "token": {
                "access_token": "ya29.token_before_invalidate",
                "expiry": future_epoch,
            }
        }
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=self._encode_secret(payload),
            stderr="",
        )

        token1 = self.provider.get_token()
        self.assertEqual(token1, "ya29.token_before_invalidate")
        self.assertEqual(mock_run.call_count, 1)

        # Invalidate cache
        self.provider.invalidate()

        # Next get_token should re-read
        token2 = self.provider.get_token()
        self.assertEqual(token2, "ya29.token_before_invalidate")
        self.assertEqual(mock_run.call_count, 2)

    @patch("subprocess.run")
    def test_force_refresh_bypasses_valid_cache(self, mock_run):
        future_epoch = time.time() + 1200
        payload = {
            "token": {
                "access_token": "ya29.initial_token",
                "expiry": future_epoch,
            }
        }
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=self._encode_secret(payload),
            stderr="",
        )

        self.provider.get_token()
        self.assertEqual(mock_run.call_count, 1)

        # Force refresh
        self.provider.get_token(force_refresh=True)
        self.assertEqual(mock_run.call_count, 2)

    @patch("subprocess.run")
    def test_concurrent_access_is_thread_safe(self, mock_run):
        future_epoch = time.time() + 1200
        payload = {
            "token": {
                "access_token": "ya29.concurrent_token",
                "expiry": future_epoch,
            }
        }
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=self._encode_secret(payload),
            stderr="",
        )

        results = []
        threads = []

        def worker():
            t = self.provider.get_token()
            results.append(t)

        for _ in range(10):
            th = threading.Thread(target=worker)
            threads.append(th)
            th.start()

        for th in threads:
            th.join()

        self.assertEqual(len(results), 10)
        self.assertTrue(all(r == "ya29.concurrent_token" for r in results))
        self.assertEqual(mock_run.call_count, 1)

    @patch("subprocess.run")
    def test_keychain_oserror_raises_auth_error(self, mock_run):
        mock_run.side_effect = FileNotFoundError("No such file or directory: 'security'")
        with self.assertRaises(AuthenticationError) as ctx:
            self.provider.get_token()
        self.assertIn("Failed to execute security CLI", str(ctx.exception))

    def test_naive_datetime_localized_to_utc(self):
        # A naive timestamp without timezone offset should be interpreted as UTC
        payload = {
            "token": {
                "access_token": "ya29.naive_token",
                "expiry": "2030-01-01T12:00:00",
            }
        }
        secret = self._encode_secret(payload)
        token, expiry = self.provider._decode_credentials(secret)
        self.assertEqual(token, "ya29.naive_token")
        expected_dt = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(expiry, expected_dt.timestamp())



class TestSecurityBinaryResolution(unittest.TestCase):
    @patch("bridge.auth.Path.is_file")
    def test_get_security_binary_when_usr_bin_security_exists(self, mock_is_file):
        mock_is_file.return_value = True
        self.assertEqual(get_security_binary(), "/usr/bin/security")

    @patch("bridge.auth.Path.is_file")
    @patch("bridge.auth.shutil.which")
    def test_get_security_binary_when_usr_bin_security_missing_uses_which(self, mock_which, mock_is_file):
        mock_is_file.return_value = False
        mock_which.return_value = "/opt/homebrew/bin/security"
        self.assertEqual(get_security_binary(), "/opt/homebrew/bin/security")

    @patch("bridge.auth.Path.is_file")
    @patch("bridge.auth.shutil.which")
    def test_get_security_binary_when_both_missing_falls_back_to_name(self, mock_which, mock_is_file):
        mock_is_file.return_value = False
        mock_which.return_value = None
        self.assertEqual(get_security_binary(), "security")

    @patch("bridge.auth.SECURITY_PATH", "/custom/bin/security")
    @patch("subprocess.run")
    def test_read_keychain_invokes_resolved_security_path(self, mock_run):
        provider = KeychainTokenProvider(service="test-service", account="test-account")
        mock_run.return_value = MagicMock(returncode=0, stdout="test-secret\n", stderr="")
        provider._read_keychain()
        mock_run.assert_called_once_with(
            ["/custom/bin/security", "find-generic-password", "-s", "test-service", "-a", "test-account", "-w"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10.0,
        )


class TestTokenProviderProtocol(unittest.TestCase):
    def test_keychain_token_provider_implements_protocol(self):
        provider = KeychainTokenProvider()
        self.assertTrue(isinstance(provider, TokenProvider))

    def test_keychain_token_provider_expiry_property(self):
        provider = KeychainTokenProvider()
        self.assertEqual(provider.expiry, 0.0)
        provider._cached_expiry = 1234567.89
        self.assertEqual(provider.expiry, 1234567.89)

    def test_invalidate_resets_expiry_and_cached_token(self):
        provider = KeychainTokenProvider()
        provider._cached_token = "some-token"
        provider._cached_expiry = 9999999.0
        provider.invalidate()
        self.assertIsNone(provider._cached_token)
        self.assertEqual(provider.expiry, 0.0)
        self.assertEqual(provider._cached_expiry, 0.0)


if __name__ == "__main__":
    unittest.main()

