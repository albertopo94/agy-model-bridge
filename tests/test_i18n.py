"""Unit tests for internationalization (i18n) module."""

import os
import unittest
from unittest import mock

# Notice: we will import from bridge.i18n
from bridge.i18n import (
    TRANSLATIONS,
    detect_locale,
    get_locale,
    is_yes,
    parse_accept_language,
    set_locale,
    t,
)


class TestDetectLocale(unittest.TestCase):
    def setUp(self):
        set_locale(None)

    def tearDown(self):
        set_locale(None)

    def test_detect_locale_defaults_to_en(self):
        env = {"LC_ALL": "", "LC_MESSAGES": "", "LANG": "", "AGY_LANG": ""}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(detect_locale(), "en")

    def test_detect_locale_with_lang_es(self):
        env = {"LANG": "es_ES.UTF-8"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(detect_locale(), "es")

    def test_detect_locale_with_lc_all_es(self):
        env = {"LC_ALL": "es_AR.UTF-8", "LANG": "en_US.UTF-8"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(detect_locale(), "es")

    def test_detect_locale_with_lc_messages_es(self):
        env = {"LC_MESSAGES": "es_CL.UTF-8", "LANG": "en_US.UTF-8"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(detect_locale(), "es")

    def test_detect_locale_agy_lang_override(self):
        env = {
            "AGY_LANG": "es",
            "LC_ALL": "en_US.UTF-8",
            "LANG": "en_US.UTF-8",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(detect_locale(), "es")

        env_en = {
            "AGY_LANG": "en",
            "LC_ALL": "es_ES.UTF-8",
            "LANG": "es_ES.UTF-8",
        }
        with mock.patch.dict(os.environ, env_en, clear=True):
            self.assertEqual(detect_locale(), "en")

    def test_detect_locale_precedence(self):
        # LC_ALL > LC_MESSAGES > LANG
        env1 = {"LC_ALL": "es_ES.UTF-8", "LC_MESSAGES": "en_US.UTF-8", "LANG": "en_US.UTF-8"}
        with mock.patch.dict(os.environ, env1, clear=True):
            self.assertEqual(detect_locale(), "es")

        env2 = {"LC_ALL": "", "LC_MESSAGES": "es_MX.UTF-8", "LANG": "en_US.UTF-8"}
        with mock.patch.dict(os.environ, env2, clear=True):
            self.assertEqual(detect_locale(), "es")

        env3 = {"LC_ALL": "", "LC_MESSAGES": "", "LANG": "es_UY.UTF-8"}
        with mock.patch.dict(os.environ, env3, clear=True):
            self.assertEqual(detect_locale(), "es")

    def test_detect_locale_non_es(self):
        for lang in ("en_US.UTF-8", "fr_FR.UTF-8", "de_DE.UTF-8", "it_IT.UTF-8", "C"):
            with mock.patch.dict(os.environ, {"LANG": lang}, clear=True):
                self.assertEqual(detect_locale(), "en")

    def test_detect_locale_case_insensitive(self):
        with mock.patch.dict(os.environ, {"LANG": "ES_ES.UTF-8"}, clear=True):
            self.assertEqual(detect_locale(), "es")


class TestTranslate(unittest.TestCase):
    def setUp(self):
        set_locale(None)

    def tearDown(self):
        set_locale(None)

    def test_t_returns_spanish_when_lang_es(self):
        msg = t("daemon_stopped", lang="es")
        self.assertIn("detenido", msg)

    def test_t_returns_english_when_lang_en(self):
        msg = t("daemon_stopped", lang="en")
        self.assertIn("stopped", msg)

    def test_t_falls_back_to_english_when_key_missing_in_spanish(self):
        with mock.patch.dict(TRANSLATIONS["en"], {"test_fallback_key": "English text"}):
            # Key exists in en but not es
            self.assertEqual(t("test_fallback_key", lang="es"), "English text")

    def test_t_returns_key_when_missing_everywhere(self):
        self.assertEqual(t("totally_missing_key_12345", lang="en"), "totally_missing_key_12345")
        self.assertEqual(t("totally_missing_key_12345", lang="es"), "totally_missing_key_12345")

    def test_t_formatting_kwargs(self):
        with mock.patch.dict(
            TRANSLATIONS["en"],
            {"test_fmt": "Hello {name}, PID is {pid}!"},
        ):
            res = t("test_fmt", lang="en", name="Alice", pid=123)
            self.assertEqual(res, "Hello Alice, PID is 123!")

    def test_t_missing_kwargs_safe(self):
        with mock.patch.dict(
            TRANSLATIONS["en"],
            {"test_safe_fmt": "Hello {name}, port {port}!"},
        ):
            # Missing port shouldn't crash
            res = t("test_safe_fmt", lang="en", name="Alice")
            self.assertIn("Alice", res)

    def test_set_and_get_locale(self):
        set_locale("es")
        self.assertEqual(get_locale(), "es")
        # When lang is None in t(), it should use get_locale()
        self.assertIn("detenido", t("daemon_stopped"))

        set_locale("en")
        self.assertEqual(get_locale(), "en")
        self.assertIn("stopped", t("daemon_stopped"))

        set_locale(None)
        # Resets to detect_locale()

    def test_setup_cursor_translations(self):
        title_en = t("setup_cursor_title", lang="en")
        title_es = t("setup_cursor_title", lang="es")
        self.assertIn("Cursor", title_en)
        self.assertIn("Cursor", title_es)
        self.assertNotEqual(title_en, title_es)

        notice_en = t("setup_cursor_notice", lang="en")
        notice_es = t("setup_cursor_notice", lang="es")
        self.assertIn("cloud", notice_en.lower())
        self.assertIn("nube", notice_es.lower())

        step1_en = t("setup_cursor_step1", lang="en", url="http://127.0.0.1:24980/v1")
        step1_es = t("setup_cursor_step1", lang="es", url="http://127.0.0.1:24980/v1")
        self.assertIn("http://127.0.0.1:24980/v1", step1_en)
        self.assertIn("http://127.0.0.1:24980/v1", step1_es)

        step2_en = t("setup_cursor_step2", lang="en", url="http://127.0.0.1:24980/v1")
        step2_es = t("setup_cursor_step2", lang="es", url="http://127.0.0.1:24980/v1")
        self.assertIn("Override OpenAI Base URL", step2_en)
        self.assertIn("Override OpenAI Base URL", step2_es)

        step3_en = t("setup_cursor_step3", lang="en", api_key="local-bridge")
        step3_es = t("setup_cursor_step3", lang="es", api_key="local-bridge")
        self.assertIn("local-bridge", step3_en)
        self.assertIn("local-bridge", step3_es)

    def test_setup_pi_translations(self):
        success_en = t("setup_pi_success", lang="en", target="/home/user/.pi/agent/models.json")
        success_es = t("setup_pi_success", lang="es", target="/home/user/.pi/agent/models.json")
        self.assertIn("Pi", success_en)
        self.assertIn("Pi", success_es)
        self.assertIn("/home/user/.pi/agent/models.json", success_en)
        self.assertIn("/home/user/.pi/agent/models.json", success_es)
        self.assertIn("successfully", success_en)
        self.assertIn("correctamente", success_es)

        auto_en = t("setup_pi_auto_read", lang="en")
        auto_es = t("setup_pi_auto_read", lang="es")
        self.assertIn("automatically", auto_en)
        self.assertIn("automáticamente", auto_es)

        hint_en = t("setup_pi_run_hint", lang="en")
        hint_es = t("setup_pi_run_hint", lang="es")
        self.assertIn("/model", hint_en)
        self.assertIn("/model", hint_es)
        self.assertIn("pi --model agy/gemini-3.8-flash-high", hint_en)
        self.assertIn("pi --model agy/gemini-3.8-flash-high", hint_es)

        uninst_en = t("uninstall_pi_restored", lang="en")
        uninst_es = t("uninstall_pi_restored", lang="es")
        self.assertIn("Pi", uninst_en)
        self.assertIn("Pi", uninst_es)
        self.assertIn("restored", uninst_en)
        self.assertIn("restaurada", uninst_es)


class TestIsYes(unittest.TestCase):
    def test_is_yes_spanish_affirmative(self):
        for val in ("s", "S", "si", "SI", "Si", "sí", "SÍ", "Sí", "  s  ", "  si  ", "  sí  "):
            self.assertTrue(is_yes(val), f"Expected True for '{val}'")

    def test_is_yes_english_affirmative(self):
        for val in ("y", "Y", "yes", "YES", "Yes", "  y  ", "  yes  "):
            self.assertTrue(is_yes(val), f"Expected True for '{val}'")

    def test_is_yes_negative_and_falsy(self):
        for val in ("n", "N", "no", "NO", "No", "cancel", "q", "", "  ", "maybe", "1", "0", None):
            self.assertFalse(is_yes(val), f"Expected False for '{val}'")  # type: ignore


class TestTranslationsParity(unittest.TestCase):
    def test_translations_dictionary_parity(self):
        en_keys = set(TRANSLATIONS.get("en", {}).keys())
        es_keys = set(TRANSLATIONS.get("es", {}).keys())
        missing_in_es = en_keys - es_keys
        missing_in_en = es_keys - en_keys
        self.assertEqual(
            missing_in_es,
            set(),
            f"Keys in 'en' missing from 'es': {missing_in_es}",
        )
        self.assertEqual(
            missing_in_en,
            set(),
            f"Keys in 'es' missing from 'en': {missing_in_en}",
        )

    def test_required_cli_message_keys_exist(self):
        required_keys = [
            # Lifecycle
            "daemon_running_bg",
            "daemon_dashboard_url",
            "daemon_stop_hint",
            "daemon_already_running",
            "daemon_start_failed",
            "daemon_stopped",
            "daemon_not_running",
            "status_active",
            "status_address",
            "status_models",
            "status_auth",
            "status_stopped",
            "status_start_hint",
            "dashboard_not_active",
            "dashboard_opening",
            # Setup
            "setup_backup_label",
            "setup_claude_success",
            "setup_claude_auto_read",
            "setup_claude_run_hint",
            "setup_codex_success",
            "setup_codex_auto_read",
            "setup_codex_run_hint",
            "setup_hermes_success",
            "setup_hermes_auto_read",
            "setup_hermes_run_hint",
            "setup_opencode_success",
            "setup_opencode_auto_read",
            "setup_opencode_run_hint",
            "setup_openclaw_success",
            "setup_openclaw_auto_read",
            "setup_openclaw_run_hint",
            # Pi
            "setup_pi_success",
            "setup_pi_auto_read",
            "setup_pi_run_hint",
            # Cursor
            "setup_cursor_title",
            "setup_cursor_notice",
            "setup_cursor_step1",
            "setup_cursor_step2",
            "setup_cursor_step3",
            "setup_cursor_step4",
            # Restore
            "restore_restored_from",
            "restore_client_ready",
            "restore_no_backups",
            "restore_available_title",
            "restore_immediate_prev",
            "restore_prompt",
            "restore_cancelled",
            "restore_invalid_choice",
            # Uninstall
            "uninstall_confirm_prompt",
            "uninstall_cancelled",
            "uninstall_success",
            "uninstall_daemon_stopped",
            "uninstall_binaries_removed",
            "uninstall_daemon_dir_removed",
            "uninstall_claude_restored",
            "uninstall_codex_restored",
            "uninstall_hermes_restored",
            "uninstall_opencode_restored",
            "uninstall_openclaw_restored",
            "uninstall_pi_restored",
            "uninstall_backups_purged",
            # Update
            "update_success",
            "update_daemon_restarted",
            "update_already_latest",
            "update_failed",
            "update_not_git_repo",
            "update_git_not_found",
            "update_git_error",
        ]
        for key in required_keys:
            self.assertIn(key, TRANSLATIONS["en"], f"Missing required key in 'en': {key}")
            self.assertIn(key, TRANSLATIONS["es"], f"Missing required key in 'es': {key}")


class TestParseAcceptLanguage(unittest.TestCase):
    def test_parse_accept_language_spanish_priority(self):
        self.assertEqual(parse_accept_language("es-ES,es;q=0.9,en;q=0.8"), "es")
        self.assertEqual(parse_accept_language("es"), "es")
        self.assertEqual(parse_accept_language("es-419,es;q=0.9"), "es")

    def test_parse_accept_language_english_priority(self):
        self.assertEqual(parse_accept_language("en-US,en;q=0.9"), "en")
        self.assertEqual(parse_accept_language("en"), "en")
        self.assertEqual(parse_accept_language("en-GB,en;q=0.8,es;q=0.5"), "en")
        self.assertEqual(parse_accept_language("es;q=0.5,en-US;q=0.9"), "en")

    def test_parse_accept_language_fallback(self):
        self.assertEqual(parse_accept_language(""), "en")
        self.assertEqual(parse_accept_language("fr-FR,fr;q=0.9,de;q=0.8"), "en")
        self.assertEqual(parse_accept_language(None), "en")  # type: ignore


class TestCLIInternationalization(unittest.TestCase):
    def setUp(self):
        set_locale(None)

    def tearDown(self):
        set_locale(None)

    @mock.patch("bridge.__main__.get_daemon_status")
    def test_cli_status_respects_lang_flag(self, mock_status):
        import io
        from bridge.__main__ import main

        mock_status.return_value = {
            "running": True,
            "pid": 5555,
            "port": 24980,
            "host": "127.0.0.1",
            "url": "http://127.0.0.1:24980/",
            "models_count": 10,
            "auth": {"status": "Valid"},
        }

        # Explicit --lang es
        out_es = io.StringIO()
        with mock.patch("sys.stdout", out_es):
            code = main(["status", "--lang", "es"])
        self.assertEqual(code, 0)
        self.assertIn("Activo", out_es.getvalue())
        self.assertIn("Dirección", out_es.getvalue())

        # Explicit --lang=es
        out_es_eq = io.StringIO()
        with mock.patch("sys.stdout", out_es_eq):
            code = main(["status", "--lang=es"])
        self.assertEqual(code, 0)
        self.assertIn("Activo", out_es_eq.getvalue())

        # Explicit --lang en
        out_en = io.StringIO()
        with mock.patch("sys.stdout", out_en):
            code = main(["status", "--lang", "en"])
        self.assertEqual(code, 0)
        self.assertIn("Active", out_en.getvalue())
        self.assertIn("Address", out_en.getvalue())

    @mock.patch("bridge.__main__.get_daemon_status")
    def test_cli_status_respects_agy_lang_env(self, mock_status):
        import io
        from bridge.__main__ import main

        mock_status.return_value = {
            "running": True,
            "pid": 5555,
            "port": 24980,
            "host": "127.0.0.1",
            "url": "http://127.0.0.1:24980/",
            "models_count": 10,
            "auth": {"status": "Valid"},
        }

        # AGY_LANG=es
        with mock.patch.dict(os.environ, {"AGY_LANG": "es"}, clear=False):
            out_es = io.StringIO()
            with mock.patch("sys.stdout", out_es):
                code = main(["status"])
            self.assertEqual(code, 0)
            self.assertIn("Activo", out_es.getvalue())

        # AGY_LANG=en
        with mock.patch.dict(os.environ, {"AGY_LANG": "en"}, clear=False):
            out_en = io.StringIO()
            with mock.patch("sys.stdout", out_en):
                code = main(["status"])
            self.assertEqual(code, 0)
            self.assertIn("Active", out_en.getvalue())


class TestPiTranslations(unittest.TestCase):
    def test_pi_set_default_keys_present_in_both_locales(self):
        for lang in ("en", "es"):
            tip = t("setup_pi_set_default_tip", lang=lang)
            done = t("setup_pi_set_default_done", lang=lang)
            self.assertIn("--set-default", tip)
            self.assertIn("settings.json", done)


if __name__ == "__main__":
    unittest.main()

