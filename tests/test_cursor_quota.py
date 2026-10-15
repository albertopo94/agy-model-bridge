"""Unit tests for CursorQuotaProvider and usage-summary parser."""

import json
import time
import unittest
from unittest.mock import MagicMock, patch

from bridge.cursor_auth import CursorSession
from bridge.cursor_quota import (
    CursorQuotaProvider,
    parse_cursor_usage_summary,
)
from bridge.errors import AuthenticationError
from bridge.quota import QuotaSnapshot


SAMPLE_CURSOR_USAGE = {
    "billingCycleStart": "2026-09-24T08:17:45.189Z",
    "billingCycleEnd": "2026-10-24T08:17:45.189Z",
    "membershipType": "free",
    "limitType": "user",
    "isUnlimited": False,
    "autoModelSelectedDisplayMessage": "You've used 7% of your included total usage",
    "namedModelSelectedDisplayMessage": "You've used 13% of your included API usage",
    "individualUsage": {
        "plan": {
            "enabled": True,
            "used": 0,
            "limit": 0,
            "remaining": 0,
            "breakdown": {
                "included": 0,
                "bonus": 13,
                "total": 13,
            },
            "autoPercentUsed": 0,
            "apiPercentUsed": 13.2,
            "totalPercentUsed": 6.6,
        },
        "onDemand": {
            "enabled": False,
            "used": 0,
            "limit": None,
            "remaining": None,
        },
    },
    "teamUsage": {},
}


class TestCursorQuota(unittest.TestCase):
    """Test suite for Cursor quota parser and provider."""

    def test_parse_cursor_usage_summary_success(self) -> None:
        now = 1760482000.0
        snapshot = parse_cursor_usage_summary(SAMPLE_CURSOR_USAGE, now=now)
        self.assertEqual(snapshot.status, "ok")
        self.assertEqual(snapshot.description, "Free Tier")
        self.assertEqual(len(snapshot.buckets), 3)

        # Bucket 0: Cursor Models
        b0 = snapshot.buckets[0]
        self.assertEqual(b0.id, "cursor-models")
        self.assertEqual(b0.name, "Cursor Models")
        self.assertEqual(b0.used_percent, 0)
        self.assertAlmostEqual(b0.remaining_fraction, 1.0)
        self.assertIsNotNone(b0.resets_in)

        # Bucket 1: Other Models
        b1 = snapshot.buckets[1]
        self.assertEqual(b1.id, "other-models")
        self.assertEqual(b1.name, "Other Models")
        self.assertEqual(b1.used_percent, 13)
        self.assertAlmostEqual(b1.remaining_fraction, 0.868, places=3)

        # Bucket 2: Plan
        b2 = snapshot.buckets[2]
        self.assertEqual(b2.id, "plan")
        self.assertEqual(b2.name, "Plan")
        self.assertEqual(b2.used_percent, 7)
        self.assertAlmostEqual(b2.remaining_fraction, 0.934, places=3)

        self.assertIsNotNone(snapshot.summary)
        self.assertEqual(snapshot.summary["membership_type"], "free")
        self.assertFalse(snapshot.summary["is_unlimited"])

    def test_parse_cursor_usage_summary_pro_plan(self) -> None:
        data = dict(SAMPLE_CURSOR_USAGE)
        data["membershipType"] = "pro"
        snapshot = parse_cursor_usage_summary(data)
        self.assertEqual(snapshot.status, "ok")
        self.assertEqual(snapshot.description, "Pro Plan")

    def test_parse_cursor_usage_summary_unlimited(self) -> None:
        data = dict(SAMPLE_CURSOR_USAGE)
        data["isUnlimited"] = True
        snapshot = parse_cursor_usage_summary(data)
        self.assertEqual(snapshot.status, "ok")
        self.assertIn("Unlimited", snapshot.description or "")

    def test_parse_cursor_usage_summary_invalid(self) -> None:
        snapshot = parse_cursor_usage_summary({"invalid": True})
        self.assertEqual(snapshot.status, "error")
        self.assertIn("Unexpected", snapshot.error or "")

    @patch("bridge.cursor_quota.urllib.request.urlopen")
    def test_provider_fetch_success(self, mock_urlopen: MagicMock) -> None:
        mock_auth = MagicMock()
        mock_auth.get_session.return_value = CursorSession(
            raw_token="raw.jwt",
            subject="sub_123",
            expiry=time.time() + 3600,
            email="dev@cursor.sh",
        )

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(SAMPLE_CURSOR_USAGE).encode("utf-8")
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        provider = CursorQuotaProvider(auth_manager=mock_auth)
        snapshot = provider.fetch()
        self.assertEqual(snapshot.status, "ok")
        self.assertEqual(len(snapshot.buckets), 3)

        # Second call hits cache
        snapshot2 = provider.fetch()
        self.assertEqual(snapshot2.status, "ok")
        mock_urlopen.assert_called_once()

    @patch("bridge.cursor_quota.urllib.request.urlopen")
    def test_provider_fetch_auth_error(self, mock_urlopen: MagicMock) -> None:
        mock_auth = MagicMock()
        mock_auth.get_session.side_effect = AuthenticationError("Keychain item not found")

        provider = CursorQuotaProvider(auth_manager=mock_auth)
        snapshot = provider.fetch()
        self.assertEqual(snapshot.status, "unavailable")
        self.assertIn("Keychain item not found", snapshot.error or "")

    @patch("bridge.cursor_quota.urllib.request.urlopen")
    def test_provider_fetch_http_401(self, mock_urlopen: MagicMock) -> None:
        import urllib.error
        mock_auth = MagicMock()
        mock_auth.get_session.return_value = CursorSession(
            raw_token="raw.jwt",
            subject="sub_123",
            expiry=time.time() + 3600,
        )
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://cursor.com/api/usage-summary",
            code=401,
            msg="Unauthorized",
            hdrs=MagicMock(),
            fp=None,
        )

        provider = CursorQuotaProvider(auth_manager=mock_auth)
        snapshot = provider.fetch()
        self.assertEqual(snapshot.status, "error")
        self.assertIn("expired", snapshot.error or "")
        mock_auth.invalidate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
