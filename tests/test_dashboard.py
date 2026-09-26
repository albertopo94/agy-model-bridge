"""Unit tests for the embedded local gateway dashboard and status endpoints."""

import unittest
from bridge.dashboard import render_dashboard, get_status_data


class MockTokenProvider:
    def __init__(self, token: str = "test-token", account: str = "antigravity@test.com", fail_with: Exception | None = None):
        self.token = token
        self.account = account
        self.fail_with = fail_with

    def get_token(self) -> str:
        if self.fail_with:
            raise self.fail_with
        return self.token


class MockClient:
    def __init__(self, token_provider: MockTokenProvider | None = None, models: list[str] | None = None, fail_models: Exception | None = None):
        self.token_provider = token_provider or MockTokenProvider()
        self.models = models if models is not None else ["gemini-2.5-pro", "gemini-2.5-flash"]
        self.fail_models = fail_models

    def fetch_available_models(self, project: str) -> list[str]:
        if self.fail_models:
            raise self.fail_models
        return self.models


class TestDashboardRendering(unittest.TestCase):
    def test_render_dashboard_html_structure(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 8080, auth_status, models_count=27)

        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("<html", html)
        self.assertIn("<head>", html)
        self.assertIn("<body>", html)
        self.assertIn("</html>", html)
        # Self-contained zero external CDN
        self.assertNotIn("https://cdn.", html)
        self.assertNotIn("https://cdnjs.", html)
        self.assertNotIn("https://unpkg.com", html)

    def test_render_dashboard_styling(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 8080, auth_status, models_count=10)

        # Dark mode styling elements
        self.assertTrue("#0f172a" in html or "#000000" in html or "background" in html)
        self.assertIn("<style>", html)
        self.assertIn("monospace", html)

    def test_status_badges_healthy_state(self):
        auth_status = {"status": "Valid", "email": "user@google.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 8080, auth_status, models_count=27)

        # Address badge
        self.assertIn("127.0.0.1:8080", html)
        # Keychain Auth badge
        self.assertIn("Valid", html)
        self.assertIn("user@google.com", html)
        # Models count badge
        self.assertIn("27 Models Discovered", html)

    def test_status_badges_degraded_state(self):
        for status in ("Expired", "Missing"):
            with self.subTest(status=status):
                auth_status = {"status": status, "email": None, "message": "Open Antigravity to refresh"}
                html = render_dashboard("127.0.0.1", 8080, auth_status, models_count=0)

                self.assertIn(status, html)
                self.assertIn("Open Antigravity to refresh", html)

    def test_interactive_setup_cards(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 8080, auth_status, models_count=20)

        # Card 1: FreeLLMAPI Bridge with /v1
        self.assertIn("FreeLLMAPI", html)
        self.assertIn("http://127.0.0.1:8080/v1", html)

        # Card 2: Claude Code Direct without /v1
        self.assertIn("Claude Code", html)
        self.assertIn("http://127.0.0.1:8080", html)
        self.assertIn("ANTHROPIC_BASE_URL", html)
        self.assertIn("ANTHROPIC_AUTH_TOKEN", html)
        self.assertIn("ANTHROPIC_CUSTOM_MODEL_OPTION", html)
        self.assertIn("CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY", html)

        # Card 3: Codex / Hermes / Aider Direct with /v1
        self.assertIn("Codex", html)
        self.assertIn('wire_api = "responses"', html)

        # Clipboard copy functionality
        self.assertIn("<script>", html)
        self.assertIn("navigator.clipboard", html)
        self.assertIn("copy", html.lower())

    def test_render_dashboard_host_0000_and_ipv6_substitutes_127001_in_snippets(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        for wildcard in ("0.0.0.0", "::", ""):
            with self.subTest(host=wildcard):
                html = render_dashboard(wildcard, 8080, auth_status, models_count=5)
                # Header badge keeps the listen address
                self.assertIn(f"🌐 {wildcard}:8080", html)
                # Snippets substitute 127.0.0.1
                self.assertIn("http://127.0.0.1:8080/v1/chat/completions", html)
                self.assertIn("ANTHROPIC_BASE_URL", html)
                self.assertIn("http://127.0.0.1:8080", html)
                self.assertIn("http://127.0.0.1:8080/v1", html)
                if wildcard:
                    self.assertNotIn(f"http://{wildcard}:8080", html)


class TestDashboardStatusData(unittest.TestCase):
    def setUp(self):
        from bridge.dashboard import _models_cache
        _models_cache.clear()

    def test_get_status_data_healthy(self):
        provider = MockTokenProvider(token="valid-tok", account="test@domain.com")
        client = MockClient(token_provider=provider, models=["m1", "m2", "m3"])

        data = get_status_data(client, "test-project", "127.0.0.1", 8080)
        self.assertEqual(data["host"], "127.0.0.1")
        self.assertEqual(data["port"], 8080)
        self.assertEqual(data["address"], "127.0.0.1:8080")
        self.assertEqual(data["auth"]["status"], "Valid")
        self.assertEqual(data["auth"]["email"], "test@domain.com")
        self.assertEqual(data["models_count"], 3)

    def test_get_status_data_cached_expiry_past_marks_expired(self):
        import time
        provider = MockTokenProvider(token="valid-tok", account="test@domain.com")
        provider._cached_expiry = time.time() - 30.0  # Expired 30 seconds ago
        client = MockClient(token_provider=provider)

        data = get_status_data(client, "test-project", "127.0.0.1", 8080)
        self.assertEqual(data["auth"]["status"], "Expired")
        self.assertIn("Open Antigravity to refresh", data["auth"]["message"])

    def test_get_status_data_expired_token(self):
        provider = MockTokenProvider(fail_with=Exception("Token expired 300s ago"))
        client = MockClient(token_provider=provider)

        data = get_status_data(client, "test-project", "127.0.0.1", 9000)
        self.assertEqual(data["auth"]["status"], "Expired")
        self.assertIn("Open Antigravity to refresh", data["auth"]["message"])

    def test_get_status_data_missing_token(self):
        provider = MockTokenProvider(fail_with=Exception("No credentials found in keychain"))
        client = MockClient(token_provider=provider)

        data = get_status_data(client, "test-project", "127.0.0.1", 9000)
        self.assertEqual(data["auth"]["status"], "Missing")
        self.assertIn("Open Antigravity to refresh", data["auth"]["message"])

    def test_get_status_data_models_error_degrades_gracefully(self):
        provider = MockTokenProvider()
        client = MockClient(token_provider=provider, fail_models=Exception("Upstream timeout"))

        data = get_status_data(client, "test-project", "127.0.0.1", 8080)
        self.assertEqual(data["models_count"], 0)

    def test_get_status_data_models_error_negative_caching(self):
        from bridge.dashboard import _models_cache
        provider = MockTokenProvider()
        client = MockClient(token_provider=provider, fail_models=Exception("Upstream timeout"))

        get_status_data(client, "cached-proj", "127.0.0.1", 8080)
        self.assertIn("cached-proj", _models_cache)
        entry = _models_cache["cached-proj"]
        self.assertEqual(entry[1], 0)


if __name__ == "__main__":
    unittest.main()
