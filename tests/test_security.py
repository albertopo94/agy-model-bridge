"""Unit tests for API key generation, storage, and validation in bridge.security."""

import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from bridge.security import (
    get_or_create_api_key,
    validate_api_key,
    write_api_key,
)


class TestSecurityModule(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.daemon_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_write_api_key_persists_with_secure_permissions(self):
        secret = "test-explicit-key-42"
        write_api_key(secret, daemon_dir=self.daemon_dir)
        key_file = self.daemon_dir / "api_key"
        self.assertTrue(key_file.exists())
        self.assertEqual(stat.S_IMODE(key_file.stat().st_mode), 0o600)
        self.assertEqual(key_file.read_text(encoding="utf-8").strip(), secret)

    def test_get_or_create_api_key_creates_and_persists(self):
        key = get_or_create_api_key(daemon_dir=self.daemon_dir)
        self.assertIsInstance(key, str)
        self.assertEqual(len(key), 48)  # 24 bytes hex = 48 chars
        key_file = self.daemon_dir / "api_key"
        self.assertTrue(key_file.exists())
        self.assertEqual(stat.S_IMODE(key_file.stat().st_mode), 0o600)
        self.assertEqual(key_file.read_text(encoding="utf-8").strip(), key)

        # Subsequent call reads existing key
        key2 = get_or_create_api_key(daemon_dir=self.daemon_dir)
        self.assertEqual(key, key2)

    def test_get_or_create_api_key_respects_env_var(self):
        with mock.patch.dict(os.environ, {"AGY_API_KEY": "env-provided-secret-token"}):
            key = get_or_create_api_key(daemon_dir=self.daemon_dir)
            self.assertEqual(key, "env-provided-secret-token")

    def test_validate_api_key_bearer(self):
        headers = {"Authorization": "Bearer secret-123"}
        self.assertTrue(validate_api_key("secret-123", headers))
        self.assertFalse(validate_api_key("other-secret", headers))

    def test_validate_api_key_x_api_key(self):
        headers = {"x-api-key": "secret-456"}
        self.assertTrue(validate_api_key("secret-456", headers))
        self.assertFalse(validate_api_key("wrong", headers))

    def test_validate_api_key_anthropic_auth_token(self):
        headers = {"anthropic-auth-token": "secret-789"}
        self.assertTrue(validate_api_key("secret-789", headers))
        self.assertFalse(validate_api_key("wrong", headers))

    def test_validate_api_key_no_auth_mode(self):
        self.assertTrue(validate_api_key(None, {}))
        self.assertTrue(validate_api_key("", {}))
        self.assertTrue(validate_api_key(None, {"Authorization": "Bearer anything"}))

    def test_validate_api_key_missing_or_invalid(self):
        self.assertFalse(validate_api_key("expected-key", {}))
        self.assertFalse(validate_api_key("expected-key", {"Authorization": "Basic dXNlcjpwYXNz"}))
        self.assertFalse(validate_api_key("expected-key", {"Authorization": "Bearer "}))

    def test_validate_api_key_bearer_case_insensitive(self):
        self.assertTrue(validate_api_key("secret-123", {"Authorization": "bearer secret-123"}))
        self.assertTrue(validate_api_key("secret-123", {"Authorization": "BEARER secret-123"}))
        self.assertTrue(validate_api_key("secret-123", {"Authorization": "Bearer secret-123"}))

    def test_get_or_create_api_key_repairs_permissions(self):
        key_file = self.daemon_dir / "api_key"
        self.daemon_dir.mkdir(parents=True, exist_ok=True)
        key_file.write_text("existing-key\n", encoding="utf-8")
        os.chmod(key_file, 0o644)  # Accidental open permissions
        key = get_or_create_api_key(daemon_dir=self.daemon_dir)
        self.assertEqual(key, "existing-key")
        self.assertEqual(stat.S_IMODE(key_file.stat().st_mode), 0o600)

    def test_validate_api_key_non_ascii_headers_does_not_crash(self):
        expected = "valid-secret-key"
        self.assertFalse(validate_api_key(expected, {"x-api-key": "ñ"}))
        self.assertFalse(validate_api_key(expected, {"Authorization": "Bearer áéíóú"}))
        self.assertFalse(validate_api_key(expected, {"anthropic-auth-token": "🔑"}))

    def test_create_server_defaults_to_secured(self):
        from bridge.server import create_server
        mock_client = mock.MagicMock()
        with mock.patch("bridge.security.DEFAULT_DAEMON_DIR", self.daemon_dir):
            server = create_server(host="127.0.0.1", port=0, client=mock_client, project="test-project")
            try:
                self.assertIsNotNone(server.api_key)
                self.assertEqual(len(server.api_key), 48)
            finally:
                server.server_close()

    def test_create_server_no_auth_disables_secured_mode(self):
        from bridge.server import create_server
        mock_client = mock.MagicMock()
        server = create_server(host="127.0.0.1", port=0, client=mock_client, project="test-project", no_auth=True)
        try:
            self.assertIsNone(server.api_key)
        finally:
            server.server_close()


if __name__ == "__main__":
    unittest.main()
