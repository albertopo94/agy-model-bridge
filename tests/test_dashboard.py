"""Unit tests for the embedded local gateway dashboard and status endpoints."""

import html
import unittest
from bridge import __version__
from bridge.dashboard import render_dashboard, get_status_data


class MockTokenProvider:
    def __init__(
        self,
        token: str = "test-token",
        account: str = "antigravity@test.com",
        fail_with: Exception | None = None,
        expiry: float = 0.0,
    ):
        self.token = token
        self.account = account
        self.fail_with = fail_with
        self._expiry = expiry

    @property
    def expiry(self) -> float:
        return self._expiry

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
        self.assertIn("agy-bridge restore-hermes", html)
        self.assertIn("agy-bridge restore-opencode", html)
        self.assertIn("agy-bridge restore-openclaw", html)
        self.assertIn("agy-bridge restore-pi", html)
        self.assertIn("agy-bridge restore-gentle-shell", html)

        # Copy buttons and pre IDs for restore
        self.assertIn('id="claude-restore"', html)
        self.assertIn("copySnippet(this, 'claude-restore')", html)
        self.assertIn('id="codex-restore"', html)
        self.assertIn("copySnippet(this, 'codex-restore')", html)
        self.assertIn('id="hermes-restore"', html)
        self.assertIn("copySnippet(this, 'hermes-restore')", html)
        self.assertIn('id="opencode-restore"', html)
        self.assertIn("copySnippet(this, 'opencode-restore')", html)
        self.assertIn('id="openclaw-restore"', html)
        self.assertIn("copySnippet(this, 'openclaw-restore')", html)
        self.assertIn('id="pi-restore"', html)
        self.assertIn("copySnippet(this, 'pi-restore')", html)
        self.assertIn('id="gentle-shell-restore"', html)
        self.assertIn("copySnippet(this, 'gentle-shell-restore')", html)

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

        # All 6 client cards
        self.assertIn("Claude Code", html)
        self.assertIn("Codex CLI", html)
        self.assertIn("Hermes Agent", html)
        self.assertIn("OpenCode", html)
        self.assertIn("OpenClaw", html)
        self.assertIn("Pi", html)
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
        self.assertIn("agy-bridge setup-hermes", html)
        self.assertIn("agy-bridge setup-opencode", html)
        self.assertIn("agy-bridge setup-openclaw", html)
        self.assertIn("agy-bridge setup-pi", html)
        self.assertIn('class="card-tip"', html)
        self.assertIn('data-i18n="tip_pi"', html)
        self.assertNotIn("ANTHROPIC_CUSTOM_MODEL_OPTION", html)
        self.assertNotIn("mkdir -p ~/.codex", html)

        # Mascot and client icons
        self.assertIn('class="card-icon"', html)
        self.assertIn("#d77757", html)
        self.assertIn("#ffc400", html)
        self.assertIn("codex-linear-gradient", html)
        self.assertIn('viewBox="0 0 270.35 270.35"', html)
        self.assertIn('viewBox="0 0 24 24"', html)
        self.assertIn('viewBox="0 0 470 470"', html)
        self.assertIn('viewBox="0 0 64 64"', html)
        self.assertNotIn("npx freellmapi setup-claude", html)
        self.assertNotIn("npx freellmapi setup-codex", html)
        self.assertNotIn('id="freellmapi-auto"', html)
        self.assertIn("BASE_URL", html)
        self.assertIn("API_KEY", html)

        # Refined manual configuration snippets (checked both in unescaped HTML and CLIENT_CARDS)
        import html as html_lib
        unescaped_html = html_lib.unescape(html)
        expected_codex_toml = (
            '# ~/.codex/config.toml\n'
            '# Replace <YOUR_API_KEY> with key from ~/.agy-bridge/api_key\n'
            'model = "gemini-3.8-flash-high"\n'
            'model_provider = "agy"\n'
            'model_context_window = 1048576\n'
            'model_auto_compact_token_limit = 943718\n\n'
            '[model_providers.agy]\n'
            'name = "agy"\n'
            'base_url = "http://127.0.0.1:24980/v1"\n'
            'wire_api = "responses"\n'
            'requires_openai_auth = false\n'
            'http_headers = { Authorization = "Bearer <YOUR_API_KEY>" }'
        )
        self.assertIn(expected_codex_toml, unescaped_html)
        self.assertIn('export ANTHROPIC_BASE_URL="http://127.0.0.1:24980"\nexport ANTHROPIC_AUTH_TOKEN="$(cat ~/.agy-bridge/api_key)"', unescaped_html)
        expected_hermes_snippet = 'BASE_URL=http://127.0.0.1:24980/v1\nAPI_KEY="$(cat ~/.agy-bridge/api_key)"'
        self.assertIn(expected_hermes_snippet, unescaped_html)
        self.assertIn('BASE_URL=http://127.0.0.1:24980/v1\nAPI_KEY="$(cat ~/.agy-bridge/api_key)"', unescaped_html)

        # Clipboard copy functionality

        self.assertIn("<script>", html)
        self.assertIn("navigator.clipboard", html)
        self.assertIn("copy", html.lower())

    def test_interactive_copy_handlers_and_doc_links(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=20)

        # 24 independent snippet IDs and corresponding copy button calls
        expected_ids = [
            "claude-auto", "claude-manual", "claude-restore",
            "codex-auto", "codex-manual", "codex-restore",
            "hermes-auto", "hermes-manual", "hermes-restore",
            "opencode-auto", "opencode-manual", "opencode-restore",
            "openclaw-auto", "openclaw-manual", "openclaw-restore",
            "cursor-auto", "cursor-manual",
            "pi-auto", "pi-manual", "pi-restore",
            "gentle-shell-auto", "gentle-shell-manual", "gentle-shell-restore",
            "freellmapi-manual",
        ]
        for snippet_id in expected_ids:
            with self.subTest(snippet_id=snippet_id):
                self.assertIn(f'id="{snippet_id}"', html)
                self.assertIn(f"copySnippet(this, '{snippet_id}')", html)

        self.assertNotIn('id="cursor-restore"', html)
        self.assertNotIn("copySnippet(this, 'cursor-restore')", html)
        self.assertNotIn('id="freellmapi-auto"', html)
        self.assertNotIn("copySnippet(this, 'freellmapi-auto')", html)

        # External doc links
        self.assertIn("Documentación ↗", html)
        self.assertIn('target="_blank"', html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertIn("https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview", html)
        self.assertIn("https://github.com/openai/codex", html)
        self.assertIn("https://hermes-agent.nousresearch.com", html)
        self.assertIn("https://opencode.ai/docs", html)
        self.assertIn("https://docs.openclaw.ai/gateway/config-tools/custom-providers", html)
        self.assertIn("https://pi.dev/docs/latest", html)
        self.assertIn("https://github.com/Gentleman-Programming/gentle-shell", html)
        self.assertIn("https://github.com/tashfeenahmed/freellmapi", html)

        # Robust clipboard JavaScript
        self.assertIn("function copySnippet(btn, elementId)", html)
        self.assertIn("function fallbackCopy(el, btn)", html)
        self.assertIn("execCommand", html)
        self.assertIn('if (btn.classList.contains("copied")) return;', html)
        self.assertIn('window.getSelection().removeAllRanges()', html)


    def test_client_cards_schema(self):
        from bridge.dashboard import CLIENT_CARDS
        self.assertEqual(len(CLIENT_CARDS), 9)
        card_titles = [c["title"] for c in CLIENT_CARDS]
        self.assertIn("Claude Code", card_titles)
        self.assertIn("Codex CLI", card_titles)
        self.assertIn("Hermes Agent", card_titles)
        self.assertIn("OpenCode", card_titles)
        self.assertIn("OpenClaw", card_titles)
        self.assertIn("Cursor", card_titles)
        self.assertIn("Pi", card_titles)
        self.assertIn("Gentle Shell", card_titles)
        self.assertIn("FreeLLMAPI", card_titles)

        card_ids = [c["id"] for c in CLIENT_CARDS]
        self.assertEqual(card_ids, ["claude", "codex", "hermes", "pi", "gentle-shell", "opencode", "openclaw", "cursor", "freellmapi"])

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
            (
                '# ~/.codex/config.toml\n'
                '# Replace <YOUR_API_KEY> with key from ~/.agy-bridge/api_key\n'
                'model = "gemini-3.8-flash-high"\n'
                'model_provider = "agy"\n'
                'model_context_window = 1048576\n'
                'model_auto_compact_token_limit = 943718\n\n'
                '[model_providers.agy]\n'
                'name = "agy"\n'
                'base_url = "http://127.0.0.1:24980/v1"\n'
                'wire_api = "responses"\n'
                'requires_openai_auth = false\n'
                'http_headers = { Authorization = "Bearer <YOUR_API_KEY>" }'
            ),
        )
        # Shell expansion placeholder in api_key falls back to <YOUR_API_KEY> in TOML
        self.assertIn(
            'Authorization = "Bearer <YOUR_API_KEY>"',
            by_id["codex"]["manual_snippet"]("127.0.0.1:24980", api_key='$(cat ~/.agy-bridge/api_key)'),
        )
        # Explicit key is preserved in TOML
        self.assertIn(
            'Authorization = "Bearer explicit-key-abc"',
            by_id["codex"]["manual_snippet"]("127.0.0.1:24980", api_key='explicit-key-abc'),
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
            'export ANTHROPIC_BASE_URL="http://127.0.0.1:24980"\nexport ANTHROPIC_AUTH_TOKEN="$(cat ~/.agy-bridge/api_key)"',
        )
        self.assertEqual(
            by_id["claude"]["docs_url"],
            "https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview",
        )

        self.assertIn('viewBox="0 0 24 24"', by_id["hermes"].get("icon_svg", ""))
        self.assertIn('id="nousresearch-hermes"', by_id["hermes"].get("icon_svg", ""))
        self.assertIn('fill="currentColor"', by_id["hermes"].get("icon_svg", ""))
        self.assertEqual(
            by_id["hermes"]["auto_cmd"]("127.0.0.1:24980"),
            "agy-bridge setup-hermes",
        )
        self.assertEqual(
            by_id["hermes"]["auto_cmd"]("127.0.0.1:9090"),
            "agy-bridge setup-hermes --port 9090",
        )
        self.assertEqual(
            by_id["hermes"]["restore_cmd"]("127.0.0.1:24980"),
            "agy-bridge restore-hermes",
        )
        self.assertEqual(
            by_id["hermes"]["manual_snippet"]("127.0.0.1:24980"),
            'BASE_URL=http://127.0.0.1:24980/v1\nAPI_KEY="$(cat ~/.agy-bridge/api_key)"',
        )
        self.assertEqual(by_id["hermes"]["docs_url"], "https://hermes-agent.nousresearch.com")

        self.assertIn('viewBox="0 0 24 24"', by_id["opencode"].get("icon_svg", ""))
        self.assertEqual(
            by_id["opencode"]["auto_cmd"]("127.0.0.1:24980"),
            "agy-bridge setup-opencode",
        )
        self.assertEqual(
            by_id["opencode"]["auto_cmd"]("127.0.0.1:9090"),
            "agy-bridge setup-opencode --port 9090",
        )
        self.assertEqual(
            by_id["opencode"]["restore_cmd"]("127.0.0.1:24980"),
            "agy-bridge restore-opencode",
        )
        self.assertEqual(
            by_id["opencode"]["manual_snippet"]("127.0.0.1:24980"),
            'BASE_URL=http://127.0.0.1:24980/v1\nAPI_KEY="$(cat ~/.agy-bridge/api_key)"',
        )
        self.assertEqual(by_id["opencode"]["docs_url"], "https://opencode.ai/docs")

        self.assertIn('viewBox="0 0 24 24"', by_id["openclaw"].get("icon_svg", ""))
        self.assertEqual(
            by_id["openclaw"]["auto_cmd"]("127.0.0.1:24980"),
            "agy-bridge setup-openclaw",
        )
        self.assertEqual(
            by_id["openclaw"]["auto_cmd"]("127.0.0.1:9090"),
            "agy-bridge setup-openclaw --port 9090",
        )
        self.assertEqual(
            by_id["openclaw"]["restore_cmd"]("127.0.0.1:24980"),
            "agy-bridge restore-openclaw",
        )
        self.assertEqual(
            by_id["openclaw"]["manual_snippet"]("127.0.0.1:24980"),
            'BASE_URL=http://127.0.0.1:24980/v1\nAPI_KEY="$(cat ~/.agy-bridge/api_key)"',
        )
        self.assertEqual(by_id["openclaw"]["docs_url"], "https://docs.openclaw.ai/gateway/config-tools/custom-providers")

        self.assertIn('viewBox="0 0 24 24"', by_id["cursor"].get("icon_svg", ""))
        self.assertEqual(
            by_id["cursor"]["auto_cmd"]("127.0.0.1:24980"),
            "agy-bridge setup-cursor",
        )
        self.assertEqual(
            by_id["cursor"]["auto_cmd"]("127.0.0.1:9090"),
            "agy-bridge setup-cursor --port 9090",
        )
        self.assertNotIn("restore_cmd", by_id["cursor"])
        self.assertEqual(
            by_id["cursor"]["manual_snippet"]("127.0.0.1:24980"),
            'BASE_URL=http://127.0.0.1:24980/v1\nAPI_KEY="$(cat ~/.agy-bridge/api_key)"',
        )
        self.assertEqual(by_id["cursor"]["docs_url"], "https://docs.cursor.com")

        self.assertIn("pi", by_id)
        self.assertIn('viewBox="0 0 470 470"', by_id["pi"].get("icon_svg", ""))
        self.assertEqual(
            by_id["pi"]["auto_cmd"]("127.0.0.1:24980"),
            "agy-bridge setup-pi",
        )
        self.assertEqual(
            by_id["pi"]["auto_cmd"]("127.0.0.1:9090"),
            "agy-bridge setup-pi --port 9090",
        )
        self.assertEqual(
            by_id["pi"]["restore_cmd"]("127.0.0.1:24980"),
            "agy-bridge restore-pi",
        )
        self.assertEqual(
            by_id["pi"]["manual_snippet"]("127.0.0.1:24980"),
            'BASE_URL=http://127.0.0.1:24980/v1\nAPI_KEY="$(cat ~/.agy-bridge/api_key)"',
        )
        self.assertEqual(by_id["pi"]["docs_url"], "https://pi.dev/docs/latest")
        self.assertIn("tip_en", by_id["pi"])
        self.assertIn("tip_es", by_id["pi"])
        self.assertIn("--set-default", by_id["pi"]["tip_en"])
        self.assertIn("--set-default", by_id["pi"]["tip_es"])

        self.assertIn("gentle-shell", by_id)
        self.assertIn('viewBox="0 0 5000 5000"', by_id["gentle-shell"].get("icon_svg", ""))
        self.assertEqual(
            by_id["gentle-shell"]["auto_cmd"]("127.0.0.1:24980"),
            "agy-bridge setup-gentle-shell",
        )
        self.assertEqual(
            by_id["gentle-shell"]["auto_cmd"]("127.0.0.1:9090"),
            "agy-bridge setup-gentle-shell --port 9090",
        )
        self.assertEqual(
            by_id["gentle-shell"]["restore_cmd"]("127.0.0.1:24980"),
            "agy-bridge restore-gentle-shell",
        )
        self.assertEqual(
            by_id["gentle-shell"]["manual_snippet"]("127.0.0.1:24980"),
            'BASE_URL=http://127.0.0.1:24980/v1\nAPI_KEY="$(cat ~/.agy-bridge/api_key)"',
        )
        self.assertEqual(
            by_id["gentle-shell"]["docs_url"],
            "https://github.com/Gentleman-Programming/gentle-shell",
        )

        self.assertNotIn("auto_cmd", by_id["freellmapi"])
        self.assertIn("icon_svg", by_id["freellmapi"])
        self.assertIn('viewBox="0 0 64 64"', by_id["freellmapi"]["icon_svg"])
        self.assertEqual(
            by_id["freellmapi"]["manual_snippet"]("127.0.0.1:24980"),
            'BASE_URL=http://127.0.0.1:24980/v1\nAPI_KEY="$(cat ~/.agy-bridge/api_key)"',
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
        provider = MockTokenProvider(token="valid-tok", account="test@domain.com", expiry=time.time() - 30.0)
        client = MockClient(token_provider=provider)

        data = get_status_data(client, "test-project", "127.0.0.1", 24980)
        self.assertEqual(data["auth"]["status"], "Expired")
        self.assertIn("Open Antigravity to refresh", data["auth"]["message"])

    def test_get_status_data_ignores_private_cached_expiry_attribute(self):
        import time

        class PrivateOnlyTokenProvider:
            def __init__(self):
                self._cached_expiry = time.time() - 30.0  # Private attribute only

            def get_token(self) -> str:
                return "priv-token"

        provider = PrivateOnlyTokenProvider()
        client = MockClient(token_provider=provider)
        data = get_status_data(client, "test-project", "127.0.0.1", 24980)
        # Without public expiry property, dashboard treats expiry as 0.0 (Valid, not Expired)
        self.assertEqual(data["auth"]["status"], "Valid")

    def test_get_status_data_with_expiry_property_marks_expired(self):
        import time

        class PropertyTokenProvider:
            def __init__(self, exp: float):
                self._exp = exp

            def get_token(self) -> str:
                return "prop-token"

            @property
            def expiry(self) -> float:
                return self._exp

        provider = PropertyTokenProvider(exp=time.time() - 100.0)
        client = MockClient(token_provider=provider)
        data = get_status_data(client, "test-project", "127.0.0.1", 24980)
        self.assertEqual(data["auth"]["status"], "Expired")
        self.assertIn("Open Antigravity to refresh", data["auth"]["message"])

    def test_get_status_data_with_callable_expiry_marks_expired(self):
        import time

        class CallableExpiryTokenProvider:
            def __init__(self, exp: float):
                self._exp = exp

            def get_token(self) -> str:
                return "callable-token"

            def expiry(self) -> float:
                return self._exp

        provider = CallableExpiryTokenProvider(exp=time.time() - 100.0)
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
        self.assertIn(f"AGY Model Bridge &bull; v{__version__} &bull; Local Gateway", html)

    def test_render_dashboard_spanish(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=10, lang="es")

        self.assertIn('<html lang="es">', html)
        self.assertIn("Gateway multiprotocolo sin dependencias", html)
        self.assertIn("Configuración automática", html)
        self.assertIn("Conexión manual", html)
        self.assertIn("Restaurar configuración", html)
        self.assertIn("10 Modelos Descubiertos", html)
        self.assertIn(f"AGY Model Bridge &bull; v{__version__} &bull; Gateway local", html)

    def test_render_dashboard_client_side_i18n_script(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=10)

        # Client-side dynamic language switcher
        self.assertIn("localStorage.getItem(\"agy_lang\")", html)
        self.assertIn("localStorage.setItem(\"agy_lang\"", html)
        self.assertIn("setLanguage", html)
        self.assertIn("I18N", html)

    def test_render_dashboard_never_leaks_api_key(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        secret = "super-secret-test-key-12345-never-leak"
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=10, api_key=secret)
        self.assertNotIn(secret, html)
        self.assertTrue("Configured" in html or "Configurada" in html)

    def test_i18n_dictionary_contains_api_key_and_gentle_shell_translations(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=10)
        # Check there is exactly one 'es: {' definition inside I18N
        i18n_start = html.find("var I18N = {")
        self.assertNotEqual(i18n_start, -1)
        i18n_block = html[i18n_start:html.find("function setLanguage", i18n_start)]
        self.assertEqual(i18n_block.count("es: {"), 1)
        self.assertIn('"desc_gentle-shell"', i18n_block)
        self.assertIn("api_key_configured", i18n_block)
        self.assertIn("api_key_not_required", i18n_block)

    def test_render_dashboard_contains_quota_panel(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=10)

        self.assertIn('<aside class="quota-panel"', html)
        self.assertIn('id="quota-card"', html)
        self.assertIn("Antigravity", html)
        self.assertIn('viewBox="0 0 16 15"', html)
        self.assertIn('id="google-antigravity"', html)
        self.assertIn("fetchQuota", html)
        self.assertIn("/api/quota", html)
        self.assertIn("1280px", html)

    def test_render_dashboard_quota_i18n_keys(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=10)

        required_keys = [
            "quota_title",
            "quota_updated_just_now",
            "quota_updated_minutes",
            "quota_updated_hours",
            "quota_used",
            "quota_resets_in",
            "quota_resets_now",
            "quota_refresh",
            "quota_loading",
            "quota_unavailable",
            "quota_error_stale",
        ]
        for key in required_keys:
            with self.subTest(key=key):
                self.assertIn(f"{key}:", html)

    def test_quota_card_rendering_script_uses_safe_dom_manipulation(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=10)

        start = html.find("function renderQuotaCard")
        self.assertNotEqual(start, -1, "renderQuotaCard function not found in dashboard script")
        end = html.find("function fetchQuota", start)
        self.assertNotEqual(end, -1)
        quota_func_body = html[start:end]

        self.assertNotIn(".innerHTML =", quota_func_body)
        self.assertIn(".textContent =", quota_func_body)

    def test_render_dashboard_quota_spanish_initial_markup(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html_es = render_dashboard("127.0.0.1", 24980, auth_status, models_count=10, lang="es")
        self.assertIn('aria-label="Actualizar cuota"', html_es)
        self.assertIn('title="Actualizar cuota"', html_es)
        self.assertIn("Cargando cuota...", html_es)

        html_en = render_dashboard("127.0.0.1", 24980, auth_status, models_count=10, lang="en")
        self.assertIn('aria-label="Refresh quota"', html_en)
        self.assertIn('title="Refresh quota"', html_en)
        self.assertIn("Loading quota...", html_en)

    def test_render_dashboard_quota_dynamic_localization_script(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html = render_dashboard("127.0.0.1", 24980, auth_status, models_count=10)

        self.assertIn("quota-refresh-btn", html)
        self.assertIn('refreshBtn.setAttribute("aria-label"', html)
        self.assertIn("Modelos Gemini", html)
        self.assertIn("Modelos Claude y GPT", html)
        self.assertIn("Límite semanal restante", html)
        self.assertIn("Límite de 5 horas restante", html)
        self.assertIn(
            "Dentro de cada grupo, los modelos comparten un límite semanal y un límite de 5 horas. "
            "La cuota se consume proporcionalmente al costo de los tokens",
            html,
        )

    def test_gentle_shell_multi_provider_card(self):
        auth_status = {"status": "Valid", "email": "dev@example.com", "message": "Authenticated"}
        html_en = render_dashboard("127.0.0.1", 24980, auth_status, models_count=10, lang="en")

        # Tabs container and buttons
        self.assertIn('class="provider-tabs"', html_en)
        self.assertIn('data-card="gentle-shell"', html_en)
        self.assertIn('data-provider="agy"', html_en)
        self.assertIn('data-provider="freellmapi"', html_en)
        self.assertIn("AGY (Antigravity)", html_en)
        self.assertIn("FreeLLMAPI", html_en)

        # FreeLLMAPI commands and tooltip
        self.assertIn(
            html.escape('agy-bridge setup-gentle-shell --provider freellmapi --api-key "<YOUR_KEY>"'),
            html_en,
        )
        self.assertIn("Requires FreeLLMAPI gateway running on http://127.0.0.1:31415", html_en)
        self.assertIn("switchProvider", html_en)

        # Spanish localization
        html_es = render_dashboard("127.0.0.1", 24980, auth_status, models_count=10, lang="es")
        self.assertIn("Requiere el gateway de FreeLLMAPI corriendo en http://127.0.0.1:31415", html_es)


if __name__ == "__main__":
    unittest.main()
