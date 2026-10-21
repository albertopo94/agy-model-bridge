"""Configurator strategy and setup functions for OpenClaw."""

import json
import os
from pathlib import Path
from typing import Any, cast

from bridge.setup.availability import split_by_availability
from bridge.setup.base import ClientConfigurator, ConfigPath, get_configurator
from bridge.setup.common import (
    _strip_json_comments,
    atomic_write_file,
    create_backup,
    get_active_api_key,
    restore_backup,
)


DEFAULT_CURSOR_OPENCLAW_MODELS: list[dict[str, Any]] = [
    {
        "id": "cursor/auto",
        "name": "Auto [Cursor - Free]",
        "reasoning": False,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 200000,
        "maxTokens": 32000,
    },
    {
        "id": "cursor/gpt-5.3-codex",
        "name": "Codex 5.3 [Cursor - Pro]",
        "reasoning": True,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 200000,
        "maxTokens": 32000,
    },
    {
        "id": "cursor/composer-2.5",
        "name": "Composer 2.5 [Cursor - Pro]",
        "reasoning": False,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 200000,
        "maxTokens": 32000,
    },
    {
        "id": "cursor/claude-opus-5-5-high",
        "name": "Claude Opus 5.5 High [Cursor - Pro]",
        "reasoning": True,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 1000000,
        "maxTokens": 64000,
    },
    {
        "id": "cursor/claude-sonnet-5-5-high",
        "name": "Claude Sonnet 5.5 High [Cursor - Pro]",
        "reasoning": True,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 1000000,
        "maxTokens": 64000,
    },
    {
        "id": "cursor/grok-4.7-high",
        "name": "Grok 4.7 High [Cursor - Pro]",
        "reasoning": True,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 256000,
        "maxTokens": 32000,
    },
]


