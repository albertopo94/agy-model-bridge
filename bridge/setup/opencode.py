"""Configurator strategy and setup functions for OpenCode CLI."""

import json
from pathlib import Path
from typing import Any, cast

from bridge.setup.base import ClientConfigurator, ConfigPath, get_configurator
from bridge.setup.common import (
    _strip_json_comments,
    atomic_write_file,
    create_backup,
    get_active_api_key,
    restore_backup,
)


class OpenCodeConfigurator(ClientConfigurator):
    """Configurator strategy for OpenCode CLI."""

    name = "opencode"
    display_name = "OpenCode"

    @property
    def default_config_path(self) -> Path:
        return Path.home() / ".config" / "opencode" / "opencode.json"

    def get_config_path(self, custom_path: Path | None = None) -> Path:
        if custom_path is not None:
            return Path(custom_path)
        jsonc_path = Path.home() / ".config" / "opencode" / "opencode.jsonc"
        json_path = self.default_config_path
        if jsonc_path.exists() and not json_path.exists():
            return jsonc_path
        return json_path

    def is_configured(self, config_path: Path | None = None) -> bool:
        target = self.get_config_path(config_path)
        if not target.exists() or not target.is_file():
            return False
        try:
            content = target.read_text(encoding="utf-8")
            if not content.strip():
                return False
            data = None
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                cleaned = _strip_json_comments(content)
                try:
                    data = json.loads(cleaned)
                except json.JSONDecodeError:
                    pass
            if isinstance(data, dict):
                provider = data.get("provider")
                if isinstance(provider, dict) and "agy" in provider:
                    return True
                model = str(data.get("model", ""))
                if model.startswith("agy/"):
                    return True
                if isinstance(provider, dict):
                    for prov in provider.values():
                        if isinstance(prov, dict):
                            opts = prov.get("options")
                            if isinstance(opts, dict) and ":24980" in str(opts.get("baseURL", "")):
                                return True
            if '"provider"' in content and '"agy"' in content:
                return True
            if '"model"' in content and "agy/" in content:
                return True
            if ":24980" in content:
                return True
            return False
        except OSError:
            return False

    def setup(
        self,
        base_url: str | None = None,
        model: str = "gemini-3.8-flash-high",
        config_path: Path | None = None,
        **kwargs: Any,
    ) -> Path:
        target = self.get_config_path(config_path)
        port = kwargs.get("port")
        auth_token = kwargs.get("auth_token") or get_active_api_key()

        if base_url:
            resolved_url = base_url.rstrip("/")
            if not resolved_url.endswith("/v1"):
                resolved_url = f"{resolved_url}/v1"
        elif port is not None:
            resolved_url = f"http://127.0.0.1:{port}/v1"
        else:
            resolved_url = "http://127.0.0.1:24980/v1"

        backup_path = None
        config: dict[str, Any] = {}
        if target.exists():
            backup_path = create_backup(target)
            try:
                raw_text = target.read_text(encoding="utf-8").strip()
                if raw_text:
                    try:
                        loaded = json.loads(raw_text)
                    except json.JSONDecodeError:
                        cleaned = _strip_json_comments(raw_text)
                        loaded = json.loads(cleaned)
                    if isinstance(loaded, dict):
                        config = loaded
            except (json.JSONDecodeError, OSError):
                config = {}

        if "$schema" not in config:
            config["$schema"] = "https://opencode.ai/config.json"

        config["model"] = f"agy/{model}"

        provider_map = config.get("provider")
        if not isinstance(provider_map, dict):
            provider_map = {}
            config["provider"] = provider_map

        provider_map["agy"] = {
            "npm": "@ai-sdk/openai-compatible",
            "name": "AGY Bridge",
            "options": {
                "baseURL": resolved_url,
                "apiKey": auth_token,
            },
            "models": {
                "gemini-3.8-flash-high": {
                    "name": "Gemini 3.8 Flash (High)",
                    "limit": {
                        "context": 1048576,
                        "output": 65536,
                    },
                },
                "gemini-2.5-pro": {
                    "name": "Gemini 2.5 Pro",
                    "limit": {
                        "context": 1048576,
                        "output": 65536,
                    },
                },
                "gemini-2.5-flash": {
                    "name": "Gemini 2.5 Flash",
                    "limit": {
                        "context": 1048576,
                        "output": 65536,
                    },
                },
                "claude-sonnet-5-5-high": {
                    "name": "Claude Sonnet 5.5 (High - AGY)",
                    "limit": {
                        "context": 1000000,
                        "output": 128000,
                    },
                },
                "claude-sonnet-5-5-medium": {
                    "name": "Claude Sonnet 5.5 (Medium - AGY)",
                    "limit": {
                        "context": 1000000,
                        "output": 128000,
                    },
                },
                "claude-sonnet-5-5-low": {
                    "name": "Claude Sonnet 5.5 (Low - AGY)",
                    "limit": {
                        "context": 1000000,
                        "output": 128000,
                    },
                },
                "claude-opus-5-5-high": {
                    "name": "Claude Opus 5.5 (High - AGY)",
                    "limit": {
                        "context": 1000000,
                        "output": 128000,
                    },
                },
                "claude-opus-5-5-medium": {
                    "name": "Claude Opus 5.5 (Medium - AGY)",
                    "limit": {
                        "context": 1000000,
                        "output": 128000,
                    },
                },
                "claude-opus-5-5-low": {
                    "name": "Claude Opus 5.5 (Low - AGY)",
                    "limit": {
                        "context": 1000000,
                        "output": 128000,
                    },
                },
                "claude-haiku-5-5-high": {
                    "name": "Claude Haiku 5.5 · High (AGY)",
                    "limit": {
                        "context": 1000000,
                        "output": 128000,
                    },
                },
                "claude-haiku-5-5-medium": {
                    "name": "Claude Haiku 5.5 · Medium (AGY)",
                    "limit": {
                        "context": 1000000,
                        "output": 128000,
                    },
                },
                "claude-haiku-5-5-low": {
                    "name": "Claude Haiku 5.5 · Low (AGY)",
                    "limit": {
                        "context": 1000000,
                        "output": 128000,
                    },
                },
            },
        }

        formatted_json = json.dumps(config, indent=2) + "\n"
        atomic_write_file(target, formatted_json, mode=0o600)
        res = ConfigPath(target)
        res.backup_path = backup_path
        return res

    def restore(
        self,
        config_path: Path | None = None,
        backup_path: Path | None = None,
        **kwargs: Any,
    ) -> bool:
        target = self.get_config_path(config_path)
        if backup_path is not None:
            try:
                restore_backup(target, backup_path=backup_path)
                return True
            except (OSError, FileNotFoundError):
                return False

        backups = self.list_backups(target)
        if backups:
            try:
                restore_backup(target, backup_path=backups[0])
                return True
            except OSError:
                return False
        elif target.exists() and target.is_file():
            try:
                raw_text = target.read_text(encoding="utf-8").strip()
                if raw_text:
                    try:
                        config = json.loads(raw_text)
                    except json.JSONDecodeError:
                        cleaned = _strip_json_comments(raw_text)
                        config = json.loads(cleaned)

                    if isinstance(config, dict):
                        prov = config.get("provider")
                        if isinstance(prov, dict):
                            prov.pop("agy", None)
                        if str(config.get("model", "")).startswith("agy/"):
                            config.pop("model", None)

                        formatted_json = json.dumps(config, indent=2) + "\n"
                        atomic_write_file(target, formatted_json, mode=0o600)
                        return True
            except (json.JSONDecodeError, OSError):
                return False
        return False


def setup_opencode(
    config_path: Path | None = None,
    base_url: str | None = None,
    port: int | None = None,
    model: str = "gemini-3.8-flash-high",
    auth_token: str | None = None,
) -> ConfigPath:
    """Configures OpenCode opencode.json with agy provider and models."""
    return cast(
        ConfigPath,
        get_configurator("opencode").setup(
            base_url=base_url,
            model=model,
            config_path=config_path,
            port=port,
            auth_token=auth_token,
        ),
    )


def restore_opencode(
    config_path: Path | None = None,
    backup_path: Path | None = None,
) -> bool:
    """Restores OpenCode opencode.json from backup or surgically removes agy provider."""
    return get_configurator("opencode").restore(
        config_path=config_path,
        backup_path=backup_path,
    )
