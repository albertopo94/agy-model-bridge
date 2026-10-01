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
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=27)

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
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=10)

        # Dark mode styling elements
        self.assertTrue("#0f172a" in html or "#000000" in html or "background" in html)
        self.assertIn("<style>", html)
        self.assertIn("monospace", html)

    def test_restore_configuration_blocks(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=20)

        # Restore section heading in supported cards
        self.assertIn("Restaurar configuración", html)
        self.assertIn("agy-bridge restore-claude", html)
        self.assertIn("agy-bridge restore-codex", html)

        # Copy buttons and pre IDs for restore
        self.assertIn('id="claude-restore"', html)
        self.assertIn("copySnippet(this, 'claude-restore')", html)
        self.assertIn('id="codex-restore"', html)
        self.assertIn("copySnippet(this, 'codex-restore')", html)

    def test_render_dashboard_vercel_styling_and_responsive_grid(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=10)

        # Vercel dark surfaces
        self.assertIn("#000000", html)
        self.assertIn("#111111", html)
        self.assertIn("#222222", html)

        # 16px card border radius
        self.assertIn("border-radius: 16px", html)

        # 2-column grid and 768px responsive fallback
        self.assertIn("repeat(2, minmax(0, 1fr))", html)
        self.assertIn("@media", html)
        self.assertIn("768px", html)

    def test_status_badges_healthy_state(self):
        auth_status = {"status": "Valid", "email": "user@google.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=27)

        # Address badge
        self.assertIn("127.0.0.1:24980", html)
        # Keychain Auth badge
        self.assertIn("Valid", html)
        self.assertIn("user@google.com", html)
        # Models count badge
        self.assertIn("27 Models Discovered", html)

    def test_github_header_link(self):
        auth_status = {"status": "Valid", "email": "user@google.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=27)

        self.assertIn("https://github.com/albertopo94/agy-model-bridge", html)
        self.assertIn('class="github-link"', html)
        self.assertIn('class="github-icon"', html)
        self.assertIn('target="_blank"', html)
        self.assertIn('rel="noopener noreferrer"', html)

    def test_status_badges_degraded_state(self):
        for status in ("Expired", "Missing"):
            with self.subTest(status=status):
                auth_status = {"status": status, "email": None, "message": "Open Antigravity to refresh"}
                html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=0)

                self.assertIn(status, html)
                self.assertIn("Open Antigravity to refresh", html)

    def test_interactive_setup_cards(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=20)

        # All 4 client cards
        self.assertIn("Claude Code", html)
        self.assertIn("Codex CLI", html)
        self.assertIn("Hermes Agent", html)
        self.assertIn("FreeLLMAPI", html)

        # Two-tier headings
        self.assertIn("Configuración automática", html)
        self.assertIn("Conexión manual", html)

        # Base URLs for Anthropic (without /v1) and OpenAI-compatible (with /v1)
        self.assertIn("http://127.0.0.1:24980", html)
        self.assertIn("http://127.0.0.1:24980/v1", html)

        # Setup commands and keywords (100% native, zero external package dependencies)
        self.assertIn("agy-bridge setup-claude", html)
        self.assertIn("agy-bridge setup-codex", html)
        self.assertNotIn("ANTHROPIC_CUSTOM_MODEL_OPTION", html)
        self.assertNotIn("mkdir -p ~/.codex", html)

        # Claude Code mascot icon and Codex CLI icon
        self.assertIn('class="card-icon"', html)
        self.assertIn("#d77757", html)
        self.assertIn("#ffc400", html)
        self.assertIn("codex-linear-gradient", html)
        self.assertIn('viewBox="0 0 270.35 270.35"', html)
        self.assertIn("export OPENAI_BASE_URL", html)
        self.assertNotIn("npx freellmapi setup", html)
        self.assertIn("BASE_URL", html)
        self.assertIn("API_KEY", html)

        # Refined manual configuration snippets (checked both in unescaped HTML and CLIENT_CARDS)
        import html as html_lib
        unescaped_html = html_lib.unescape(html)
        self.assertIn('# ~/.codex/config.toml\n[model]\nwire_api = "responses"\nbase_url = "http://127.0.0.1:24980/v1"', unescaped_html)
        self.assertIn('export ANTHROPIC_BASE_URL="http://127.0.0.1:24980"\nexport ANTHROPIC_AUTH_TOKEN="local-bridge"', unescaped_html)
        self.assertIn('export OPENAI_BASE_URL="http://127.0.0.1:24980/v1"\nexport OPENAI_API_KEY="local-bridge"', unescaped_html)
        self.assertIn('BASE_URL=http://127.0.0.1:24980/v1\nAPI_KEY=local-bridge', unescaped_html)

        # Clipboard copy functionality

        self.assertIn("<script>", html)
        self.assertIn("navigator.clipboard", html)
        self.assertIn("copy", html.lower())

    def test_interactive_copy_handlers_and_doc_links(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=20)

        # 10 independent snippet IDs and corresponding copy button calls
        expected_ids = [
            "claude-auto", "claude-manual", "claude-restore",
            "codex-auto", "codex-manual", "codex-restore",
            "hermes-auto", "hermes-manual",
            "freellmapi-auto", "freellmapi-manual",
        ]
        for snippet_id in expected_ids:
            with self.subTest(snippet_id=snippet_id):
                self.assertIn(f'id="{snippet_id}"', html)
                self.assertIn(f"copySnippet(this, '{snippet_id}')", html)

        # External doc links
        self.assertIn("Documentación ↗", html)
        self.assertIn('target="_blank"', html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertIn("https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview", html)
        self.assertIn("https://github.com/openai/codex", html)
        self.assertIn("https://hermes-agent.nousresearch.com", html)
        self.assertIn("https://github.com/tashfeenahmed/freellmapi", html)

        # Robust clipboard JavaScript
        self.assertIn("function copySnippet(btn, elementId)", html)
        self.assertIn("function fallbackCopy(el, btn)", html)
        self.assertIn("execCommand", html)
        self.assertIn('if (btn.classList.contains("copied")) return;', html)
        self.assertIn('window.getSelection().removeAllRanges()', html)


    def test_client_cards_schema(self):
        from bridge.dashboard import CLIENT_CARDS
        self.assertEqual(len(CLIENT_CARDS), 4)
        card_titles = [c["title"] for c in CLIENT_CARDS]
        self.assertIn("Claude Code", card_titles)
        self.assertIn("Codex CLI", card_titles)
        self.assertIn("Hermes Agent", card_titles)
        self.assertIn("FreeLLMAPI", card_titles)

        by_id = {c["id"]: c for c in CLIENT_CARDS}
        self.assertEqual(
            by_id["codex"]["auto_cmd"]("127.0.0.1:24980"),
            "agy-bridge setup-codex",
        )
        self.assertEqual(
            by_id["codex"]["auto_cmd"]("127.0.0.1:9090"),
            "agy-bridge setup-codex --port 9090",
        )
        self.assertEqual(
            by_id["codex"]["restore_cmd"]("127.0.0.1:24980"),
            "agy-bridge restore-codex",
        )
        self.assertEqual(
            by_id["codex"]["manual_snippet"]("127.0.0.1:24980"),
            '# ~/.codex/config.toml\n[model]\nwire_api = "responses"\nbase_url = "http://{addr}/v1"'.replace("{addr}", "127.0.0.1:24980"),
        )
        self.assertEqual(by_id["codex"]["docs_url"], "https://github.com/openai/codex")

        self.assertEqual(
            by_id["claude"]["auto_cmd"]("127.0.0.1:24980"),
            "agy-bridge setup-claude",
        )
        self.assertEqual(
            by_id["claude"]["auto_cmd"]("127.0.0.1:9090"),
            "agy-bridge setup-claude --port 9090",
        )
        self.assertEqual(
            by_id["claude"]["restore_cmd"]("127.0.0.1:24980"),
            "agy-bridge restore-claude",
        )
        self.assertEqual(
            by_id["claude"]["manual_snippet"]("127.0.0.1:24980"),
            'export ANTHROPIC_BASE_URL="http://127.0.0.1:24980"\nexport ANTHROPIC_AUTH_TOKEN="local-bridge"',
        )
        self.assertEqual(
            by_id["claude"]["docs_url"],
            "https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview",
        )

        self.assertEqual(
            by_id["hermes"]["auto_cmd"]("127.0.0.1:24980"),
            'export OPENAI_BASE_URL="http://127.0.0.1:24980/v1" OPENAI_API_KEY="local-bridge" && hermes',
        )
        self.assertEqual(
            by_id["hermes"]["manual_snippet"]("127.0.0.1:24980"),
            'export OPENAI_BASE_URL="http://127.0.0.1:24980/v1"\nexport OPENAI_API_KEY="local-bridge"',
        )
        self.assertEqual(by_id["hermes"]["docs_url"], "https://hermes-agent.nousresearch.com")

        self.assertEqual(
            by_id["freellmapi"]["auto_cmd"]("127.0.0.1:24980"),
            'http://127.0.0.1:24980/v1',
        )
        self.assertEqual(
            by_id["freellmapi"]["manual_snippet"]("127.0.0.1:24980"),
            'BASE_URL=http://127.0.0.1:24980/v1\nAPI_KEY=local-bridge',
        )
        self.assertEqual(by_id["freellmapi"]["docs_url"], "https://github.com/tashfeenahmed/freellmapi")


    def test_render_dashboard_host_0000_and_ipv6_substitutes_127001_in_snippets(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        for wildcard in ("0.0.0.0", "::", ""):
            with self.subTest(host=wildcard):
                html = render_dashboard(wildcard, 24980, auth_status, models_count=5)
                # Header badge keeps the listen address
                self.assertIn(f"🌐 {wildcard}:24980", html)
                # Snippets substitute 127.0.0.1
                self.assertIn("http://127.0.0.1:24980", html)
                self.assertIn("http://127.0.0.1:24980/v1", html)
                if wildcard:
                    self.assertNotIn(f"http://{wildcard}:24980", html)


class TestDashboardStatusData(unittest.TestCase):
    def setUp(self):
        from bridge.dashboard import _models_cache
        _models_cache.clear()

    def test_get_status_data_healthy(self):
        provider = MockTokenProvider(token="valid-tok", account="test@domain.com")
        client = MockClient(token_provider=provider, models=["m1", "m2", "m3"])

        data = get_status_data(client, "test-project", "127.0.0.1", 24980)
        self.assertEqual(data["host"], "127.0.0.1")
        self.assertEqual(data["port"], 24980)
        self.assertEqual(data["address"], "127.0.0.1:24980")
        self.assertEqual(data["auth"]["status"], "Valid")
        self.assertEqual(data["auth"]["email"], "test@domain.com")
        self.assertEqual(data["models_count"], 3)

    def test_get_status_data_cached_expiry_past_marks_expired(self):
        import time
        provider = MockTokenProvider(token="valid-tok", account="test@domain.com")
        provider._cached_expiry = time.time() - 30.0  # Expired 30 seconds ago
        client = MockClient(token_provider=provider)

        data = get_status_data(client, "test-project", "127.0.0.1", 24980)
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

        data = get_status_data(client, "test-project", "127.0.0.1", 24980)
        self.assertEqual(data["models_count"], 0)

    def test_get_status_data_models_error_negative_caching(self):
        from bridge.dashboard import _models_cache
        provider = MockTokenProvider()
        client = MockClient(token_provider=provider, fail_models=Exception("Upstream timeout"))

        get_status_data(client, "cached-proj", "127.0.0.1", 24980)
        self.assertIn("cached-proj", _models_cache)
        entry = _models_cache["cached-proj"]
        self.assertEqual(entry[1], 0)

    def test_get_status_data_models_error_negative_caching_on_expired_entry(self):
        import time
        from bridge.dashboard import _models_cache
        provider = MockTokenProvider()
        client = MockClient(token_provider=provider, fail_models=Exception("Upstream timeout"))

        # Seed cache with an expired entry (70 seconds ago) with count 15
        now = time.time()
        _models_cache["expired-proj"] = (now - 70.0, 15)

        data = get_status_data(client, "expired-proj", "127.0.0.1", 24980)
        self.assertEqual(data["models_count"], 15)
        # Verify negative caching: cache entry updated to now - 45.0 (giving 15s negative cache window)
        entry = _models_cache["expired-proj"]
        self.assertEqual(entry[1], 15)
        self.assertAlmostEqual(entry[0], now - 45.0, delta=2.0)


class TestDashboardBilingual(unittest.TestCase):
    def test_render_dashboard_language_switcher_markup(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=10, lang="en")

        # Language switcher buttons
        self.assertIn("lang-switcher", html)
        self.assertIn('id="btn-lang-en"', html)
        self.assertIn('id="btn-lang-es"', html)
        self.assertIn("setLanguage('en')", html)
        self.assertIn("setLanguage('es')", html)

    def test_render_dashboard_english(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=10, lang="en")

        self.assertIn('<html lang="en">', html)
        self.assertIn("Zero-dependency multi-protocol gateway", html)
        self.assertIn("Automatic configuration", html)
        self.assertIn("Manual connection", html)
        self.assertIn("Restore configuration", html)
        self.assertIn("10 Models Discovered", html)

    def test_render_dashboard_spanish(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=10, lang="es")

        self.assertIn('<html lang="es">', html)
        self.assertIn("Gateway multiprotocolo sin dependencias", html)
        self.assertIn("Configuración automática", html)
        self.assertIn("Conexión manual", html)
        self.assertIn("Restaurar configuración", html)
        self.assertIn("10 Modelos Descubiertos", html)

    def test_render_dashboard_client_side_i18n_script(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=10)

        # Client-side dynamic language switcher
        self.assertIn("localStorage.getItem(\"agy_lang\")", html)
        self.assertIn("localStorage.setItem(\"agy_lang\"", html)
        self.assertIn("setLanguage", html)
        self.assertIn("I18N", html)


if __name__ == "__main__":
    unittest.main()
