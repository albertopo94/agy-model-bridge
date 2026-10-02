import json
import os
import re
import stat
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from bridge.setup import (
    CLIENT_CONFIGURATORS,
    ClaudeConfigurator,
    ClientConfigurator,
    CodexConfigurator,
    HermesConfigurator,
    OpenClawConfigurator,
    OpenCodeConfigurator,
    atomic_write_file,
    build_hermes_block,
    create_backup,
    describe_backup,
    get_configurator,
    list_backups,
    list_configurators,
    register_configurator,
    restore_backup,
    restore_claude,
    restore_codex,
    restore_hermes,
    restore_openclaw,
    restore_opencode,
    setup_claude,
    setup_codex,
    setup_hermes,
    setup_openclaw,
    setup_opencode,
    uninstall,
    update_installation,
)


class TestAtomicWriteFile(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_atomic_write_creates_file_with_mode_0o600(self):
        target = self.dir_path / "test.txt"
        content = "hello world\nsecret content"
        atomic_write_file(target, content)

        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), content)
        file_stat = target.stat()
        file_mode = stat.S_IMODE(file_stat.st_mode)
        self.assertEqual(file_mode, 0o600)

    def test_atomic_write_creates_parent_directories_with_mode_0o700(self):
        nested_dir = self.dir_path / "sub" / "deep"
        target = nested_dir / "config.json"
        content = '{"key": "value"}'
        atomic_write_file(target, content)

        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), content)
        parent_stat = nested_dir.stat()
        parent_mode = stat.S_IMODE(parent_stat.st_mode)
        self.assertEqual(parent_mode, 0o700)

    def test_atomic_write_overwrites_existing_file(self):
        target = self.dir_path / "settings.json"
        target.write_text("initial", encoding="utf-8")
        atomic_write_file(target, "updated content")

        self.assertEqual(target.read_text(encoding="utf-8"), "updated content")
        file_mode = stat.S_IMODE(target.stat().st_mode)
        self.assertEqual(file_mode, 0o600)

    def test_atomic_write_custom_mode(self):
        target = self.dir_path / "custom.txt"
        atomic_write_file(target, "custom mode", mode=0o644)
        file_mode = stat.S_IMODE(target.stat().st_mode)
        self.assertEqual(file_mode, 0o644)

    def test_atomic_write_failure_cleans_up_temp(self):
        target = self.dir_path / "fail.txt"
        with self.assertRaises(TypeError):
            atomic_write_file(target, 12345)  # type: ignore

        temp_files = list(self.dir_path.glob("fail.txt.tmp.*"))
        self.assertEqual(len(temp_files), 0)


class TestCreateBackup(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_backup_non_existent_returns_none(self):
        missing = self.dir_path / "does_not_exist.toml"
        backup_path = create_backup(missing)
        self.assertIsNone(backup_path)

    def test_create_backup_directory_target_returns_none(self):
        sub_dir = self.dir_path / "adir"
        sub_dir.mkdir()
        backup_path = create_backup(sub_dir)
        self.assertIsNone(backup_path)

    def test_create_backup_creates_timestamped_copy(self):
        target = self.dir_path / "config.toml"
        target.write_text('model = "gemini"\n', encoding="utf-8")

        backup_path = create_backup(target)
        self.assertIsNotNone(backup_path)
        self.assertTrue(backup_path.exists())
        self.assertNotEqual(target, backup_path)
        self.assertEqual(backup_path.read_text(encoding="utf-8"), 'model = "gemini"\n')

        # Check timestamp pattern: *.backup-YYYY-MM-DDTHH-MM-SS
        iso_pattern = re.compile(r"^config\.toml\.backup-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}$")
        self.assertTrue(
            bool(iso_pattern.match(backup_path.name)),
            f"Backup name '{backup_path.name}' does not match expected ISO pattern",
        )


class TestListBackups(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_list_backups_empty_when_dir_missing(self):
        missing_target = self.dir_path / "nonexistent" / "settings.json"
        self.assertEqual(list_backups(missing_target), [])

    def test_list_backups_empty_when_no_backups(self):
        target = self.dir_path / "settings.json"
        target.write_text("{}", encoding="utf-8")
        self.assertEqual(list_backups(target), [])

    def test_list_backups_sorts_by_mtime_descending(self):
        import time
        target = self.dir_path / "settings.json"
        target.write_text("{}", encoding="utf-8")

        b1 = self.dir_path / "settings.json.backup-2026-09-20T10-00-00"
        b1.write_text('{"v": 1}', encoding="utf-8")
        os.utime(b1, (1000.0, 1000.0))

        b2 = self.dir_path / "settings.json.backup-2026-09-30T08-57-26-113Z"
        b2.write_text('{"v": 2}', encoding="utf-8")
        os.utime(b2, (2000.0, 2000.0))

        b3 = self.dir_path / "settings.json.backup-2026-09-30T12-15-44"
        b3.write_text('{"v": 3}', encoding="utf-8")
        os.utime(b3, (3000.0, 3000.0))

        # Irrelevant file that should not be included
        other = self.dir_path / "other.json.backup-2026-09-30T12-00-00"
        other.write_text("{}", encoding="utf-8")

        results = list_backups(target)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0], b3)  # Most recent
        self.assertEqual(results[1], b2)  # Intermediate (e.g. freellmapi format)
        self.assertEqual(results[2], b1)  # Oldest