DEFAULT_AGY_OPENCLAW_MODELS: list[dict[str, Any]] = [
                {
                    "id": "gemini-3.8-flash-high",
                    "name": "Gemini 3.8 Flash (High)",
                    "reasoning": True,
                    "input": ["text"],
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    "contextWindow": 1048576,
                    "maxTokens": 65536,
                },
                {
                    "id": "claude-sonnet-5-5-high",
                    "name": "Claude Sonnet 5.5 (High - AGY)",
                    "reasoning": True,
                    "input": ["text"],
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    "contextWindow": 1000000,
                    "maxTokens": 128000,
                },
                {
                    "id": "claude-sonnet-5-5-medium",
                    "name": "Claude Sonnet 5.5 (Medium - AGY)",
                    "reasoning": True,
                    "input": ["text"],
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    "contextWindow": 1000000,
                    "maxTokens": 128000,
                },
                {
                    "id": "claude-sonnet-5-5-low",
                    "name": "Claude Sonnet 5.5 (Low - AGY)",
                    "reasoning": True,
                    "input": ["text"],
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    "contextWindow": 1000000,
                    "maxTokens": 128000,
                },
                {
                    "id": "claude-opus-5-5-high",
                    "name": "Claude Opus 5.5 (High - AGY)",
                    "reasoning": True,
                    "input": ["text"],
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    "contextWindow": 1000000,
                    "maxTokens": 128000,
                },
                {
                    "id": "claude-opus-5-5-medium",
                    "name": "Claude Opus 5.5 (Medium - AGY)",
                    "reasoning": True,
                    "input": ["text"],
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    "contextWindow": 1000000,
                    "maxTokens": 128000,
                },
                {
                    "id": "claude-opus-5-5-low",
                    "name": "Claude Opus 5.5 (Low - AGY)",
                    "reasoning": True,
                    "input": ["text"],
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    "contextWindow": 1000000,
                    "maxTokens": 128000,
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


class OpenClawConfigurator(ClientConfigurator):
    """Configurator strategy for OpenClaw."""

    name = "openclaw"
    display_name = "OpenClaw"

    @property
    def default_config_path(self) -> Path:
        cfg_path = os.environ.get("OPENCLAW_CONFIG_PATH")
        if cfg_path and cfg_path.strip():
            return Path(cfg_path.strip())
        state_dir = os.environ.get("OPENCLAW_STATE_DIR")
        if state_dir and state_dir.strip():
            return Path(state_dir.strip()) / "openclaw.json"
        claw_home = os.environ.get("OPENCLAW_HOME")
        if claw_home and claw_home.strip():
            return Path(claw_home.strip()) / ".openclaw" / "openclaw.json"
        return Path.home() / ".openclaw" / "openclaw.json"

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
                models_sec = data.get("models")
                if isinstance(models_sec, dict):
                    providers = models_sec.get("providers")
                    if isinstance(providers, dict) and "agy" in providers:
                        return True
                agents_sec = data.get("agents")
                if isinstance(agents_sec, dict):
                    defaults = agents_sec.get("defaults")
                    if isinstance(defaults, dict):
                        model = defaults.get("model")
                        if isinstance(model, dict):
                            primary = str(model.get("primary", ""))
                            if primary.startswith("agy/"):
                                return True
            if ":24980" in content:
                return True
            if '"providers"' in content and '"agy"' in content:
                return True
            if '"primary"' in content and "agy/" in content:
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

        agents = config.setdefault("agents", {})
        defaults = agents.setdefault("defaults", {})
        model_dict = defaults.setdefault("model", {})
        model_dict["primary"] = f"agy/{model}"

        models_dict = config.setdefault("models", {})
        providers = models_dict.setdefault("providers", {})
        provider = str(kwargs.get("provider") or "agy").lower()

        if provider in ("cursor", "all", "todos"):
            providers["cursor"] = {
                "baseUrl": resolved_url,
                "apiKey": auth_token,
                "api": "openai-completions",
                "headers": {"User-Agent": "openclaw"},
                "models": [dict(m) for m in DEFAULT_CURSOR_OPENCLAW_MODELS],
            }

        agy_models: list[dict[str, Any]] = []
        agy_skipped: list[str] = []
        if provider in ("agy", "all", "todos"):
            agy_kept, agy_skipped = split_by_availability(
                [(m["id"], dict(m)) for m in DEFAULT_AGY_OPENCLAW_MODELS],
                kwargs.get("available_models"),
            )
            agy_models = [model for _, model in agy_kept]
            providers["agy"] = {
                "baseUrl": resolved_url,
                "apiKey": auth_token,
                "api": "openai-completions",
                "headers": {"User-Agent": "openclaw"},
                "models": agy_models
        }

        formatted_json = json.dumps(config, indent=2) + "\n"
        atomic_write_file(target, formatted_json, mode=0o600)
        res = ConfigPath(target)
        res.backup_path = backup_path
        res.availability_verified = kwargs.get("available_models") is not None
        res.skipped_models = agy_skipped
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
                        models_dict = config.get("models")
                        provider = kwargs.get("provider")
                        if isinstance(models_dict, dict):
                            prov = models_dict.get("providers")
                            if isinstance(prov, dict):
                                if provider == "cursor":
                                    prov.pop("cursor", None)
                                elif provider in ("all", "todos"):
                                    prov.pop("agy", None)
                                    prov.pop("cursor", None)
                                else:
                                    prov.pop("agy", None)
                        agents = config.get("agents")
                        if isinstance(agents, dict):
                            defaults = agents.get("defaults")
                            if isinstance(defaults, dict):
                                model_dict = defaults.get("model")
                                if isinstance(model_dict, dict):
                                    prim = str(model_dict.get("primary", ""))
                                    if prim.startswith("agy/") or prim.startswith("cursor/"):
                                        model_dict.pop("primary", None)

                        formatted_json = json.dumps(config, indent=2) + "\n"
                        atomic_write_file(target, formatted_json, mode=0o600)
                        return True
            except (json.JSONDecodeError, OSError):
                return False
        return False


def setup_openclaw(
    config_path: Path | None = None,
    base_url: str | None = None,
    port: int | None = None,
    model: str = "gemini-3.8-flash-high",
    auth_token: str | None = None,
    provider: str = "agy",
    available_models: set[str] | None = None,
) -> ConfigPath:
    """Configures OpenClaw openclaw.json with agy provider and models."""
    return cast(
        ConfigPath,
        get_configurator("openclaw").setup(
            base_url=base_url,
            model=model,
            config_path=config_path,
            port=port,
            auth_token=auth_token,
            provider=provider,
            available_models=available_models,
        ),
    )


def restore_openclaw(
    config_path: Path | None = None,
    backup_path: Path | None = None,
    provider: str | None = None,
) -> bool:
    """Restores OpenClaw openclaw.json from backup or surgically removes agy/cursor provider."""
    return get_configurator("openclaw").restore(
        config_path=config_path,
        backup_path=backup_path,
        provider=provider,
    )
