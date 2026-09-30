import json
import os
import re
import stat
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from bridge.setup import (
    atomic_write_file,
    create_backup,
    describe_backup,
    list_backups,
    restore_backup,
    setup_claude,
    setup_codex,
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
            ["restore-claude", "--help"],
            ["restore-codex", "--help"],
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
        self.assertIn("No se encontraron backups", out.getvalue())

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
        self.assertIn("Restaurada configuración desde:", out.getvalue())
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
        self.assertIn("[1] settings.json.backup-2026-09-30T12-00-00  [Anthropic Original]  <-- Anterior inmediata", output)
        self.assertIn("[2] settings.json.backup-2026-09-20T10-00-00  [Anthropic Original]", output)
        prompt_arg = mock_input.call_args[0][0]
        self.assertIn("Ingrese un número (1-2)", prompt_arg)
        self.assertIn("presione Enter para [1]", prompt_arg)
        self.assertIn("'q' para cancelar", prompt_arg)

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
        self.assertIn("[1] settings.json.backup-2026-09-30T12-00-00  [AGY Bridge]  <-- Anterior inmediata", output)
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
        self.assertIn("Operación cancelada", out.getvalue())

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
        self.assertIn("[1] config.toml.backup-2026-09-30T12-00-00  [AGY Bridge]  <-- Anterior inmediata", output)
        self.assertIn("[2] config.toml.backup-2026-09-25T10-00-00  [FreeLLMAPI]", output)
        self.assertIn("[3] config.toml.backup-2026-09-20T10-00-00  [Codex Original]", output)


if __name__ == "__main__":
    unittest.main()