class TestDescribeBackup(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_describe_claude_freellmapi_backup(self):
        b = self.dir_path / "settings.json.backup-2026-09-30T13-30-12"
        b.write_text(json.dumps({
            "env": {
                "ANTHROPIC_BASE_URL": "http://127.0.0.1:31415",
                "ANTHROPIC_AUTH_TOKEN": "freellmapi-fa8cac1b8",
            }
        }), encoding="utf-8")
        self.assertEqual(describe_backup(b), "FreeLLMAPI")

    def test_describe_claude_agy_bridge_backup(self):
        b = self.dir_path / "settings.json.backup-2026-09-30T14-04-58"
        b.write_text(json.dumps({
            "env": {
                "ANTHROPIC_BASE_URL": "http://127.0.0.1:24980",
                "ANTHROPIC_AUTH_TOKEN": "antigravity",
            }
        }), encoding="utf-8")
        self.assertEqual(describe_backup(b), "AGY Bridge")

    def test_describe_claude_anthropic_original_backup(self):
        b = self.dir_path / "settings.json.backup-2026-09-22T17-00-18-257Z"
        b.write_text(json.dumps({
            "env": {}
        }), encoding="utf-8")
        self.assertEqual(describe_backup(b), "Anthropic Original")

    def test_describe_codex_agy_bridge_backup(self):
        b = self.dir_path / "config.toml.backup-2026-09-30T12-15-55"
        b.write_text('# agy:start\nmodel = "gemini"\n# agy:end', encoding="utf-8")
        self.assertEqual(describe_backup(b), "AGY Bridge")

    def test_describe_codex_freellmapi_backup(self):
        b = self.dir_path / "config.toml.backup-2026-09-26T21-34-23"
        b.write_text('base_url = "http://127.0.0.1:31415/v1"', encoding="utf-8")
        self.assertEqual(describe_backup(b), "FreeLLMAPI")

    def test_describe_codex_original_backup(self):
        b = self.dir_path / "config.toml.backup-2026-09-26T21-34-23-420Z"
        b.write_text('[projects]\nactive = "main"', encoding="utf-8")
        self.assertEqual(describe_backup(b), "Codex Original")

    def test_describe_opencode_agy_bridge_backup(self):
        b = self.dir_path / "opencode.json.backup-2026-10-02T10-00-00"
        b.write_text(json.dumps({
            "model": "agy/gemini-3.8-flash-high",
            "provider": {"agy": {"options": {"baseURL": "http://127.0.0.1:24980/v1"}}},
        }), encoding="utf-8")
        self.assertEqual(describe_backup(b), "AGY Bridge")

    def test_describe_opencode_original_backup(self):
        b = self.dir_path / "opencode.json.backup-2026-10-02T09-00-00"
        b.write_text(json.dumps({
            "model": "anthropic/claude-3-5-sonnet",
        }), encoding="utf-8")
        self.assertEqual(describe_backup(b), "OpenCode Original")

    def test_describe_openclaw_agy_bridge_backup(self):
        b = self.dir_path / "openclaw.json.backup-2026-10-02T10-00-00"
        b.write_text(json.dumps({
            "models": {"providers": {"agy": {"baseUrl": "http://127.0.0.1:24980/v1"}}},
        }), encoding="utf-8")
        self.assertEqual(describe_backup(b), "AGY Bridge")

    def test_describe_openclaw_original_backup(self):
        b = self.dir_path / "openclaw.json.backup-2026-10-02T09-00-00"
        b.write_text(json.dumps({
            "agents": {"defaults": {"model": {"primary": "openai/gpt-4o"}}},
        }), encoding="utf-8")
        self.assertEqual(describe_backup(b), "OpenClaw Original")

    def test_describe_missing_or_invalid_file(self):
        missing = self.dir_path / "does_not_exist"
        self.assertEqual(describe_backup(missing), "Desconocido")


class TestRestoreBackup(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_restore_backup_raises_if_no_backups(self):
        target = self.dir_path / "settings.json"
        with self.assertRaises(FileNotFoundError):
            restore_backup(target)

    def test_restore_backup_raises_if_specified_backup_missing(self):
        target = self.dir_path / "settings.json"
        missing_b = self.dir_path / "settings.json.backup-none"
        with self.assertRaises(FileNotFoundError):
            restore_backup(target, backup_path=missing_b)

    def test_restore_latest_backup_when_no_backup_specified(self):
        target = self.dir_path / "settings.json"
        target.write_text('{"active": "bridge"}', encoding="utf-8")

        b_old = self.dir_path / "settings.json.backup-2026-09-29T10-00-00"
        b_old.write_text('{"config": "old"}', encoding="utf-8")
        os.utime(b_old, (1000.0, 1000.0))

        b_latest = self.dir_path / "settings.json.backup-2026-09-30T11-00-00"
        b_latest.write_text('{"config": "previous_native"}', encoding="utf-8")
        os.utime(b_latest, (2000.0, 2000.0))

        restored = restore_backup(target)

        self.assertEqual(restored, b_latest)
        self.assertEqual(target.read_text(encoding="utf-8"), '{"config": "previous_native"}')
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        # Ensure backup file is NOT deleted
        self.assertTrue(b_latest.exists())
        self.assertTrue(b_old.exists())
        # Ensure NO new backup was created upon restore
        backups = list_backups(target)
        self.assertEqual(len(backups), 2)

    def test_restore_specific_historical_backup(self):
        target = self.dir_path / "config.toml"
        target.write_text('active = "bridge"\n', encoding="utf-8")

        b1 = self.dir_path / "config.toml.backup-1"
        b1.write_text('setting = "choice1"\n', encoding="utf-8")

        b2 = self.dir_path / "config.toml.backup-2"
        b2.write_text('setting = "choice2"\n', encoding="utf-8")

        restored = restore_backup(target, backup_path=b1)
        self.assertEqual(restored, b1)
        self.assertEqual(target.read_text(encoding="utf-8"), 'setting = "choice1"\n')
        self.assertTrue(b1.exists())


class TestSetupClaude(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_fresh_settings_creation(self):
        target = self.dir_path / "settings.json"
        res_path = setup_claude(settings_path=target)

        self.assertEqual(res_path, target)
        self.assertIsNone(getattr(res_path, "backup_path", None))
        self.assertTrue(target.exists())
        file_mode = stat.S_IMODE(target.stat().st_mode)
        self.assertEqual(file_mode, 0o600)

        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertIn("env", data)
        env = data["env"]
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://127.0.0.1:24980")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "antigravity")
        self.assertEqual(env["ANTHROPIC_MODEL"], "gemini-3.8-flash-high")
        self.assertEqual(env["ANTHROPIC_DEFAULT_SONNET_MODEL"], "gemini-3.8-flash-high")
        self.assertEqual(env["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "gemini-3.8-flash-high")
        self.assertEqual(env["ANTHROPIC_DEFAULT_OPUS_MODEL"], "gemini-3.8-flash-high")
        self.assertEqual(env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "1048576")
        self.assertEqual(env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"], "1")

        # modelPicker options for Claude Code /model menu
        self.assertIn("modelPicker", data)
        model_options = data["modelPicker"].get("options", [])
        option_models = [opt["model"] for opt in model_options]
        self.assertEqual(
            option_models,
            [
                "gemini-3.8-flash-high",
                "gemini-3.7-flash-tiered",
                "gemini-3.6-flash-tiered",
                "claude-sonnet-4-6",
                "claude-opus-4-6-thinking",
            ],
        )
        self.assertFalse(data["modelPicker"].get("replaceBuiltInOptions", True))

        # Indentation should be 2 spaces
        raw_text = target.read_text(encoding="utf-8")
        self.assertIn('  "env": {', raw_text)
        self.assertIn('    "ANTHROPIC_BASE_URL": "http://127.0.0.1:24980"', raw_text)

        # No backup should have been created for a fresh file
        backups = list(self.dir_path.glob("settings.json.backup-*"))
        self.assertEqual(len(backups), 0)

    def test_model_picker_with_custom_model_prepends_option(self):
        target = self.dir_path / "settings.json"
        setup_claude(settings_path=target, model="my-special-model")

        data = json.loads(target.read_text(encoding="utf-8"))
        options = data.get("modelPicker", {}).get("options", [])
        self.assertEqual(options[0]["model"], "my-special-model")
        self.assertIn("my-special-model", options[0]["label"])
        self.assertEqual(options[1]["model"], "gemini-3.8-flash-high")

    def test_surgical_merge_preserves_existing_keys_and_creates_backup(self):
        target = self.dir_path / "settings.json"
        initial_data = {
            "outputStyle": "verbose",
            "permissions": {"allowAll": False},
            "env": {
                "CUSTOM_EXISTING_KEY": "custom_val",
                "ANTHROPIC_BASE_URL": "http://old-url.local",
            },
        }
        target.write_text(json.dumps(initial_data, indent=2), encoding="utf-8")

        res_path = setup_claude(settings_path=target)

        # Backup was created with initial contents
        backups = list(self.dir_path.glob("settings.json.backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(res_path.backup_path, backups[0])
        backup_data = json.loads(backups[0].read_text(encoding="utf-8"))
        self.assertEqual(backup_data["env"]["ANTHROPIC_BASE_URL"], "http://old-url.local")

        # Target file has merged keys
        updated_data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(updated_data["outputStyle"], "verbose")
        self.assertEqual(updated_data["permissions"], {"allowAll": False})
        self.assertEqual(updated_data["env"]["CUSTOM_EXISTING_KEY"], "custom_val")
        self.assertEqual(updated_data["env"]["ANTHROPIC_BASE_URL"], "http://127.0.0.1:24980")
        self.assertEqual(updated_data["env"]["ANTHROPIC_MODEL"], "gemini-3.8-flash-high")

    def test_custom_flags_port_model_url(self):
        target = self.dir_path / "settings.json"
        setup_claude(
            settings_path=target,
            port=9090,
            model="gemini-2.5-pro",
        )
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["env"]["ANTHROPIC_BASE_URL"], "http://127.0.0.1:9090")
        self.assertEqual(data["env"]["ANTHROPIC_MODEL"], "gemini-2.5-pro")

        # Explicit URL with trailing slash stripped
        target2 = self.dir_path / "settings2.json"
        setup_claude(
            settings_path=target2,
            base_url="https://gateway.example.com/agy///",
            auth_token="custom-token",
        )
        data2 = json.loads(target2.read_text(encoding="utf-8"))
        self.assertEqual(data2["env"]["ANTHROPIC_BASE_URL"], "https://gateway.example.com/agy")
        self.assertEqual(data2["env"]["ANTHROPIC_AUTH_TOKEN"], "custom-token")

    def test_idempotency_repeated_runs(self):
        target = self.dir_path / "settings.json"
        setup_claude(settings_path=target)
        first_content = target.read_text(encoding="utf-8")

        setup_claude(settings_path=target)
        second_content = target.read_text(encoding="utf-8")
        self.assertEqual(first_content, second_content)

    def test_default_path_used_when_none(self):
        with unittest.mock.patch("pathlib.Path.home", return_value=self.dir_path):
            res = setup_claude()
            expected = self.dir_path / ".claude" / "settings.json"
            self.assertEqual(res, expected)
            self.assertTrue(expected.exists())


class TestSetupCodex(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_fresh_codex_config_creation(self):
        target = self.dir_path / "config.toml"
        res_path = setup_codex(config_path=target)

        self.assertEqual(res_path, target)
        self.assertIsNone(getattr(res_path, "backup_path", None))
        self.assertTrue(target.exists())
        file_mode = stat.S_IMODE(target.stat().st_mode)
        self.assertEqual(file_mode, 0o600)

        content = target.read_text(encoding="utf-8")
        self.assertEqual(content.count("# agy:start"), 1)
        self.assertEqual(content.count("# agy:end"), 1)

        self.assertIn('model = "gemini-3.8-flash-high"', content)
        self.assertIn('model_provider = "agy"', content)
        self.assertIn("model_context_window = 1048576", content)
        self.assertIn("model_auto_compact_token_limit = 943718", content)
        self.assertIn("[model_providers.agy]", content)
        self.assertIn('name = "agy"', content)
        self.assertIn('base_url = "http://127.0.0.1:24980/v1"', content)
        self.assertIn('wire_api = "responses"', content)
        self.assertIn("requires_openai_auth = false", content)

        # No backup should have been created for a fresh file
        backups = list(self.dir_path.glob("config.toml.backup-*"))
        self.assertEqual(len(backups), 0)

    def test_replace_existing_delimited_block_in_place_and_creates_backup(self):
        target = self.dir_path / "config.toml"
        initial_content = (
            "[projects]\n"
            'active = "my-project"\n\n'
            "# agy:start\n"
            'model = "old-model"\n'
            'model_provider = "agy"\n'
            "model_context_window = 1048576\n"
            "model_auto_compact_token_limit = 943718\n\n"
            "[model_providers.agy]\n"
            'name = "agy"\n'
            'base_url = "http://127.0.0.1:7070/v1"\n'
            'wire_api = "responses"\n'
            "requires_openai_auth = false\n"
            "# agy:end\n\n"
            "[mcp_servers]\n"
            'server1 = "http://localhost:3000"\n'
        )
        target.write_text(initial_content, encoding="utf-8")

        res_path = setup_codex(config_path=target)

        # Backup created
        backups = list(self.dir_path.glob("config.toml.backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(res_path.backup_path, backups[0])
        self.assertEqual(backups[0].read_text(encoding="utf-8"), initial_content)

        # Target updated in-place
        updated = target.read_text(encoding="utf-8")
        self.assertEqual(updated.count("# agy:start"), 1)
        self.assertEqual(updated.count("# agy:end"), 1)
        self.assertIn("[projects]\nactive = \"my-project\"", updated)
        self.assertIn("[mcp_servers]\nserver1 = \"http://localhost:3000\"", updated)
        self.assertIn('model = "gemini-3.8-flash-high"', updated)
        self.assertIn('base_url = "http://127.0.0.1:24980/v1"', updated)

    def test_insertion_with_existing_tables_without_agy_block(self):
        target = self.dir_path / "config.toml"
        initial_content = (
            "[projects]\n"
            'active = "my-project"\n'
        )
        target.write_text(initial_content, encoding="utf-8")

        setup_codex(config_path=target)

        # Backup created
        backups = list(self.dir_path.glob("config.toml.backup-*"))
        self.assertEqual(len(backups), 1)

        updated = target.read_text(encoding="utf-8")
        self.assertEqual(updated.count("# agy:start"), 1)
        self.assertIn("[projects]\nactive = \"my-project\"", updated)
        self.assertIn('model = "gemini-3.8-flash-high"', updated)

    def test_codex_setup_avoids_duplicate_root_keys(self):
        target = self.dir_path / "config.toml"
        initial_content = (
            'personality = "pragmatic"\n'
            'model = "gpt-6-sol"\n'
            'model_reasoning_effort = "medium"\n\n'
            "[projects]\n"
            'active = "test"\n'
        )
        target.write_text(initial_content, encoding="utf-8")

        setup_codex(config_path=target)

        updated = target.read_text(encoding="utf-8")
        try:
            import tomllib
            parsed = tomllib.loads(updated)
            self.assertEqual(parsed.get("model"), "gemini-3.8-flash-high")
            self.assertEqual(parsed.get("model_provider"), "agy")
            self.assertEqual(parsed.get("personality"), "pragmatic")
        except ImportError:
            # Python 3.10 standard library compatibility (tomllib was added in Python 3.11)
            self.assertIn('model = "gemini-3.8-flash-high"', updated)
            self.assertIn('model_provider = "agy"', updated)
            self.assertIn('personality = "pragmatic"', updated)
        self.assertIn('# model = "gpt-6-sol"  # agy-override', updated)

    def test_codex_cli_flags_port_and_model(self):
        target = self.dir_path / "config.toml"
        setup_codex(
            config_path=target,
            port=9090,
            model="gemini-2.5-pro",
        )
        content = target.read_text(encoding="utf-8")
        self.assertIn('model = "gemini-2.5-pro"', content)
        self.assertIn('base_url = "http://127.0.0.1:9090/v1"', content)

        # Explicit URL flag
        target2 = self.dir_path / "config2.toml"
        setup_codex(
            config_path=target2,
            base_url="https://remote.example.com/v1///",
        )
        content2 = target2.read_text(encoding="utf-8")
        self.assertIn('base_url = "https://remote.example.com/v1"', content2)

    def test_codex_idempotency_repeated_runs(self):
        target = self.dir_path / "config.toml"
        setup_codex(config_path=target)
        first_content = target.read_text(encoding="utf-8")

        setup_codex(config_path=target)
        second_content = target.read_text(encoding="utf-8")
        self.assertEqual(first_content, second_content)

    def test_codex_default_path_used_when_none(self):
        with unittest.mock.patch("pathlib.Path.home", return_value=self.dir_path):
            res = setup_codex()
            expected = self.dir_path / ".codex" / "config.toml"
            self.assertEqual(res, expected)
            self.assertTrue(expected.exists())


class TestCLIParsing(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_setup_claude_dispatches_with_flags(self):
        from bridge.__main__ import main
        target = self.dir_path / "claude_settings.json"
        exit_code = main(["setup-claude", "--port", "9090", "--model", "gemini-3.8-flash", "--path", str(target)])
        self.assertEqual(exit_code, 0)
        self.assertTrue(target.exists())
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["env"]["ANTHROPIC_BASE_URL"], "http://127.0.0.1:9090")
        self.assertEqual(data["env"]["ANTHROPIC_MODEL"], "gemini-3.8-flash")

    def test_cli_setup_claude_outputs_backup_and_guidance(self):
        import io
        from bridge.__main__ import main
        target = self.dir_path / "claude_settings.json"
        target.write_text('{"env": {}}', encoding="utf-8")
        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            exit_code = main(["setup-claude", "--path", str(target)])
        self.assertEqual(exit_code, 0)
        output = out.getvalue()
        self.assertIn("Backup: ", output)
        self.assertIn(f"Claude Code configured successfully at {target}", output)
        self.assertIn("Claude Code will read this configuration automatically.", output)
        self.assertIn("Run 'claude' to start coding with Gemini 3.8 Flash · high (1M context).", output)

    def test_cli_setup_codex_dispatches_with_flags(self):
        from bridge.__main__ import main
        target = self.dir_path / "codex_config.toml"
        exit_code = main(["setup-codex", "--port", "7070", "--model", "gemini-3.8-flash-low", "--path", str(target)])
        self.assertEqual(exit_code, 0)
        self.assertTrue(target.exists())
        content = target.read_text(encoding="utf-8")
        self.assertIn('model = "gemini-3.8-flash-low"', content)
        self.assertIn('base_url = "http://127.0.0.1:7070/v1"', content)

    def test_cli_setup_codex_outputs_backup_and_guidance(self):
        import io
        from bridge.__main__ import main
        target = self.dir_path / "codex_config.toml"
        target.write_text('model = "old"', encoding="utf-8")
        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            exit_code = main(["setup-codex", "--path", str(target)])
        self.assertEqual(exit_code, 0)
        output = out.getvalue()
        self.assertIn("Backup: ", output)
        self.assertIn(f"Codex CLI configured successfully at {target}", output)
        self.assertIn("Codex CLI will read this configuration automatically.", output)
        self.assertIn("Run 'codex' to start coding with Gemini 3.8 Flash · high (1M context).", output)

    @unittest.mock.patch("bridge.__main__.run_server")
    def test_cli_daemon_mode_invokes_run_server(self, mock_run_server):
        from bridge.__main__ import main
        exit_code = main(["--port", "9999", "--host", "0.0.0.0", "--project", "my-prj"])
        self.assertEqual(exit_code, 0)
        mock_run_server.assert_called_once_with(
            host="0.0.0.0",
            port=9999,
            project="my-prj",
            base_url=None,
        )

    def test_cli_help_flags(self):
        from bridge.__main__ import main
        for subcmd in (
            ["setup-claude", "--help"],
            ["setup-codex", "--help"],
            ["setup-hermes", "--help"],
            ["restore-claude", "--help"],
            ["restore-codex", "--help"],
            ["restore-hermes", "--help"],
            ["uninstall", "--help"],
            ["--help"],
        ):
            with self.subTest(subcmd=subcmd):
                with self.assertRaises(SystemExit) as cm:
                    with unittest.mock.patch("sys.stdout"):
                        main(subcmd)
                self.assertEqual(cm.exception.code, 0)


class TestCLIRestore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_restore_claude_no_backups_returns_1(self):
        import io
        from bridge.__main__ import main
        target = self.dir_path / "settings.json"
        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            exit_code = main(["restore-claude", "--path", str(target)])
        self.assertEqual(exit_code, 1)
        self.assertTrue(
            "No se encontraron backups" in out.getvalue()
            or "No backups found" in out.getvalue()
        )

    def test_cli_restore_claude_with_latest_flag(self):
        import io
        from bridge.__main__ import main
        target = self.dir_path / "settings.json"
        target.write_text('{"env": "bridge"}', encoding="utf-8")

        b1 = self.dir_path / "settings.json.backup-1"
        b1.write_text('{"env": "older"}', encoding="utf-8")
        os.utime(b1, (1000.0, 1000.0))

        b2 = self.dir_path / "settings.json.backup-2"
        b2.write_text('{"env": "immediate_previous"}', encoding="utf-8")
        os.utime(b2, (2000.0, 2000.0))

        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            exit_code = main(["restore-claude", "--path", str(target), "--latest"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(target.read_text(encoding="utf-8"), '{"env": "immediate_previous"}')
        self.assertTrue(
            "Restaurada configuración desde:" in out.getvalue()
            or "Restored configuration from:" in out.getvalue()
        )
        self.assertIn("Claude Code", out.getvalue())

    def test_cli_restore_claude_with_backup_flag(self):
        from bridge.__main__ import main
        target = self.dir_path / "settings.json"
        target.write_text('{"env": "bridge"}', encoding="utf-8")

        b1 = self.dir_path / "settings.json.backup-1"
        b1.write_text('{"env": "specific"}', encoding="utf-8")

        exit_code = main(["restore-claude", "--path", str(target), "--backup", str(b1)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(target.read_text(encoding="utf-8"), '{"env": "specific"}')

    def test_cli_restore_claude_interactive_enter_picks_option_1(self):
        import io
        from bridge.__main__ import main
        target = self.dir_path / "settings.json"
        target.write_text('{"env": "bridge"}', encoding="utf-8")

        b1 = self.dir_path / "settings.json.backup-2026-09-20T10-00-00"
        b1.write_text('{"env": "old"}', encoding="utf-8")
        os.utime(b1, (1000.0, 1000.0))

        b2 = self.dir_path / "settings.json.backup-2026-09-30T12-00-00"
        b2.write_text('{"env": "immediate_previous"}', encoding="utf-8")
        os.utime(b2, (2000.0, 2000.0))

        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            with unittest.mock.patch("builtins.input", return_value="") as mock_input:
                exit_code = main(["restore-claude", "--path", str(target)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(target.read_text(encoding="utf-8"), '{"env": "immediate_previous"}')
        output = out.getvalue()
        self.assertTrue(
            "[1] settings.json.backup-2026-09-30T12-00-00  [Anthropic Original]  <-- Anterior inmediata" in output
            or "[1] settings.json.backup-2026-09-30T12-00-00  [Anthropic Original]  <-- Immediate previous" in output
        )
        self.assertIn("[2] settings.json.backup-2026-09-20T10-00-00  [Anthropic Original]", output)
        prompt_arg = mock_input.call_args[0][0]
        self.assertTrue("1-2" in prompt_arg)
        self.assertTrue("Enter" in prompt_arg)
        self.assertTrue("'q'" in prompt_arg)

    def test_cli_restore_claude_interactive_displays_distinct_provenance_tags(self):
        import io
        from bridge.__main__ import main
        target = self.dir_path / "settings.json"
        target.write_text('{"env": {}}', encoding="utf-8")

        b1 = self.dir_path / "settings.json.backup-2026-09-20T10-00-00"
        b1.write_text('{"env": {}}', encoding="utf-8")
        os.utime(b1, (1000.0, 1000.0))

        b2 = self.dir_path / "settings.json.backup-2026-09-25T10-00-00"
        b2.write_text(json.dumps({
            "env": {
                "ANTHROPIC_BASE_URL": "http://127.0.0.1:31415",
                "ANTHROPIC_AUTH_TOKEN": "freellmapi-xyz",
            }
        }), encoding="utf-8")
        os.utime(b2, (2000.0, 2000.0))

        b3 = self.dir_path / "settings.json.backup-2026-09-30T12-00-00"
        b3.write_text(json.dumps({
            "env": {
                "ANTHROPIC_BASE_URL": "http://127.0.0.1:24980",
                "ANTHROPIC_AUTH_TOKEN": "antigravity",
            }
        }), encoding="utf-8")
        os.utime(b3, (3000.0, 3000.0))

        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            with unittest.mock.patch("builtins.input", return_value="q"):
                main(["restore-claude", "--path", str(target)])

        output = out.getvalue()
        self.assertTrue(
            "[1] settings.json.backup-2026-09-30T12-00-00  [AGY Bridge]  <-- Anterior inmediata" in output
            or "[1] settings.json.backup-2026-09-30T12-00-00  [AGY Bridge]  <-- Immediate previous" in output
        )
        self.assertIn("[2] settings.json.backup-2026-09-25T10-00-00  [FreeLLMAPI]", output)
        self.assertIn("[3] settings.json.backup-2026-09-20T10-00-00  [Anthropic Original]", output)

    def test_cli_restore_claude_interactive_cancels_with_q(self):
        import io
        from bridge.__main__ import main
        target = self.dir_path / "settings.json"
        target.write_text('{"env": "bridge"}', encoding="utf-8")

        b1 = self.dir_path / "settings.json.backup-1"
        b1.write_text('{"env": "old"}', encoding="utf-8")

        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            with unittest.mock.patch("builtins.input", return_value="q"):
                exit_code = main(["restore-claude", "--path", str(target)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(target.read_text(encoding="utf-8"), '{"env": "bridge"}')
        self.assertTrue(
            "Operación cancelada" in out.getvalue()
            or "Operation cancelled" in out.getvalue()
        )

    def test_cli_restore_claude_interactive_selects_specific_number(self):
        import io
        from bridge.__main__ import main
        target = self.dir_path / "settings.json"
        target.write_text('{"env": "bridge"}', encoding="utf-8")

        b1 = self.dir_path / "settings.json.backup-2026-09-20T10-00-00"
        b1.write_text('{"env": "old"}', encoding="utf-8")
        os.utime(b1, (1000.0, 1000.0))

        b2 = self.dir_path / "settings.json.backup-2026-09-30T12-00-00"
        b2.write_text('{"env": "immediate_previous"}', encoding="utf-8")
        os.utime(b2, (2000.0, 2000.0))

        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            with unittest.mock.patch("builtins.input", return_value="2"):
                exit_code = main(["restore-claude", "--path", str(target)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(target.read_text(encoding="utf-8"), '{"env": "old"}')

    def test_cli_restore_codex_with_latest_flag(self):
        import io
        from bridge.__main__ import main
        target = self.dir_path / "config.toml"
        target.write_text('active = "bridge"\n', encoding="utf-8")

        b = self.dir_path / "config.toml.backup-1"
        b.write_text('active = "native_codex"\n', encoding="utf-8")

        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            exit_code = main(["restore-codex", "--path", str(target), "--latest"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(target.read_text(encoding="utf-8"), 'active = "native_codex"\n')
        self.assertIn("Codex CLI", out.getvalue())

    def test_cli_restore_codex_interactive_displays_distinct_provenance_tags(self):
        import io
        from bridge.__main__ import main
        target = self.dir_path / "config.toml"
        target.write_text('active = "test"', encoding="utf-8")

        b1 = self.dir_path / "config.toml.backup-2026-09-20T10-00-00"
        b1.write_text('[projects]\nactive = "main"', encoding="utf-8")
        os.utime(b1, (1000.0, 1000.0))

        b2 = self.dir_path / "config.toml.backup-2026-09-25T10-00-00"
        b2.write_text('base_url = "http://127.0.0.1:31415/v1"', encoding="utf-8")
        os.utime(b2, (2000.0, 2000.0))

        b3 = self.dir_path / "config.toml.backup-2026-09-30T12-00-00"
        b3.write_text('# agy:start\nmodel = "gemini"\n# agy:end', encoding="utf-8")
        os.utime(b3, (3000.0, 3000.0))

        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            with unittest.mock.patch("builtins.input", return_value="q"):
                main(["restore-codex", "--path", str(target)])

        output = out.getvalue()
        self.assertTrue(
            "[1] config.toml.backup-2026-09-30T12-00-00  [AGY Bridge]  <-- Anterior inmediata" in output
            or "[1] config.toml.backup-2026-09-30T12-00-00  [AGY Bridge]  <-- Immediate previous" in output
        )
        self.assertIn("[2] config.toml.backup-2026-09-25T10-00-00  [FreeLLMAPI]", output)
        self.assertIn("[3] config.toml.backup-2026-09-20T10-00-00  [Codex Original]", output)


class TestUninstall(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.daemon_dir = self.root / ".agy-bridge"
        self.daemon_dir.mkdir(parents=True, exist_ok=True)
        self.bin_dir = self.root / ".local" / "bin"
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        self.claude_dir = self.root / ".claude"
        self.claude_dir.mkdir(parents=True, exist_ok=True)
        self.claude_settings = self.claude_dir / "settings.json"
        self.codex_dir = self.root / ".codex"
        self.codex_dir.mkdir(parents=True, exist_ok=True)
        self.codex_config = self.codex_dir / "config.toml"
        self.hermes_dir = self.root / ".hermes"
        self.hermes_dir.mkdir(parents=True, exist_ok=True)
        self.hermes_config = self.hermes_dir / "config.yaml"

    def tearDown(self):
        self.temp_dir.cleanup()

    @unittest.mock.patch("bridge.daemon.stop_daemon")
    def test_uninstall_stops_daemon_and_removes_daemon_dir(self, mock_stop_daemon):
        mock_stop_daemon.return_value = {"status": "stopped", "pid": 12345}
        (self.daemon_dir / "bridge.log").write_text("log content", encoding="utf-8")

        result = uninstall(
            daemon_dir=self.daemon_dir,
            bin_dir=self.bin_dir,
            claude_settings_path=self.claude_settings,
            codex_config_path=self.codex_config,
            hermes_config_path=self.hermes_config,
        )

        mock_stop_daemon.assert_called_once_with(pid_file=self.daemon_dir / "bridge.pid")
        self.assertTrue(result["daemon_stopped"])
        self.assertTrue(result["daemon_dir_removed"])
        self.assertFalse(self.daemon_dir.exists())

    def test_uninstall_removes_launcher_binaries(self):
        bin1 = self.bin_dir / "agy-bridge"
        bin1.write_text("#!/bin/sh\n", encoding="utf-8")
        bin2 = self.bin_dir / "agy-model-bridge"
        bin2.symlink_to(bin1)

        result = uninstall(
            daemon_dir=self.daemon_dir,
            bin_dir=self.bin_dir,
            claude_settings_path=self.claude_settings,
            codex_config_path=self.codex_config,
            hermes_config_path=self.hermes_config,
        )

        self.assertFalse(bin1.exists())
        self.assertFalse(bin2.exists())
        self.assertFalse(bin2.is_symlink())
        self.assertIn(str(bin1), result["binaries_removed"])
        self.assertIn(str(bin2), result["binaries_removed"])

    def test_uninstall_restores_claude_and_codex_from_backups(self):
        # Create backups
        b_claude = self.claude_dir / "settings.json.backup-2026-09-20T10-00-00"
        b_claude.write_text(json.dumps({"env": {"CUSTOM": "original"}}), encoding="utf-8")
        self.claude_settings.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:24980"}}), encoding="utf-8")

        b_codex = self.codex_dir / "config.toml.backup-2026-09-20T10-00-00"
        b_codex.write_text('model = "original-gpt"\n', encoding="utf-8")
        self.codex_config.write_text('# agy:start\nmodel = "gemini"\n# agy:end\n', encoding="utf-8")

        b_hermes = self.hermes_dir / "config.yaml.backup-2026-09-20T10-00-00"
        b_hermes.write_text('model:\n  default: "original-hermes"\n', encoding="utf-8")
        self.hermes_config.write_text('# agy:start\nmodel:\n  default: "gemini"\n# agy:end\n', encoding="utf-8")

        result = uninstall(
            daemon_dir=self.daemon_dir,
            bin_dir=self.bin_dir,
            claude_settings_path=self.claude_settings,
            codex_config_path=self.codex_config,
            hermes_config_path=self.hermes_config,
            restore_configs=True,
            purge_backups=False,
        )

        self.assertTrue(result["claude_restored"])
        self.assertTrue(result["codex_restored"])
        self.assertTrue(result["hermes_restored"])
        self.assertFalse(result["backups_purged"])

        # Verify content restored
        claude_data = json.loads(self.claude_settings.read_text(encoding="utf-8"))
        self.assertEqual(claude_data, {"env": {"CUSTOM": "original"}})
        self.assertEqual(self.codex_config.read_text(encoding="utf-8"), 'model = "original-gpt"\n')
        self.assertEqual(self.hermes_config.read_text(encoding="utf-8"), 'model:\n  default: "original-hermes"\n')
        # Backups still exist since purge_backups was False
        self.assertTrue(b_claude.exists())
        self.assertTrue(b_codex.exists())
        self.assertTrue(b_hermes.exists())

    def test_uninstall_surgically_cleans_configs_when_no_backups(self):
        # Claude config with agy keys and modelPicker, but user custom keys preserved
        claude_initial = {
            "outputStyle": "verbose",
            "permissions": {"allowAll": False},
            "env": {
                "USER_KEY": "keep_me",
                "ANTHROPIC_BASE_URL": "http://127.0.0.1:24980",
                "ANTHROPIC_AUTH_TOKEN": "antigravity",
                "ANTHROPIC_MODEL": "gemini-3.8-flash-high",
                "ANTHROPIC_DEFAULT_SONNET_MODEL": "gemini-3.8-flash-high",
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": "gemini-3.8-flash-high",
                "ANTHROPIC_DEFAULT_OPUS_MODEL": "gemini-3.8-flash-high",
                "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "1048576",
                "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
            },
            "modelPicker": {
                "options": [
                    {"model": "gemini-3.8-flash-high", "label": "Gemini 3.8 Flash"},
                    {"model": "gemini-3.7-flash-tiered", "label": "Gemini 3.7 Flash"},
                ],
                "replaceBuiltInOptions": False,
            },
        }
        self.claude_settings.write_text(json.dumps(claude_initial, indent=2), encoding="utf-8")

        # Codex config with user tables and delimited agy block
        codex_initial = (
            "[projects]\n"
            'active = "my-project"\n\n'
            '# model = "old-model"  # agy-override\n'
            '# model_provider = "old-provider"  # agy-override\n'
            "# agy:start\n"
            'model = "gemini-3.8-flash-high"\n'
            'model_provider = "agy"\n\n'
            "[model_providers.agy]\n"
            'base_url = "http://127.0.0.1:24980/v1"\n'
            "# agy:end\n\n"
            "[mcp_servers]\n"
            's1 = "url"\n'
        )
        self.codex_config.write_text(codex_initial, encoding="utf-8")

        result = uninstall(
            daemon_dir=self.daemon_dir,
            bin_dir=self.bin_dir,
            claude_settings_path=self.claude_settings,
            codex_config_path=self.codex_config,
            restore_configs=True,
            purge_backups=False,
        )

        self.assertTrue(result["claude_restored"])
        self.assertTrue(result["codex_restored"])

        # Check Claude surgical cleaning
        claude_cleaned = json.loads(self.claude_settings.read_text(encoding="utf-8"))
        self.assertEqual(claude_cleaned["outputStyle"], "verbose")
        self.assertEqual(claude_cleaned["permissions"], {"allowAll": False})
        self.assertEqual(claude_cleaned["env"], {"USER_KEY": "keep_me"})
        self.assertNotIn("modelPicker", claude_cleaned)

        # Check Codex surgical cleaning
        codex_cleaned = self.codex_config.read_text(encoding="utf-8")
        self.assertNotIn("# agy:start", codex_cleaned)
        self.assertNotIn("# agy:end", codex_cleaned)
        self.assertNotIn("model_providers.agy", codex_cleaned)
        self.assertIn("[projects]\nactive = \"my-project\"", codex_cleaned)
        self.assertIn("[mcp_servers]\ns1 = \"url\"", codex_cleaned)
        self.assertIn('model = "old-model"', codex_cleaned)
        self.assertIn('model_provider = "old-provider"', codex_cleaned)

    def test_uninstall_restore_configs_false_leaves_configs_untouched(self):
        claude_content = '{\n  "env": {\n    "ANTHROPIC_MODEL": "gemini"\n  }\n}\n'
        self.claude_settings.write_text(claude_content, encoding="utf-8")
        codex_content = '# agy:start\nmodel = "gemini"\n# agy:end\n'
        self.codex_config.write_text(codex_content, encoding="utf-8")

        result = uninstall(
            daemon_dir=self.daemon_dir,
            bin_dir=self.bin_dir,
            claude_settings_path=self.claude_settings,
            codex_config_path=self.codex_config,
            restore_configs=False,
            purge_backups=False,
        )

        self.assertFalse(result["claude_restored"])
        self.assertFalse(result["codex_restored"])
        self.assertEqual(self.claude_settings.read_text(encoding="utf-8"), claude_content)
        self.assertEqual(self.codex_config.read_text(encoding="utf-8"), codex_content)

    def test_uninstall_purge_backups_deletes_all_backup_files(self):
        b1 = self.claude_dir / "settings.json.backup-1"
        b1.write_text("{}", encoding="utf-8")
        b2 = self.claude_dir / "settings.json.backup-2"
        b2.write_text("{}", encoding="utf-8")
        b3 = self.codex_dir / "config.toml.backup-1"
        b3.write_text("test", encoding="utf-8")

        result = uninstall(
            daemon_dir=self.daemon_dir,
            bin_dir=self.bin_dir,
            claude_settings_path=self.claude_settings,
            codex_config_path=self.codex_config,
            restore_configs=True,
            purge_backups=True,
        )

        self.assertTrue(result["backups_purged"])
        self.assertFalse(b1.exists())
        self.assertFalse(b2.exists())
        self.assertFalse(b3.exists())

    def test_uninstall_handles_nonexistent_paths_gracefully(self):
        nonexistent_root = self.root / "empty_dir"
        result = uninstall(
            daemon_dir=nonexistent_root / "daemon",
            bin_dir=nonexistent_root / "bin",
            claude_settings_path=nonexistent_root / "settings.json",
            codex_config_path=nonexistent_root / "config.toml",
            restore_configs=True,
            purge_backups=True,
        )

        self.assertFalse(result["daemon_stopped"])
        self.assertFalse(result["claude_restored"])
        self.assertFalse(result["codex_restored"])
        self.assertEqual(result["binaries_removed"], [])
        self.assertFalse(result["daemon_dir_removed"])
        self.assertTrue(result["backups_purged"])


class TestCLIUninstall(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    @unittest.mock.patch("bridge.__main__.uninstall")
    def test_cli_uninstall_interactive_cancel_on_no_or_enter(self, mock_uninstall):
        import io
        from bridge.__main__ import main

        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            with unittest.mock.patch("builtins.input", return_value="n"):
                exit_code = main(["uninstall"])

        self.assertEqual(exit_code, 0)
        mock_uninstall.assert_not_called()
        self.assertTrue(
            "cancelada" in out.getvalue().lower()
            or "cancelled" in out.getvalue().lower()
        )

    @unittest.mock.patch("bridge.__main__.uninstall")
    def test_cli_uninstall_interactive_confirm_on_s(self, mock_uninstall):
        import io
        from bridge.__main__ import main

        mock_uninstall.return_value = {
            "daemon_stopped": True,
            "claude_restored": True,
            "codex_restored": True,
            "binaries_removed": ["/bin/agy-bridge"],
            "daemon_dir_removed": True,
            "backups_purged": False,
        }

        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            with unittest.mock.patch("builtins.input", return_value="s"):
                exit_code = main(["uninstall"])

        self.assertEqual(exit_code, 0)
        mock_uninstall.assert_called_once_with(restore_configs=True, purge_backups=False)
        self.assertTrue(
            "desinstalado correctamente" in out.getvalue().lower()
            or "uninstalled successfully" in out.getvalue().lower()
        )

    @unittest.mock.patch("bridge.__main__.uninstall")
    def test_cli_uninstall_yes_flag_skips_prompt(self, mock_uninstall):
        import io
        from bridge.__main__ import main

        mock_uninstall.return_value = {
            "daemon_stopped": False,
            "claude_restored": False,
            "codex_restored": False,
            "binaries_removed": [],
            "daemon_dir_removed": False,
            "backups_purged": False,
        }

        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            with unittest.mock.patch("builtins.input", side_effect=AssertionError("Prompt should not be called")):
                exit_code = main(["uninstall", "--yes"])

        self.assertEqual(exit_code, 0)
        mock_uninstall.assert_called_once_with(restore_configs=True, purge_backups=False)

    @unittest.mock.patch("bridge.__main__.uninstall")
    def test_cli_uninstall_short_y_flag_skips_prompt(self, mock_uninstall):
        from bridge.__main__ import main

        mock_uninstall.return_value = {
            "daemon_stopped": False,
            "claude_restored": False,
            "codex_restored": False,
            "binaries_removed": [],
            "daemon_dir_removed": False,
            "backups_purged": False,
        }

        with unittest.mock.patch("sys.stdout"):
            with unittest.mock.patch("builtins.input", side_effect=AssertionError("Prompt should not be called")):
                exit_code = main(["uninstall", "-y"])

        self.assertEqual(exit_code, 0)
        mock_uninstall.assert_called_once_with(restore_configs=True, purge_backups=False)

    @unittest.mock.patch("bridge.__main__.uninstall")
    def test_cli_uninstall_flags_purge_and_keep_configs(self, mock_uninstall):
        from bridge.__main__ import main

        mock_uninstall.return_value = {
            "daemon_stopped": True,
            "claude_restored": False,
            "codex_restored": False,
            "binaries_removed": [],
            "daemon_dir_removed": True,
            "backups_purged": True,
        }

        with unittest.mock.patch("sys.stdout"):
            exit_code = main(["uninstall", "-y", "--purge", "--keep-configs"])

        self.assertEqual(exit_code, 0)
        mock_uninstall.assert_called_once_with(restore_configs=False, purge_backups=True)

    def test_cli_uninstall_help(self):
        from bridge.__main__ import main

        with self.assertRaises(SystemExit) as cm:
            with unittest.mock.patch("sys.stdout"):
                main(["uninstall", "--help"])
        self.assertEqual(cm.exception.code, 0)


class TestUpdateInstallation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name) / "core"
        self.repo_dir.mkdir(parents=True)
        (self.repo_dir / ".git").mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    @unittest.mock.patch("bridge.setup.subprocess.run")
    @unittest.mock.patch("bridge.daemon.start_daemon")
    @unittest.mock.patch("bridge.daemon.stop_daemon")
    @unittest.mock.patch("bridge.daemon.is_pid_alive")
    @unittest.mock.patch("bridge.daemon.read_pid")
    def test_update_success_with_daemon_restart(
        self, mock_read_pid, mock_is_alive, mock_stop, mock_start, mock_run
    ):
        mock_run.return_value = unittest.mock.MagicMock(
            returncode=0,
            stdout="Updating 1234abc..5678def\nFast-forward\n bridge/setup.py | 10 +\n 1 file changed\n",
            stderr="",
        )
        mock_read_pid.return_value = 4242
        mock_is_alive.return_value = True
        mock_stop.return_value = {"status": "stopped", "pid": 4242}
        mock_start.return_value = {"status": "started", "pid": 4243}

        result = update_installation(
            core_dir=self.repo_dir,
            restart_daemon_if_running=True,
        )

        self.assertEqual(result["status"], "updated")
        self.assertTrue(result["restarted_daemon"])
        self.assertEqual(result["version"], "0.8.0")
        mock_run.assert_called_once_with(
            ["git", "-C", str(self.repo_dir), "pull", "--ff-only"],
            capture_output=True,
            text=True,
        )
        mock_stop.assert_called_once()
        mock_start.assert_called_once_with(no_open=True)

    @unittest.mock.patch("bridge.setup.subprocess.run")
    @unittest.mock.patch("bridge.daemon.start_daemon")
    @unittest.mock.patch("bridge.daemon.stop_daemon")
    @unittest.mock.patch("bridge.daemon.is_pid_alive")
    @unittest.mock.patch("bridge.daemon.read_pid")
    def test_update_success_daemon_not_running(
        self, mock_read_pid, mock_is_alive, mock_stop, mock_start, mock_run
    ):
        mock_run.return_value = unittest.mock.MagicMock(
            returncode=0,
            stdout="Updating 1234abc..5678def\nFast-forward\n",
            stderr="",
        )
        mock_read_pid.return_value = None
        mock_is_alive.return_value = False

        result = update_installation(
            core_dir=self.repo_dir,
            restart_daemon_if_running=True,
        )

        self.assertEqual(result["status"], "updated")
        self.assertFalse(result["restarted_daemon"])
        mock_stop.assert_not_called()
        mock_start.assert_not_called()

    @unittest.mock.patch("bridge.setup.subprocess.run")
    @unittest.mock.patch("bridge.daemon.stop_daemon")
    def test_update_already_up_to_date(self, mock_stop, mock_run):
        mock_run.return_value = unittest.mock.MagicMock(
            returncode=0,
            stdout="Already up to date.\n",
            stderr="",
        )

        result = update_installation(
            core_dir=self.repo_dir,
            restart_daemon_if_running=True,
        )

        self.assertEqual(result["status"], "already_up_to_date")
        self.assertFalse(result["restarted_daemon"])
        mock_stop.assert_not_called()

    def test_update_nonexistent_or_non_git_directory(self):
        non_git_dir = Path(self.temp_dir.name) / "not_a_repo"
        non_git_dir.mkdir()

        result = update_installation(
            core_dir=non_git_dir,
        )

        self.assertEqual(result["status"], "error")
        self.assertFalse(result["restarted_daemon"])
        self.assertIn("git", result["message"].lower())

    @unittest.mock.patch("bridge.setup.subprocess.run")
    def test_update_git_pull_failure(self, mock_run):
        mock_run.return_value = unittest.mock.MagicMock(
            returncode=1,
            stdout="",
            stderr="fatal: unable to access: Could not resolve host\n",
        )

        result = update_installation(
            core_dir=self.repo_dir,
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("Could not resolve host", result["message"])
        self.assertFalse(result["restarted_daemon"])

    @unittest.mock.patch("bridge.setup.subprocess.run")
    def test_update_git_command_missing(self, mock_run):
        mock_run.side_effect = FileNotFoundError("git not found")

        result = update_installation(
            core_dir=self.repo_dir,
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("git", result["message"].lower())
        self.assertFalse(result["restarted_daemon"])

    @unittest.mock.patch("bridge.setup.subprocess.run")
    def test_update_discovers_default_core_dir(self, mock_run):
        mock_run.return_value = unittest.mock.MagicMock(
            returncode=0,
            stdout="Already up to date.\n",
            stderr="",
        )
        fake_home = Path(self.temp_dir.name) / "fake_home"
        core_dir = fake_home / ".agy-bridge" / "core"
        (core_dir / ".git").mkdir(parents=True)

        with unittest.mock.patch("pathlib.Path.home", return_value=fake_home):
            result = update_installation(core_dir=None)

        self.assertEqual(result["status"], "already_up_to_date")
        mock_run.assert_called_once_with(
            ["git", "-C", str(core_dir), "pull", "--ff-only"],
            capture_output=True,
            text=True,
        )


class TestCLIUpdateAndVersion(unittest.TestCase):
    @unittest.mock.patch("bridge.__main__.update_installation")
    def test_cli_update_success(self, mock_update):
        from bridge.__main__ import main
        import io
        from contextlib import redirect_stdout

        mock_update.return_value = {
            "status": "updated",
            "message": "Repository updated successfully.",
            "restarted_daemon": True,
            "version": "0.4.0",
        }

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = main(["update"])

        self.assertEqual(exit_code, 0)
        output = f.getvalue()
        self.assertIn("0.4.0", output)
        self.assertTrue("actualizado" in output.lower() or "updated" in output.lower())
        mock_update.assert_called_once_with(core_dir=None, restart_daemon_if_running=True)

    @unittest.mock.patch("bridge.__main__.update_installation")
    def test_cli_upgrade_alias(self, mock_update):
        from bridge.__main__ import main
        import io
        from contextlib import redirect_stdout

        mock_update.return_value = {
            "status": "already_up_to_date",
            "message": "Already up to date.",
            "restarted_daemon": False,
            "version": "0.4.0",
        }

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = main(["upgrade"])

        self.assertEqual(exit_code, 0)
        output = f.getvalue()
        self.assertIn("0.4.0", output)
        mock_update.assert_called_once_with(core_dir=None, restart_daemon_if_running=True)

    @unittest.mock.patch("bridge.__main__.update_installation")
    def test_cli_update_error(self, mock_update):
        from bridge.__main__ import main
        import io
        from contextlib import redirect_stdout

        mock_update.return_value = {
            "status": "error",
            "message": "git pull failed due to conflict",
            "restarted_daemon": False,
            "version": "0.4.0",
        }

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = main(["update"])

        self.assertEqual(exit_code, 1)
        output = f.getvalue()
        self.assertIn("git pull failed", output)

    def test_cli_version_flags(self):
        from bridge.__main__ import main
        import io
        from contextlib import redirect_stdout

        for flag in ("--version", "-v"):
            f = io.StringIO()
            with redirect_stdout(f):
                exit_code = main([flag])
            self.assertEqual(exit_code, 0)
            self.assertEqual(f.getvalue().strip(), "agy-bridge v0.8.0")

    def test_cli_subcommand_version_flags(self):
        from bridge.__main__ import main
        import io
        from contextlib import redirect_stdout

        for flag in ("--version", "-v"):
            f = io.StringIO()
            with redirect_stdout(f):
                exit_code = main(["update", flag])
            self.assertEqual(exit_code, 0)
            self.assertEqual(f.getvalue().strip(), "agy-bridge v0.8.0")

    def test_version_unification(self):
        import bridge
        from pathlib import Path
        import re

        self.assertEqual(bridge.__version__, "0.8.0")
        pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
        pyproject_text = pyproject_path.read_text(encoding="utf-8")
        match = re.search(r'version\s*=\s*"([^"]+)"', pyproject_text)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "0.8.0")


class TestClientConfiguratorRegistry(unittest.TestCase):
    def test_default_configurators_registered(self):
        claude_cfg = get_configurator("claude")
        self.assertIsInstance(claude_cfg, ClaudeConfigurator)
        self.assertEqual(claude_cfg.name, "claude")
        self.assertEqual(claude_cfg.display_name, "Claude Code")

        codex_cfg = get_configurator("codex")
        self.assertIsInstance(codex_cfg, CodexConfigurator)
        self.assertEqual(codex_cfg.name, "codex")
        self.assertEqual(codex_cfg.display_name, "Codex CLI")

        hermes_cfg = get_configurator("hermes")
        self.assertIsInstance(hermes_cfg, HermesConfigurator)
        self.assertEqual(hermes_cfg.name, "hermes")
        self.assertEqual(hermes_cfg.display_name, "Hermes Agent")

        opencode_cfg = get_configurator("opencode")
        self.assertIsInstance(opencode_cfg, OpenCodeConfigurator)
        self.assertEqual(opencode_cfg.name, "opencode")
        self.assertEqual(opencode_cfg.display_name, "OpenCode")

        openclaw_cfg = get_configurator("openclaw")
        self.assertIsInstance(openclaw_cfg, OpenClawConfigurator)
        self.assertEqual(openclaw_cfg.name, "openclaw")
        self.assertEqual(openclaw_cfg.display_name, "OpenClaw")

    def test_get_configurator_unknown_raises_key_error(self):
        with self.assertRaises(KeyError):
            get_configurator("unknown_client")

    def test_list_configurators(self):
        configurators = list_configurators()
        names = [c.name for c in configurators]
        self.assertIn("claude", names)
        self.assertIn("codex", names)
        self.assertIn("hermes", names)
        self.assertIn("opencode", names)
        self.assertIn("openclaw", names)

    def test_register_custom_configurator(self):
        class DummyConfigurator(ClientConfigurator):
            name = "dummy"
            display_name = "Dummy Client"

            @property
            def default_config_path(self) -> Path:
                return Path("/tmp/dummy.conf")

            def is_configured(self, config_path: Path | None = None) -> bool:
                return False

            def setup(self, base_url: str | None = None, model: str = "gemini-3.8-flash-high", config_path: Path | None = None, **kwargs) -> Path:
                return self.get_config_path(config_path)

            def restore(self, config_path: Path | None = None, backup_path: Path | None = None, **kwargs) -> bool:
                return True

        dummy = DummyConfigurator()
        register_configurator(dummy)
        try:
            self.assertEqual(get_configurator("dummy"), dummy)
            self.assertIn(dummy, list_configurators())
        finally:
            CLIENT_CONFIGURATORS.pop("dummy", None)


class TestClaudeConfiguratorStrategy(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.configurator = ClaudeConfigurator()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_paths(self):
        with unittest.mock.patch("pathlib.Path.home", return_value=self.dir_path):
            self.assertEqual(
                self.configurator.default_config_path,
                self.dir_path / ".claude" / "settings.json",
            )
            self.assertEqual(
                self.configurator.get_config_path(),
                self.dir_path / ".claude" / "settings.json",
            )
        custom = self.dir_path / "custom.json"
        self.assertEqual(self.configurator.get_config_path(custom), custom)

    def test_is_configured_false_when_file_missing_or_clean(self):
        target = self.dir_path / "settings.json"
        self.assertFalse(self.configurator.is_configured(target))

        target.write_text(json.dumps({"env": {"OTHER_KEY": "val"}}), encoding="utf-8")
        self.assertFalse(self.configurator.is_configured(target))

    def test_is_configured_true_after_setup(self):
        target = self.dir_path / "settings.json"
        self.configurator.setup(config_path=target)
        self.assertTrue(self.configurator.is_configured(target))

    def test_restore_from_backup(self):
        target = self.dir_path / "settings.json"
        target.write_text(json.dumps({"env": {"ORIGINAL": "val"}}), encoding="utf-8")

        # Setup creates backup
        self.configurator.setup(config_path=target)
        self.assertTrue(self.configurator.is_configured(target))

        # Restore restores original
        restored = self.configurator.restore(config_path=target)
        self.assertTrue(restored)
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data, {"env": {"ORIGINAL": "val"}})

    def test_restore_surgical_clean_without_backups(self):
        target = self.dir_path / "settings.json"
        target.write_text(
            json.dumps({
                "env": {
                    "USER_KEY": "keep",
                    "ANTHROPIC_BASE_URL": "http://127.0.0.1:24980",
                    "ANTHROPIC_MODEL": "gemini-3.8-flash-high",
                },
                "modelPicker": {"options": [{"model": "gemini-3.8-flash-high"}]},
            }),
            encoding="utf-8",
        )
        self.assertTrue(self.configurator.is_configured(target))

        restored = self.configurator.restore(config_path=target)
        self.assertTrue(restored)
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["env"], {"USER_KEY": "keep"})
        self.assertNotIn("modelPicker", data)

    def test_purge_backups(self):
        target = self.dir_path / "settings.json"
        target.write_text("{}", encoding="utf-8")
        b1 = self.dir_path / "settings.json.backup-2026-09-20T10-00-00"
        b1.write_text("{}", encoding="utf-8")
        b2 = self.dir_path / "settings.json.backup-2026-09-21T10-00-00"
        b2.write_text("{}", encoding="utf-8")

        purged_count = self.configurator.purge_backups(target)
        self.assertEqual(purged_count, 2)
        self.assertEqual(len(self.configurator.list_backups(target)), 0)


class TestCodexConfiguratorStrategy(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.configurator = CodexConfigurator()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_paths(self):
        with unittest.mock.patch("pathlib.Path.home", return_value=self.dir_path):
            self.assertEqual(
                self.configurator.default_config_path,
                self.dir_path / ".codex" / "config.toml",
            )
            self.assertEqual(
                self.configurator.get_config_path(),
                self.dir_path / ".codex" / "config.toml",
            )
        custom = self.dir_path / "custom.toml"
        self.assertEqual(self.configurator.get_config_path(custom), custom)

    def test_is_configured_false_when_file_missing_or_clean(self):
        target = self.dir_path / "config.toml"
        self.assertFalse(self.configurator.is_configured(target))

        target.write_text('personality = "pragmatic"\n', encoding="utf-8")
        self.assertFalse(self.configurator.is_configured(target))

    def test_is_configured_true_after_setup(self):
        target = self.dir_path / "config.toml"
        self.configurator.setup(config_path=target)
        self.assertTrue(self.configurator.is_configured(target))

    def test_restore_from_backup(self):
        target = self.dir_path / "config.toml"
        target.write_text('model = "gpt-original"\n', encoding="utf-8")

        self.configurator.setup(config_path=target)
        self.assertTrue(self.configurator.is_configured(target))

        restored = self.configurator.restore(config_path=target)
        self.assertTrue(restored)
        self.assertEqual(target.read_text(encoding="utf-8"), 'model = "gpt-original"\n')

    def test_restore_surgical_clean_without_backups(self):
        target = self.dir_path / "config.toml"
        target.write_text(
            '[projects]\nactive = "my-prj"\n\n'
            '# model = "old"  # agy-override\n'
            '# agy:start\nmodel = "gemini"\n# agy:end\n',
            encoding="utf-8",
        )
        self.assertTrue(self.configurator.is_configured(target))

        restored = self.configurator.restore(config_path=target)
        self.assertTrue(restored)
        cleaned = target.read_text(encoding="utf-8")
        self.assertNotIn("# agy:start", cleaned)
        self.assertIn('model = "old"', cleaned)

    def test_purge_backups(self):
        target = self.dir_path / "config.toml"
        target.write_text("{}", encoding="utf-8")
        b1 = self.dir_path / "config.toml.backup-2026-09-20T10-00-00"
        b1.write_text("{}", encoding="utf-8")

        purged_count = self.configurator.purge_backups(target)
        self.assertEqual(purged_count, 1)
        self.assertEqual(len(self.configurator.list_backups(target)), 0)


class TestHermesConfiguratorStrategy(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.configurator = HermesConfigurator()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_paths(self):
        with unittest.mock.patch("pathlib.Path.home", return_value=self.dir_path):
            self.assertEqual(
                self.configurator.default_config_path,
                self.dir_path / ".hermes" / "config.yaml",
            )
            self.assertEqual(
                self.configurator.get_config_path(),
                self.dir_path / ".hermes" / "config.yaml",
            )
        custom = self.dir_path / "custom.yaml"
        self.assertEqual(self.configurator.get_config_path(custom), custom)

    def test_is_configured_false_when_file_missing_or_clean(self):
        target = self.dir_path / "config.yaml"
        self.assertFalse(self.configurator.is_configured(target))

        target.write_text("terminal:\n  theme: dark\n", encoding="utf-8")
        self.assertFalse(self.configurator.is_configured(target))

    def test_is_configured_true_variations(self):
        target = self.dir_path / "config.yaml"
        for sample in (
            "# agy:start\nmodel:\n  default: 'x'\n# agy:end",
            "model_provider: custom:local-(127.0.0.1:24980)",
            "base_url: http://127.0.0.1:24980/v1",
            "provider: custom:local-127.0.0.1:24980",
        ):
            with self.subTest(sample=sample):
                target.write_text(sample, encoding="utf-8")
                self.assertTrue(self.configurator.is_configured(target))

    def test_setup_fresh_file(self):
        target = self.dir_path / "config.yaml"
        res = self.configurator.setup(config_path=target)
        self.assertEqual(res, target)
        self.assertTrue(target.exists())
        self.assertTrue(self.configurator.is_configured(target))
        content = target.read_text(encoding="utf-8")
        self.assertIn("# agy:start", content)
        self.assertIn('default: "gemini-3.8-flash-high"', content)
        self.assertIn('provider: "custom:local-(127.0.0.1:24980)"', content)
        self.assertIn('base_url: "http://127.0.0.1:24980/v1"', content)
        self.assertIn('api_mode: "chat_completions"', content)
        self.assertIn('api_key: "local-bridge"', content)
        self.assertIn("# agy:end", content)

        # Permissions 0o600
        mode = stat.S_IMODE(target.stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_setup_with_existing_file_with_conflict(self):
        target = self.dir_path / "config.yaml"
        initial_content = (
            "terminal:\n"
            "  theme: dark\n"
            "model:\n"
            '  default: "anthropic/claude-3-5-sonnet"\n'
            "  temperature: 0.7\n"
        )
        target.write_text(initial_content, encoding="utf-8")

        res = self.configurator.setup(config_path=target)
        self.assertIsNotNone(res.backup_path)
        self.assertTrue(res.backup_path.exists())

        content = target.read_text(encoding="utf-8")
        self.assertIn("# agy:start", content)
        self.assertIn('default: "gemini-3.8-flash-high"', content)
        self.assertIn("# [agy-disabled] model:", content)
        self.assertIn('# [agy-disabled]   default: "anthropic/claude-3-5-sonnet"', content)
        self.assertIn("# [agy-disabled]   temperature: 0.7", content)
        self.assertIn("terminal:\n  theme: dark", content)

    def test_setup_custom_port_and_url_and_model(self):
        target = self.dir_path / "config.yaml"
        self.configurator.setup(
            config_path=target,
            port=9090,
            model="gemini-3.7-flash",
            auth_token="custom-token",
        )
        content = target.read_text(encoding="utf-8")
        self.assertIn('provider: "custom:local-(127.0.0.1:9090)"', content)
        self.assertIn('base_url: "http://127.0.0.1:9090/v1"', content)
        self.assertIn('default: "gemini-3.7-flash"', content)
        self.assertIn('api_key: "custom-token"', content)

        # Custom URL without /v1 gets /v1 appended
        target2 = self.dir_path / "config2.yaml"
        self.configurator.setup(
            config_path=target2,
            base_url="http://custom.host:1234",
        )
        content2 = target2.read_text(encoding="utf-8")
        self.assertIn('base_url: "http://custom.host:1234/v1"', content2)

    def test_restore_from_backup(self):
        target = self.dir_path / "config.yaml"
        target.write_text('model:\n  default: "original-hermes"\n', encoding="utf-8")

        self.configurator.setup(config_path=target)
        self.assertTrue(self.configurator.is_configured(target))

        restored = self.configurator.restore(config_path=target)
        self.assertTrue(restored)
        self.assertEqual(target.read_text(encoding="utf-8"), 'model:\n  default: "original-hermes"\n')

    def test_restore_surgical_clean_without_backups(self):
        target = self.dir_path / "config.yaml"
        target.write_text(
            "# agy:start\n"
            "model:\n"
            '  default: "gemini-3.8-flash-high"\n'
            '  provider: "custom:local-(127.0.0.1:24980)"\n'
            '  base_url: "http://127.0.0.1:24980/v1"\n'
            '  api_mode: "chat_completions"\n'
            '  api_key: "local-bridge"\n'
            "# agy:end\n\n"
            "terminal:\n"
            "  theme: dark\n"
            "# [agy-disabled] model:\n"
            '# [agy-disabled]   default: "anthropic/claude-3-5-sonnet"\n',
            encoding="utf-8",
        )
        self.assertTrue(self.configurator.is_configured(target))

        restored = self.configurator.restore(config_path=target)
        self.assertTrue(restored)
        cleaned = target.read_text(encoding="utf-8")
        self.assertNotIn("# agy:start", cleaned)
        self.assertNotIn("# [agy-disabled]", cleaned)
        self.assertIn("terminal:\n  theme: dark", cleaned)
        self.assertIn('model:\n  default: "anthropic/claude-3-5-sonnet"', cleaned)

    def test_purge_backups(self):
        target = self.dir_path / "config.yaml"
        target.write_text("model: {}", encoding="utf-8")
        b1 = self.dir_path / "config.yaml.backup-2026-09-20T10-00-00"
        b1.write_text("model: {}", encoding="utf-8")

        purged_count = self.configurator.purge_backups(target)
        self.assertEqual(purged_count, 1)
        self.assertEqual(len(self.configurator.list_backups(target)), 0)


class TestCLIHermes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_setup_hermes_dispatches_with_flags(self):
        from bridge.__main__ import main
        target = self.dir_path / "hermes_config.yaml"
        exit_code = main(["setup-hermes", "--port", "9090", "--model", "gemini-3.8-flash-low", "--path", str(target)])
        self.assertEqual(exit_code, 0)
        self.assertTrue(target.exists())
        content = target.read_text(encoding="utf-8")
        self.assertIn('default: "gemini-3.8-flash-low"', content)
        self.assertIn('provider: "custom:local-(127.0.0.1:9090)"', content)
        self.assertIn('base_url: "http://127.0.0.1:9090/v1"', content)

    def test_cli_setup_hermes_outputs_backup_and_guidance(self):
        import io
        from bridge.__main__ import main
        target = self.dir_path / "hermes_config.yaml"
        target.write_text("model:\n  default: 'old'\n", encoding="utf-8")
        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            exit_code = main(["setup-hermes", "--path", str(target)])
        self.assertEqual(exit_code, 0)
        output = out.getvalue()
        self.assertIn("Backup: ", output)
        self.assertIn(f"Hermes Agent configured successfully at {target}", output)
        self.assertIn("Hermes Agent will read this configuration automatically.", output)
        self.assertTrue(
            "Run 'hermes' or open Hermes Desktop" in output
            or "Ejecutá 'hermes' o abrí Hermes Desktop" in output
        )

    def test_cli_restore_hermes_no_backups_returns_1(self):
        import io
        from bridge.__main__ import main
        target = self.dir_path / "config.yaml"
        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            exit_code = main(["restore-hermes", "--path", str(target)])
        self.assertEqual(exit_code, 1)

    def test_cli_restore_hermes_with_latest_flag(self):
        import io
        from bridge.__main__ import main
        target = self.dir_path / "config.yaml"
        target.write_text("model: bridge", encoding="utf-8")

        b1 = self.dir_path / "config.yaml.backup-1"
        b1.write_text("model: older", encoding="utf-8")
        os.utime(b1, (1000.0, 1000.0))

        b2 = self.dir_path / "config.yaml.backup-2"
        b2.write_text("model: immediate_previous", encoding="utf-8")
        os.utime(b2, (2000.0, 2000.0))

        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            exit_code = main(["restore-hermes", "--path", str(target), "--latest"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(target.read_text(encoding="utf-8"), "model: immediate_previous")
        self.assertIn("Hermes Agent", out.getvalue())

    def test_cli_restore_hermes_with_backup_flag(self):
        from bridge.__main__ import main
        target = self.dir_path / "config.yaml"
        target.write_text("model: bridge", encoding="utf-8")

        b1 = self.dir_path / "config.yaml.backup-1"
        b1.write_text("model: specific", encoding="utf-8")

        exit_code = main(["restore-hermes", "--path", str(target), "--backup", str(b1)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(target.read_text(encoding="utf-8"), "model: specific")


class TestUninstallDynamicConfigurators(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.daemon_dir = self.root / ".agy-bridge"
        self.daemon_dir.mkdir(parents=True, exist_ok=True)
        self.bin_dir = self.root / ".local" / "bin"
        self.bin_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_uninstall_automatically_handles_registered_3rd_party_configurator(self):
        calls = {"restore": False, "purge": False}
        test_root = self.root

        class MockThirdPartyConfigurator(ClientConfigurator):
            name = "mock3rd"
            display_name = "Mock 3rd Party Client"

            @property
            def default_config_path(self) -> Path:
                return test_root / ".mock3rd" / "config.json"

            def is_configured(self, config_path: Path | None = None) -> bool:
                return True

            def setup(self, base_url: str | None = None, model: str = "gemini-3.8-flash-high", config_path: Path | None = None, **kwargs) -> Path:
                return self.get_config_path(config_path)

            def restore(self, config_path: Path | None = None, backup_path: Path | None = None, **kwargs) -> bool:
                calls["restore"] = True
                return True

            def purge_backups(self, config_path: Path | None = None) -> int:
                calls["purge"] = True
                return 3

        mock_configurator = MockThirdPartyConfigurator()
        register_configurator(mock_configurator)
        try:
            res = uninstall(
                daemon_dir=self.daemon_dir,
                bin_dir=self.bin_dir,
                restore_configs=True,
                purge_backups=True,
            )
            self.assertTrue(calls["restore"])
            self.assertTrue(calls["purge"])
            self.assertIn("mock3rd", res["restored_clients"])
            self.assertTrue(res["restored_clients"]["mock3rd"])
            self.assertIn("claude_restored", res)
            self.assertIn("codex_restored", res)
        finally:
            CLIENT_CONFIGURATORS.pop("mock3rd", None)


class TestStandaloneWrappers(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_wrappers_delegate_to_configurators(self):
        claude_path = self.dir_path / "claude.json"
        codex_path = self.dir_path / "codex.toml"

        p1 = setup_claude(settings_path=claude_path)
        self.assertEqual(p1, claude_path)
        self.assertTrue(get_configurator("claude").is_configured(claude_path))

        p2 = setup_codex(config_path=codex_path)
        self.assertEqual(p2, codex_path)
        self.assertTrue(get_configurator("codex").is_configured(codex_path))

        self.assertTrue(restore_claude(settings_path=claude_path))
        self.assertTrue(restore_codex(config_path=codex_path))

        hermes_path = self.dir_path / "hermes.yaml"
        p3 = setup_hermes(config_path=hermes_path)
        self.assertEqual(p3, hermes_path)
        self.assertTrue(get_configurator("hermes").is_configured(hermes_path))
        self.assertTrue(restore_hermes(config_path=hermes_path))

        opencode_path = self.dir_path / "opencode.json"
        p4 = setup_opencode(config_path=opencode_path)
        self.assertEqual(p4, opencode_path)
        self.assertTrue(get_configurator("opencode").is_configured(opencode_path))
        self.assertTrue(restore_opencode(config_path=opencode_path))

        openclaw_path = self.dir_path / "openclaw.json"
        p5 = setup_openclaw(config_path=openclaw_path)
        self.assertEqual(p5, openclaw_path)
        self.assertTrue(get_configurator("openclaw").is_configured(openclaw_path))
        self.assertTrue(restore_openclaw(config_path=openclaw_path))


class TestOpenCodeConfigurator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.configurator = OpenCodeConfigurator()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_paths(self):
        with unittest.mock.patch("pathlib.Path.home", return_value=self.dir_path):
            self.assertEqual(
                self.configurator.default_config_path,
                self.dir_path / ".config" / "opencode" / "opencode.json",
            )
            # When neither exists, returns default opencode.json
            self.assertEqual(
                self.configurator.get_config_path(),
                self.dir_path / ".config" / "opencode" / "opencode.json",
            )

            # When opencode.jsonc exists and opencode.json does NOT exist: returns opencode.jsonc
            opencode_dir = self.dir_path / ".config" / "opencode"
            opencode_dir.mkdir(parents=True, exist_ok=True)
            jsonc_file = opencode_dir / "opencode.jsonc"
            jsonc_file.write_text("{}", encoding="utf-8")
            self.assertEqual(
                self.configurator.get_config_path(),
                jsonc_file,
            )

            # When opencode.json ALSO exists: returns opencode.json
            json_file = opencode_dir / "opencode.json"
            json_file.write_text("{}", encoding="utf-8")
            self.assertEqual(
                self.configurator.get_config_path(),
                json_file,
            )

        custom = self.dir_path / "custom.json"
        self.assertEqual(self.configurator.get_config_path(custom), custom)

    def test_is_configured_false_when_file_missing_or_clean(self):
        target = self.dir_path / "opencode.json"
        self.assertFalse(self.configurator.is_configured(target))

        target.write_text(json.dumps({"agent": {"test": 1}}), encoding="utf-8")
        self.assertFalse(self.configurator.is_configured(target))

    def test_is_configured_true_variations(self):
        target = self.dir_path / "opencode.json"
        for sample in (
            json.dumps({"provider": {"agy": {"npm": "@ai-sdk/openai-compatible"}}}),
            json.dumps({"model": "agy/gemini-3.8-flash-high"}),
            json.dumps({"provider": {"custom": {"options": {"baseURL": "http://127.0.0.1:24980/v1"}}}}),
            '{"provider": {"agy": {}}}',
            '{"model": "agy/gemini-2.5-pro"}',
        ):
            with self.subTest(sample=sample):
                target.write_text(sample, encoding="utf-8")
                self.assertTrue(self.configurator.is_configured(target))

    def test_setup_fresh_file(self):
        target = self.dir_path / "opencode.json"
        res = self.configurator.setup(config_path=target)
        self.assertEqual(res, target)
        self.assertTrue(target.exists())
        self.assertTrue(self.configurator.is_configured(target))

        # Permissions 0o600
        mode = stat.S_IMODE(target.stat().st_mode)
        self.assertEqual(mode, 0o600)

        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data.get("$schema"), "https://opencode.ai/config.json")
        self.assertEqual(data.get("model"), "agy/gemini-3.8-flash-high")
        self.assertIn("provider", data)
        self.assertIn("agy", data["provider"])

        agy_conf = data["provider"]["agy"]
        self.assertEqual(agy_conf["npm"], "@ai-sdk/openai-compatible")
        self.assertEqual(agy_conf["name"], "AGY Bridge")
        self.assertEqual(
            agy_conf["options"],
            {
                "baseURL": "http://127.0.0.1:24980/v1",
                "apiKey": "local-bridge",
            },
        )
        self.assertIn("models", agy_conf)
        self.assertEqual(
            agy_conf["models"]["gemini-3.8-flash-high"],
            {
                "name": "Gemini 3.8 Flash (High)",
                "limit": {
                    "context": 1048576,
                    "output": 65536,
                },
            },
        )
        self.assertEqual(
            agy_conf["models"]["gemini-2.5-pro"],
            {
                "name": "Gemini 2.5 Pro",
                "limit": {
                    "context": 1048576,
                    "output": 65536,
                },
            },
        )
        self.assertEqual(
            agy_conf["models"]["gemini-2.5-flash"],
            {
                "name": "Gemini 2.5 Flash",
                "limit": {
                    "context": 1048576,
                    "output": 65536,
                },
            },
        )

    def test_setup_preserves_existing_keys_and_other_providers(self):
        target = self.dir_path / "opencode.json"
        initial = {
            "$schema": "https://custom.schema/config.json",
            "agent": {"build": {"tools": ["terminal"]}},
            "permission": {"allow": ["all"]},
            "provider": {
                "anthropic": {
                    "npm": "@ai-sdk/anthropic",
                    "name": "Anthropic",
                }
            },
        }
        target.write_text(json.dumps(initial, indent=2), encoding="utf-8")

        res = self.configurator.setup(config_path=target)
        self.assertIsNotNone(res.backup_path)
        self.assertTrue(res.backup_path.exists())

        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["$schema"], "https://custom.schema/config.json")
        self.assertEqual(data["agent"], {"build": {"tools": ["terminal"]}})
        self.assertEqual(data["permission"], {"allow": ["all"]})
        self.assertEqual(data["model"], "agy/gemini-3.8-flash-high")
        self.assertIn("anthropic", data["provider"])
        self.assertEqual(data["provider"]["anthropic"]["name"], "Anthropic")
        self.assertIn("agy", data["provider"])

    def test_setup_jsonc_with_comments_stripping(self):
        target = self.dir_path / "opencode.jsonc"
        jsonc_content = (
            "{\n"
            "  // This is a single line comment\n"
            '  "agent": {\n'
            '    /* Multiline comment here */\n'
            '    "url": "http://example.com/api//v1"\n'
            "  }\n"
            "}\n"
        )
        target.write_text(jsonc_content, encoding="utf-8")

        res = self.configurator.setup(config_path=target)
        self.assertTrue(target.exists())
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["agent"]["url"], "http://example.com/api//v1")
        self.assertEqual(data["model"], "agy/gemini-3.8-flash-high")
        self.assertIn("agy", data["provider"])

    def test_setup_custom_port_and_url_and_model_and_token(self):
        target = self.dir_path / "opencode.json"
        self.configurator.setup(
            config_path=target,
            port=9090,
            model="gemini-2.5-pro",
            auth_token="custom-secret-key",
        )
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["model"], "agy/gemini-2.5-pro")
        self.assertEqual(data["provider"]["agy"]["options"]["baseURL"], "http://127.0.0.1:9090/v1")
        self.assertEqual(data["provider"]["agy"]["options"]["apiKey"], "custom-secret-key")

        # Custom URL without /v1 gets /v1 appended
        target2 = self.dir_path / "opencode2.json"
        self.configurator.setup(
            config_path=target2,
            base_url="http://custom.host:1234",
        )
        data2 = json.loads(target2.read_text(encoding="utf-8"))
        self.assertEqual(data2["provider"]["agy"]["options"]["baseURL"], "http://custom.host:1234/v1")

    def test_restore_from_backup(self):
        target = self.dir_path / "opencode.json"
        target.write_text(json.dumps({"model": "original-opencode"}), encoding="utf-8")

        self.configurator.setup(config_path=target)
        self.assertTrue(self.configurator.is_configured(target))

        restored = self.configurator.restore(config_path=target)
        self.assertTrue(restored)
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data.get("model"), "original-opencode")

    def test_restore_surgical_clean_without_backups(self):
        target = self.dir_path / "opencode.json"
        data = {
            "$schema": "https://opencode.ai/config.json",
            "model": "agy/gemini-3.8-flash-high",
            "agent": {"tools": ["bash"]},
            "provider": {
                "agy": {"name": "AGY Bridge"},
                "other": {"name": "Other Provider"},
            },
        }
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.assertTrue(self.configurator.is_configured(target))

        restored = self.configurator.restore(config_path=target)
        self.assertTrue(restored)

        cleaned = json.loads(target.read_text(encoding="utf-8"))
        self.assertNotIn("agy", cleaned.get("provider", {}))
        self.assertIn("other", cleaned.get("provider", {}))
        self.assertNotIn("model", cleaned)
        self.assertEqual(cleaned.get("agent"), {"tools": ["bash"]})

    def test_purge_backups(self):
        target = self.dir_path / "opencode.json"
        target.write_text("{}", encoding="utf-8")
        b1 = self.dir_path / "opencode.json.backup-2026-10-02T10-00-00"
        b1.write_text("{}", encoding="utf-8")

        purged_count = self.configurator.purge_backups(target)
        self.assertEqual(purged_count, 1)
        self.assertEqual(len(self.configurator.list_backups(target)), 0)


class TestCLIOpenCode(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_setup_opencode_dispatches_with_flags(self):
        from bridge.__main__ import main
        target = self.dir_path / "opencode_config.json"
        exit_code = main(["setup-opencode", "--port", "9090", "--model", "gemini-2.5-pro", "--path", str(target)])
        self.assertEqual(exit_code, 0)
        self.assertTrue(target.exists())
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["model"], "agy/gemini-2.5-pro")
        self.assertEqual(data["provider"]["agy"]["options"]["baseURL"], "http://127.0.0.1:9090/v1")

    def test_cli_setup_opencode_outputs_backup_and_guidance(self):
        import io
        from bridge.__main__ import main
        target = self.dir_path / "opencode_config.json"
        target.write_text(json.dumps({"model": "old"}), encoding="utf-8")
        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            exit_code = main(["setup-opencode", "--path", str(target)])
        self.assertEqual(exit_code, 0)
        output = out.getvalue()
        self.assertIn("Backup: ", output)
        self.assertIn(f"OpenCode configured successfully at {target}", output)
        self.assertIn("OpenCode will read this configuration automatically.", output)
        self.assertTrue(
            "Run 'opencode' to start coding" in output
            or "Ejecutá 'opencode' para empezar a programar" in output
        )

    def test_cli_restore_opencode_no_backups_returns_1(self):
        import io
        from bridge.__main__ import main
        target = self.dir_path / "opencode.json"
        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            exit_code = main(["restore-opencode", "--path", str(target)])
        self.assertEqual(exit_code, 1)

    def test_cli_restore_opencode_with_latest_flag(self):
        import io
        from bridge.__main__ import main
        target = self.dir_path / "opencode.json"
        target.write_text(json.dumps({"model": "bridge"}), encoding="utf-8")

        b1 = self.dir_path / "opencode.json.backup-1"
        b1.write_text(json.dumps({"model": "older"}), encoding="utf-8")
        os.utime(b1, (1000.0, 1000.0))

        b2 = self.dir_path / "opencode.json.backup-2"
        b2.write_text(json.dumps({"model": "immediate_previous"}), encoding="utf-8")
        os.utime(b2, (2000.0, 2000.0))

        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            exit_code = main(["restore-opencode", "--path", str(target), "--latest"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"model": "immediate_previous"})
        self.assertIn("OpenCode", out.getvalue())

    def test_cli_restore_opencode_with_backup_flag(self):
        from bridge.__main__ import main
        target = self.dir_path / "opencode.json"
        target.write_text(json.dumps({"model": "bridge"}), encoding="utf-8")

        b1 = self.dir_path / "opencode.json.backup-1"
        b1.write_text(json.dumps({"model": "specific"}), encoding="utf-8")

        exit_code = main(["restore-opencode", "--path", str(target), "--backup", str(b1)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"model": "specific"})


class TestUninstallOpenCode(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.daemon_dir = self.root / ".agy-bridge"
        self.daemon_dir.mkdir(parents=True, exist_ok=True)
        self.bin_dir = self.root / ".local" / "bin"
        self.bin_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_uninstall_discovers_and_cleans_opencode(self):
        opencode_config = self.root / ".config" / "opencode" / "opencode.json"
        opencode_config.parent.mkdir(parents=True, exist_ok=True)
        opencode_config.write_text(
            json.dumps({
                "model": "agy/gemini-3.8-flash-high",
                "provider": {"agy": {"name": "AGY Bridge"}},
            }),
            encoding="utf-8",
        )

        res = uninstall(
            daemon_dir=self.daemon_dir,
            bin_dir=self.bin_dir,
            custom_config_paths={"opencode": opencode_config},
            restore_configs=True,
            purge_backups=False,
        )

        self.assertIn("opencode", res["restored_clients"])
        self.assertTrue(res["restored_clients"]["opencode"])
        self.assertTrue(res.get("opencode_restored", False))
        cleaned = json.loads(opencode_config.read_text(encoding="utf-8"))
        self.assertNotIn("agy", cleaned.get("provider", {}))
        self.assertNotIn("model", cleaned)


class TestOpenClawConfigurator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.configurator = OpenClawConfigurator()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_config_path_precedence(self):
        # 1. OPENCLAW_CONFIG_PATH override
        custom_path = self.dir_path / "custom" / "custom_openclaw.json"
        with unittest.mock.patch.dict(os.environ, {"OPENCLAW_CONFIG_PATH": str(custom_path)}):
            self.assertEqual(self.configurator.default_config_path, custom_path)

        # 2. OPENCLAW_STATE_DIR override
        state_dir = self.dir_path / "state"
        with unittest.mock.patch.dict(os.environ, {"OPENCLAW_CONFIG_PATH": "", "OPENCLAW_STATE_DIR": str(state_dir)}):
            self.assertEqual(self.configurator.default_config_path, state_dir / "openclaw.json")

        # 3. OPENCLAW_HOME override
        home_dir = self.dir_path / "openclaw_home"
        with unittest.mock.patch.dict(os.environ, {"OPENCLAW_CONFIG_PATH": "", "OPENCLAW_STATE_DIR": "", "OPENCLAW_HOME": str(home_dir)}):
            self.assertEqual(self.configurator.default_config_path, home_dir / ".openclaw" / "openclaw.json")

        # 4. Fallback default: Path.home() / ".openclaw" / "openclaw.json"
        with unittest.mock.patch.dict(os.environ, {"OPENCLAW_CONFIG_PATH": "", "OPENCLAW_STATE_DIR": "", "OPENCLAW_HOME": ""}):
            with unittest.mock.patch("pathlib.Path.home", return_value=self.dir_path):
                self.assertEqual(self.configurator.default_config_path, self.dir_path / ".openclaw" / "openclaw.json")

    def test_is_configured_false_when_missing_or_clean(self):
        target = self.dir_path / "openclaw.json"
        self.assertFalse(self.configurator.is_configured(target))

        target.write_text(json.dumps({"agents": {"defaults": {"model": {"primary": "openai/gpt-4o"}}}}), encoding="utf-8")
        self.assertFalse(self.configurator.is_configured(target))

    def test_is_configured_true_variations(self):
        target = self.dir_path / "openclaw.json"
        for sample in (
            json.dumps({"models": {"providers": {"agy": {"baseUrl": "http://127.0.0.1:24980/v1"}}}}),
            json.dumps({"agents": {"defaults": {"model": {"primary": "agy/gemini-3.8-flash-high"}}}}),
            json.dumps({"models": {"providers": {"custom": {"baseUrl": "http://127.0.0.1:24980/v1"}}}}),
            '{"models": {"providers": {"agy": {}}}}',
            '{"agents": {"defaults": {"model": {"primary": "agy/gemini-2.5-pro"}}}}',
            '{"models": {"endpoint": "http://localhost:24980/v1"}}',
        ):
            with self.subTest(sample=sample):
                target.write_text(sample, encoding="utf-8")
                self.assertTrue(self.configurator.is_configured(target))

    def test_setup_fresh_file(self):
        target = self.dir_path / "openclaw.json"
        res = self.configurator.setup(config_path=target)
        self.assertEqual(res, target)
        self.assertTrue(target.exists())
        self.assertTrue(self.configurator.is_configured(target))

        # Permissions 0o600
        mode = stat.S_IMODE(target.stat().st_mode)
        self.assertEqual(mode, 0o600)

        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["agents"]["defaults"]["model"]["primary"], "agy/gemini-3.8-flash-high")
        self.assertIn("models", data)
        self.assertIn("providers", data["models"])
        self.assertIn("agy", data["models"]["providers"])

        agy_provider = data["models"]["providers"]["agy"]
        self.assertEqual(agy_provider["baseUrl"], "http://127.0.0.1:24980/v1")
        self.assertEqual(agy_provider["apiKey"], "local-bridge")
        self.assertEqual(agy_provider["api"], "openai-completions")
        self.assertEqual(agy_provider["headers"], {"User-Agent": "openclaw"})
        self.assertEqual(len(agy_provider["models"]), 3)

        expected_models = [
            {
                "id": "gemini-3.8-flash-high",
                "name": "Gemini 3.8 Flash (High)",
                "reasoning": False,
                "input": ["text"],
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                "contextWindow": 1048576,
                "maxTokens": 65536,
            },
            {
                "id": "gemini-2.5-pro",
                "name": "Gemini 2.5 Pro",
                "reasoning": False,
                "input": ["text"],
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                "contextWindow": 1048576,
                "maxTokens": 65536,
            },
            {
                "id": "gemini-2.5-flash",
                "name": "Gemini 2.5 Flash",
                "reasoning": False,
                "input": ["text"],
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                "contextWindow": 1048576,
                "maxTokens": 65536,
            },
        ]
        self.assertEqual(agy_provider["models"], expected_models)

    def test_setup_preserves_existing_keys_and_deep_merges(self):
        target = self.dir_path / "openclaw.json"
        initial = {
            "version": "1.0.0",
            "agents": {
                "defaults": {
                    "timeout": 60,
                    "model": {
                        "fallback": "openai/gpt-4o",
                    },
                },
                "custom_agent": {"tools": ["web_search"]},
            },
            "models": {
                "providers": {
                    "anthropic": {
                        "baseUrl": "https://api.anthropic.com",
                        "apiKey": "sk-ant-123",
                    },
                },
            },
            "channels": {"telegram": {"enabled": True}},
        }
        target.write_text(json.dumps(initial, indent=2), encoding="utf-8")

        res = self.configurator.setup(config_path=target)
        self.assertIsNotNone(res.backup_path)
        self.assertTrue(res.backup_path.exists())

        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(data["channels"], {"telegram": {"enabled": True}})
        self.assertEqual(data["agents"]["custom_agent"], {"tools": ["web_search"]})
        self.assertEqual(data["agents"]["defaults"]["timeout"], 60)
        self.assertEqual(data["agents"]["defaults"]["model"]["fallback"], "openai/gpt-4o")
        self.assertEqual(data["agents"]["defaults"]["model"]["primary"], "agy/gemini-3.8-flash-high")
        self.assertIn("anthropic", data["models"]["providers"])
        self.assertIn("agy", data["models"]["providers"])

    def test_setup_json_with_comments_stripping(self):
        target = self.dir_path / "openclaw.json"
        jsonc_content = (
            "{\n"
            "  // OpenClaw configuration comment\n"
            '  "agents": {\n'
            '    /* Multiline comment */\n'
            '    "defaults": {}\n'
            "  }\n"
            "}\n"
        )
        target.write_text(jsonc_content, encoding="utf-8")

        res = self.configurator.setup(config_path=target)
        self.assertTrue(target.exists())
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["agents"]["defaults"]["model"]["primary"], "agy/gemini-3.8-flash-high")
        self.assertIn("agy", data["models"]["providers"])

    def test_setup_custom_port_and_url_and_model_and_token(self):
        target = self.dir_path / "openclaw.json"
        self.configurator.setup(
            config_path=target,
            port=9090,
            model="gemini-2.5-pro",
            auth_token="custom-secret-key",
        )
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["agents"]["defaults"]["model"]["primary"], "agy/gemini-2.5-pro")
        self.assertEqual(data["models"]["providers"]["agy"]["baseUrl"], "http://127.0.0.1:9090/v1")
        self.assertEqual(data["models"]["providers"]["agy"]["apiKey"], "custom-secret-key")

        # Custom URL without /v1 gets /v1 appended
        target2 = self.dir_path / "openclaw2.json"
        self.configurator.setup(
            config_path=target2,
            base_url="http://custom.host:1234",
        )
        data2 = json.loads(target2.read_text(encoding="utf-8"))
        self.assertEqual(data2["models"]["providers"]["agy"]["baseUrl"], "http://custom.host:1234/v1")

    def test_restore_from_backup(self):
        target = self.dir_path / "openclaw.json"
        target.write_text(json.dumps({"version": "original-openclaw"}), encoding="utf-8")

        self.configurator.setup(config_path=target)
        self.assertTrue(self.configurator.is_configured(target))

        restored = self.configurator.restore(config_path=target)
        self.assertTrue(restored)
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data.get("version"), "original-openclaw")

    def test_restore_surgical_clean_without_backups(self):
        target = self.dir_path / "openclaw.json"
        data = {
            "agents": {
                "defaults": {
                    "timeout": 30,
                    "model": {
                        "primary": "agy/gemini-3.8-flash-high",
                        "fallback": "openai/gpt-4o",
                    },
                },
            },
            "models": {
                "providers": {
                    "agy": {"baseUrl": "http://127.0.0.1:24980/v1"},
                    "other": {"baseUrl": "http://other/v1"},
                },
            },
        }
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.assertTrue(self.configurator.is_configured(target))

        restored = self.configurator.restore(config_path=target)
        self.assertTrue(restored)

        cleaned = json.loads(target.read_text(encoding="utf-8"))
        self.assertNotIn("agy", cleaned.get("models", {}).get("providers", {}))
        self.assertIn("other", cleaned.get("models", {}).get("providers", {}))
        self.assertNotIn("primary", cleaned.get("agents", {}).get("defaults", {}).get("model", {}))
        self.assertEqual(cleaned["agents"]["defaults"]["model"]["fallback"], "openai/gpt-4o")
        self.assertEqual(cleaned["agents"]["defaults"]["timeout"], 30)

    def test_purge_backups(self):
        target = self.dir_path / "openclaw.json"
        target.write_text("{}", encoding="utf-8")
        b1 = self.dir_path / "openclaw.json.backup-2026-10-02T10-00-00"
        b1.write_text("{}", encoding="utf-8")

        purged_count = self.configurator.purge_backups(target)
        self.assertEqual(purged_count, 1)
        self.assertEqual(len(self.configurator.list_backups(target)), 0)


class TestCLIOpenClaw(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_setup_openclaw_dispatches_with_flags(self):
        from bridge.__main__ import main
        target = self.dir_path / "openclaw_config.json"
        exit_code = main(["setup-openclaw", "--port", "9090", "--model", "gemini-2.5-pro", "--path", str(target)])
        self.assertEqual(exit_code, 0)
        self.assertTrue(target.exists())
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["agents"]["defaults"]["model"]["primary"], "agy/gemini-2.5-pro")
        self.assertEqual(data["models"]["providers"]["agy"]["baseUrl"], "http://127.0.0.1:9090/v1")

    def test_cli_setup_openclaw_outputs_backup_and_guidance(self):
        import io
        from bridge.__main__ import main
        target = self.dir_path / "openclaw_config.json"
        target.write_text(json.dumps({"version": "old"}), encoding="utf-8")
        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            exit_code = main(["setup-openclaw", "--path", str(target)])
        self.assertEqual(exit_code, 0)
        output = out.getvalue()
        self.assertIn("Backup: ", output)
        self.assertIn(f"OpenClaw configured successfully at {target}", output)
        self.assertIn("OpenClaw will read this configuration automatically.", output)
        self.assertTrue(
            "Run 'openclaw gateway' or 'openclaw agent'" in output
            or "Ejecutá 'openclaw gateway' o 'openclaw agent'" in output
        )

    def test_cli_restore_openclaw_no_backups_returns_1(self):
        import io
        from bridge.__main__ import main
        target = self.dir_path / "openclaw.json"
        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            exit_code = main(["restore-openclaw", "--path", str(target)])
        self.assertEqual(exit_code, 1)

    def test_cli_restore_openclaw_with_latest_flag(self):
        import io
        from bridge.__main__ import main
        target = self.dir_path / "openclaw.json"
        target.write_text(json.dumps({"version": "bridge"}), encoding="utf-8")

        b1 = self.dir_path / "openclaw.json.backup-1"
        b1.write_text(json.dumps({"version": "older"}), encoding="utf-8")
        os.utime(b1, (1000.0, 1000.0))

        b2 = self.dir_path / "openclaw.json.backup-2"
        b2.write_text(json.dumps({"version": "immediate_previous"}), encoding="utf-8")
        os.utime(b2, (2000.0, 2000.0))

        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            exit_code = main(["restore-openclaw", "--path", str(target), "--latest"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"version": "immediate_previous"})
        self.assertIn("OpenClaw", out.getvalue())

    def test_cli_restore_openclaw_with_backup_flag(self):
        from bridge.__main__ import main
        target = self.dir_path / "openclaw.json"
        target.write_text(json.dumps({"version": "bridge"}), encoding="utf-8")

        b1 = self.dir_path / "openclaw.json.backup-1"
        b1.write_text(json.dumps({"version": "specific"}), encoding="utf-8")

        exit_code = main(["restore-openclaw", "--path", str(target), "--backup", str(b1)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"version": "specific"})


class TestUninstallOpenClaw(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.daemon_dir = self.root / ".agy-bridge"
        self.daemon_dir.mkdir(parents=True, exist_ok=True)
        self.bin_dir = self.root / ".local" / "bin"
        self.bin_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_uninstall_discovers_and_cleans_openclaw(self):
        openclaw_config = self.root / ".openclaw" / "openclaw.json"
        openclaw_config.parent.mkdir(parents=True, exist_ok=True)
        openclaw_config.write_text(
            json.dumps({
                "agents": {"defaults": {"model": {"primary": "agy/gemini-3.8-flash-high"}}},
                "models": {"providers": {"agy": {"baseUrl": "http://127.0.0.1:24980/v1"}}},
            }),
            encoding="utf-8",
        )

        res = uninstall(
            daemon_dir=self.daemon_dir,
            bin_dir=self.bin_dir,
            custom_config_paths={"openclaw": openclaw_config},
            restore_configs=True,
            purge_backups=False,
        )

        self.assertIn("openclaw", res["restored_clients"])
        self.assertTrue(res["restored_clients"]["openclaw"])
        self.assertTrue(res.get("openclaw_restored", False))
        cleaned = json.loads(openclaw_config.read_text(encoding="utf-8"))
        self.assertNotIn("agy", cleaned.get("models", {}).get("providers", {}))
        self.assertNotIn("primary", cleaned.get("agents", {}).get("defaults", {}).get("model", {}))

    def test_uninstall_kwarg_openclaw_config_path(self):
        openclaw_config = self.root / ".openclaw" / "openclaw.json"
        openclaw_config.parent.mkdir(parents=True, exist_ok=True)
        openclaw_config.write_text(
            json.dumps({
                "agents": {"defaults": {"model": {"primary": "agy/gemini-3.8-flash-high"}}},
                "models": {"providers": {"agy": {"baseUrl": "http://127.0.0.1:24980/v1"}}},
            }),
            encoding="utf-8",
        )

        res = uninstall(
            daemon_dir=self.daemon_dir,
            bin_dir=self.bin_dir,
            openclaw_config_path=openclaw_config,
            restore_configs=True,
            purge_backups=False,
        )

        self.assertIn("openclaw", res["restored_clients"])
        self.assertTrue(res["restored_clients"]["openclaw"])
        self.assertTrue(res.get("openclaw_restored", False))
        cleaned = json.loads(openclaw_config.read_text(encoding="utf-8"))
        self.assertNotIn("agy", cleaned.get("models", {}).get("providers", {}))


if __name__ == "__main__":
    unittest.main()



