"""Tests for Antigravity model availability filtering used by client setup."""

import unittest
from unittest import mock

from bridge.setup.availability import (
    fetch_agy_available_models,
    split_by_availability,
    with_bridge_aliases,
)


class TestSplitByAvailability(unittest.TestCase):
    def setUp(self):
        self.entries = [
            ("gemini-4-argon-high", {"id": "gemini-4-argon-high"}),
            ("claude-sonnet-5-5-high", {"id": "claude-sonnet-5-5-high"}),
            ("gemini-2.5-pro", {"id": "gemini-2.5-pro"}),
        ]

    def test_filters_out_models_absent_from_catalog(self):
        kept, skipped = split_by_availability(
            self.entries, {"gemini-4-argon-high", "gemini-2.5-pro"}
        )
        self.assertEqual(
            kept,
            [
                ("gemini-4-argon-high", {"id": "gemini-4-argon-high"}),
                ("gemini-2.5-pro", {"id": "gemini-2.5-pro"}),
            ],
        )
        self.assertEqual(skipped, ["claude-sonnet-5-5-high"])

    def test_keeps_original_order(self):
        kept, _ = split_by_availability(
            [("b", 1), ("a", 2), ("c", 3)], {"a", "b", "c"}
        )
        self.assertEqual(kept, [("b", 1), ("a", 2), ("c", 3)])

    def test_unknown_availability_keeps_everything(self):
        kept, skipped = split_by_availability(self.entries, None)
        self.assertEqual(kept, self.entries)
        self.assertEqual(skipped, [])

    def test_empty_kept_when_catalog_shares_nothing(self):
        kept, skipped = split_by_availability(self.entries, {"some-other-model"})
        self.assertEqual(kept, [])
        self.assertEqual(skipped, ["gemini-4-argon-high", "claude-sonnet-5-5-high", "gemini-2.5-pro"])

    def test_all_models_skipped_are_reported_in_order(self):
        _, skipped = split_by_availability(self.entries, set())
        self.assertEqual(
            skipped, ["gemini-4-argon-high", "claude-sonnet-5-5-high", "gemini-2.5-pro"]
        )


class TestWithBridgeAliases(unittest.TestCase):
    def test_adds_aliases_whose_target_is_servable(self):
        expanded = with_bridge_aliases({"gemini-3.8-flash-tiered"})
        self.assertIn("gemini-3.8", expanded)
        self.assertIn("gemini-3.8-flash-high", expanded)
        self.assertIn("gemini-3.8-flash-tiered", expanded)

    def test_does_not_add_aliases_whose_target_is_unservable(self):
        expanded = with_bridge_aliases({"gemini-3.8-flash-tiered"})
        self.assertNotIn("gemini-3.8-pro", expanded)
        self.assertNotIn("gemini-4-argon-high", expanded)
        self.assertNotIn("argon", expanded)

    def test_catalog_ids_are_preserved(self):
        catalog = {"gemini-2.5-pro", "claude-opus-5-5-high"}
        expanded = with_bridge_aliases(catalog)
        self.assertTrue(catalog.issubset(expanded))


class TestFetchAgyAvailableModels(unittest.TestCase):
    def test_returns_catalog_ids_plus_servable_aliases(self):
        client = mock.Mock()
        client.load_code_assist.return_value = {"project": "p"}
        client.fetch_available_models.return_value = [
            {"id": "gemini-4-argon-high"},
            {"id": "claude-sonnet-5-5-high"},
        ]
        with mock.patch("bridge.client.CloudCodeClient", return_value=client), \
             mock.patch("bridge.auth.KeychainTokenProvider"):
            result = fetch_agy_available_models()
        self.assertTrue({"gemini-4-argon-high", "claude-sonnet-5-5-high"}.issubset(result))
        # Bridge aliases whose target is served must survive filtering.
        self.assertIn("argon", result)
        self.assertIn("gemini-4-argon", result)
        self.assertIn("claude-sonnet-5-5", result)
        # And aliases of unserved targets must not appear.
        self.assertNotIn("gemini-3.8", result)

    def test_returns_catalog_ids(self):
        client = mock.Mock()
        client.load_code_assist.return_value = {"project": "aicode-consumers"}
        client.fetch_available_models.return_value = [
            {"id": "gemini-4-argon-high"},
            {"id": "claude-sonnet-5-5-high"},
            {"name": "no-id"},
        ]
        with mock.patch("bridge.client.CloudCodeClient", return_value=client), \
             mock.patch("bridge.auth.KeychainTokenProvider"):
            result = fetch_agy_available_models()
        self.assertTrue(
            {"gemini-4-argon-high", "claude-sonnet-5-5-high"}.issubset(result)
        )
        self.assertNotIn("no-id", result)
        client.fetch_available_models.assert_called_once_with("aicode-consumers")

    def test_returns_none_when_project_missing(self):
        client = mock.Mock()
        client.load_code_assist.return_value = {"project": ""}
        with mock.patch("bridge.client.CloudCodeClient", return_value=client), \
             mock.patch("bridge.auth.KeychainTokenProvider"):
            self.assertIsNone(fetch_agy_available_models())
        client.fetch_available_models.assert_not_called()

    def test_returns_none_when_catalog_empty(self):
        client = mock.Mock()
        client.load_code_assist.return_value = {"project": "p"}
        client.fetch_available_models.return_value = []
        with mock.patch("bridge.client.CloudCodeClient", return_value=client), \
             mock.patch("bridge.auth.KeychainTokenProvider"):
            self.assertIsNone(fetch_agy_available_models())

    def test_returns_none_on_credential_failure(self):
        with mock.patch(
            "bridge.auth.KeychainTokenProvider",
            side_effect=RuntimeError("no keychain entry"),
        ):
            self.assertIsNone(fetch_agy_available_models())

    def test_returns_none_on_upstream_failure(self):
        client = mock.Mock()
        client.load_code_assist.side_effect = ConnectionError("offline")
        with mock.patch("bridge.client.CloudCodeClient", return_value=client), \
             mock.patch("bridge.auth.KeychainTokenProvider"):
            self.assertIsNone(fetch_agy_available_models())

    def test_timeout_is_forwarded_to_client(self):
        client = mock.Mock()
        client.load_code_assist.return_value = {"project": "p"}
        client.fetch_available_models.return_value = [{"id": "m"}]
        with mock.patch("bridge.client.CloudCodeClient", return_value=client) as ctor, \
             mock.patch("bridge.auth.KeychainTokenProvider"):
            fetch_agy_available_models(timeout=3.5)
        self.assertEqual(ctor.call_args.kwargs.get("timeout"), 3.5)


if __name__ == "__main__":
    unittest.main()
