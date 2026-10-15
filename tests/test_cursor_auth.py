"""Unit tests for Cursor authentication and session token extraction."""

import base64
import json
import subprocess
import time
import unittest
from unittest.mock import MagicMock, patch

from bridge.cursor_auth import (
    CursorAuthManager,
    CursorSession,
    decode_cursor_jwt,
)
from bridge.errors import AuthenticationError


def make_test_jwt(sub: str, exp: int, email: str | None = None) -> str:
    """Helper to generate an unsigned test JWT."""
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').decode().rstrip("=")
    payload_dict = {"sub": sub, "exp": exp}
    if email:
        payload_dict["email"] = email
    payload_bytes = json.dumps(payload_dict).encode()
    payload = base64.urlsafe_b64encode(payload_bytes).decode().rstrip("=")
    sig = "mock_signature"
    return f"{header}.{payload}.{sig}"


class TestCursorAuth(unittest.TestCase):
    """Test suite for CursorAuthManager and JWT parsing."""

    def test_decode_cursor_jwt_valid(self) -> None:
        future_exp = int(time.time()) + 3600
        token = make_test_jwt("user_12345", future_exp, "test@example.com")
        sub, exp, email = decode_cursor_jwt(token)
        self.assertEqual(sub, "user_12345")
        self.assertEqual(exp, float(future_exp))
        self.assertEqual(email, "test@example.com")

    def test_decode_cursor_jwt_without_email(self) -> None:
        future_exp = int(time.time()) + 1800
        token = make_test_jwt("auth0|abcde", future_exp)
        sub, exp, email = decode_cursor_jwt(token)
        self.assertEqual(sub, "auth0|abcde")
        self.assertEqual(exp, float(future_exp))
        self.assertIsNone(email)

    def test_decode_cursor_jwt_invalid_format(self) -> None:
        with self.assertRaises(AuthenticationError):
            decode_cursor_jwt("not-a-jwt")

        with self.assertRaises(AuthenticationError):
            decode_cursor_jwt("header.invalid-base64.sig")

    def test_decode_cursor_jwt_missing_sub(self) -> None:
        header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode().rstrip("=")
        payload = base64.urlsafe_b64encode(b'{"exp":12345}').decode().rstrip("=")
        token = f"{header}.{payload}.sig"
        with self.assertRaises(AuthenticationError) as ctx:
            decode_cursor_jwt(token)
        self.assertIn("sub", str(ctx.exception))

    def test_cursor_session_cookie(self) -> None:
        session = CursorSession(
            raw_token="raw.jwt.token",
            subject="google-oauth2|12345",
            expiry=time.time() + 3600,
            email="test@example.com",
        )
        cookie = session.cookie
        self.assertIn("WorkosCursorSessionToken=", cookie)
        self.assertIn("google-oauth2%7C12345", cookie)
        self.assertIn("%3A%3A", cookie)
        self.assertIn("raw.jwt.token", cookie)

    @patch("subprocess.run")
    def test_get_session_from_keychain_success(self, mock_run: MagicMock) -> None:
        future_exp = int(time.time()) + 7200
        token = make_test_jwt("user_xyz", future_exp, "coder@cursor.sh")
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=token + "\n",
            stderr="",
        )

        manager = CursorAuthManager()
        session = manager.get_session()
        self.assertEqual(session.subject, "user_xyz")
        self.assertEqual(session.email, "coder@cursor.sh")
        self.assertEqual(session.raw_token, token)
        self.assertFalse(session.is_expired)

        # Call again without force_refresh: should hit cache (mock_run called once)
        session2 = manager.get_session()
        self.assertEqual(session2.subject, "user_xyz")
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_get_session_from_keychain_force_refresh(self, mock_run: MagicMock) -> None:
        future_exp = int(time.time()) + 7200
        token = make_test_jwt("user_1", future_exp)
        token2 = make_test_jwt("user_2", future_exp)
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=token + "\n", stderr=""),
            MagicMock(returncode=0, stdout=token2 + "\n", stderr=""),
        ]

        manager = CursorAuthManager()
        s1 = manager.get_session()
        self.assertEqual(s1.subject, "user_1")

        s2 = manager.get_session(force_refresh=True)
        self.assertEqual(s2.subject, "user_2")
        self.assertEqual(mock_run.call_count, 2)

    @patch("subprocess.run")
    def test_get_session_keychain_missing_or_error(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=44,
            stdout="",
            stderr="security: SecKeychainSearchCopyNext: The specified item could not be found in the keychain.",
        )

        manager = CursorAuthManager()
        with self.assertRaises(AuthenticationError) as ctx:
            manager.get_session()
        self.assertIn("Keychain", str(ctx.exception))
        self.assertIn("cursor-access-token", str(ctx.exception))

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["security"], timeout=10.0))
    def test_get_session_keychain_timeout(self, mock_run: MagicMock) -> None:
        manager = CursorAuthManager()
        with self.assertRaises(AuthenticationError) as ctx:
            manager.get_session()
        self.assertIn("timed out", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
