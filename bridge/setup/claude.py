"""Configurator strategy and setup functions for Claude Code."""

import json
from pathlib import Path
from typing import Any, cast

from bridge.setup.base import ClientConfigurator, ConfigPath, get_configurator
from bridge.setup.common import (
    atomic_write_file,
    create_backup,
    get_active_api_key,
    restore_backup,
)

DEFAULT_CLAUDE_MODEL_PICKER_OPTIONS: list[dict[str, str]] = [
    {
        "model": "gemini-3.8-flash-high",
        "label": "Gemini 3.8 Flash · High (AGY)",
        "behavesAs": "claude-3-7-sonnet",
    },
    {
        "model": "gemini-3.7-flash-tiered",
        "label": "Gemini 3.7 Flash · High (AGY)",
        "behavesAs": "claude-3-7-sonnet",
    },
    {
        "model": "claude-sonnet-5-5-high",
        "label": "Claude Sonnet 5.5 · High (AGY)",
        "behavesAs": "claude-3-7-sonnet",
    },
    {
        "model": "claude-sonnet-5-5-medium",
        "label": "Claude Sonnet 5.5 · Medium (AGY)",
        "behavesAs": "claude-3-7-sonnet",
    },
    {
        "model": "claude-sonnet-5-5-low",
        "label": "Claude Sonnet 5.5 · Low (AGY)",
        "behavesAs": "claude-3-7-sonnet",
    },
    {
        "model": "claude-opus-5-5-high",
        "label": "Claude Opus 5.5 · High (AGY)",
        "behavesAs": "claude-3-7-sonnet",
    },
    {
        "model": "claude-opus-5-5-medium",
        "label": "Claude Opus 5.5 · Medium (AGY)",
        "behavesAs": "claude-3-7-sonnet",
    },
    {
        "model": "claude-opus-5-5-low",
        "label": "Claude Opus 5.5 · Low (AGY)",
        "behavesAs": "claude-3-7-sonnet",
    },
    {
        "model": "gemini-2.5-pro",
        "label": "Gemini 2.5 Pro (AGY)",
        "behavesAs": "claude-3-7-sonnet",
    },
    {
        "model": "gemini-2.5-flash",
        "label": "Gemini 2.5 Flash (AGY)",
        "behavesAs": "claude-3-7-sonnet",
    },
]


class ClaudeConfigurator(ClientConfigurator):
    """Configurator strategy for Claude Code CLI."""

    name = "claude"
    display_name = "Claude Code"

    @property
    def default_config_path(self) -> Path:
        return Path.home() / ".claude" / "settings.json"

    def is_configured(self, config_path: Path | None = None) -> bool:
        target = self.get_config_path(config_path)
        if not target.exists() or not target.is_file():
            return False
        try:
            content = target.read_text(encoding="utf-8").strip()
            if not content:
                return False
            data = json.loads(content)
            if not isinstance(data, dict):
                return False
            env = data.get("env")
            if isinstance(env, dict):
                base_url = str(env.get("ANTHROPIC_BASE_URL", "")).lower()
                auth_token = str(env.get("ANTHROPIC_AUTH_TOKEN", "")).lower()
                model = str(env.get("ANTHROPIC_MODEL", "")).lower()
                if "24980" in base_url or auth_token == "antigravity" or "gemini" in model:
                    return True
                agy_env_keys = (
                    "ANTHROPIC_BASE_URL",
                    "ANTHROPIC_AUTH_TOKEN",
                    "ANTHROPIC_MODEL",
                    "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
                    "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY",
                )
                if any(k in env for k in agy_env_keys):
                    return True
                if any(k.startswith("ANTHROPIC_DEFAULT_") and k.endswith("_MODEL") for k in env):
                    return True
            picker = data.get("modelPicker")
            if isinstance(picker, dict):
                options = picker.get("options", [])
                if isinstance(options, list):
                    for opt in options:
                        if isinstance(opt, dict) and "gemini" in opt.get("model", ""):
                            return True
            return False
        except (json.JSONDecodeError, OSError):
            return False

    def setup(
        self,
        base_url: str | None = None,
        model: str = "gemini-3.8-flash-high",
        config_path: Path | None = None,
        **kwargs: Any,
    ) -> Path:
        target = self.get_config_path(config_path or kwargs.get("settings_path"))
        port = kwargs.get("port")
        auth_token = kwargs.get("auth_token") or get_active_api_key()

        if base_url:
            resolved_url = base_url.rstrip("/")
        elif port is not None:
            resolved_url = f"http://127.0.0.1:{port}"
        else:
            resolved_url = "http://127.0.0.1:24980"

        backup_path = None
        settings: dict[str, Any] = {}
        if target.exists():
            backup_path = create_backup(target)
            try:
                with open(target, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        loaded = json.loads(content)
                        if isinstance(loaded, dict):
                            settings = loaded
            except (json.JSONDecodeError, OSError):
                settings = {}

        env_dict = settings.get("env")
        if not isinstance(env_dict, dict):
            env_dict = {}
            settings["env"] = env_dict

        env_dict["ANTHROPIC_BASE_URL"] = resolved_url
        env_dict["ANTHROPIC_AUTH_TOKEN"] = auth_token
        env_dict["ANTHROPIC_MODEL"] = model
        env_dict["ANTHROPIC_DEFAULT_SONNET_MODEL"] = model
        env_dict["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = model
        env_dict["ANTHROPIC_DEFAULT_OPUS_MODEL"] = model
        env_dict["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "1048576"
        env_dict["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] = "1"

        model_options = [dict(opt) for opt in DEFAULT_CLAUDE_MODEL_PICKER_OPTIONS]
        if not any(opt.get("model") == model for opt in model_options):
            model_options.insert(
                0,
                {
                    "model": model,
                    "label": f"Custom ({model})",
                    "behavesAs": "claude-3-7-sonnet",
                },
            )

        settings["modelPicker"] = {
            "options": model_options,
            "replaceBuiltInOptions": False,
        }

        formatted_json = json.dumps(settings, indent=2) + "\n"
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
        target = self.get_config_path(config_path or kwargs.get("settings_path"))
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
                content = target.read_text(encoding="utf-8").strip()
                if content:
                    settings = json.loads(content)
                    if isinstance(settings, dict):
                        env = settings.get("env")
                        if isinstance(env, dict):
                            keys_to_clean = [
                                k
                                for k in env
                                if k
                                in (
                                    "ANTHROPIC_BASE_URL",
                                    "ANTHROPIC_AUTH_TOKEN",
                                    "ANTHROPIC_MODEL",
                                    "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
                                    "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY",
                                )
                                or (k.startswith("ANTHROPIC_DEFAULT_") and k.endswith("_MODEL"))
                            ]
                            for k in keys_to_clean:
                                del env[k]

                        model_picker = settings.get("modelPicker")
                        if isinstance(model_picker, dict):
                            agy_models = {
                                "gemini-3.8-flash-high",
                                "gemini-3.7-flash-tiered",
                                "gemini-3.6-flash-tiered",
                                "claude-sonnet-4-6",
                                "claude-opus-4-6-thinking",
                                "claude-sonnet-5-5-high",
                                "claude-sonnet-5-5-medium",
                                "claude-sonnet-5-5-low",
                                "claude-opus-5-5-high",
                                "claude-opus-5-5-medium",
                                "claude-opus-5-5-low",
                                "gemini-2.5-pro",
                                "gemini-2.5-flash",
                            }
                            options = model_picker.get("options", [])
                            if isinstance(options, list):
                                remaining_opts = [
                                    opt
                                    for opt in options
                                    if isinstance(opt, dict)
                                    and opt.get("model") not in agy_models
                                    and not opt.get("label", "").startswith("Custom (")
                                ]
                                if remaining_opts:
                                    settings["modelPicker"]["options"] = remaining_opts
                                else:
                                    settings.pop("modelPicker", None)
                            else:
                                settings.pop("modelPicker", None)

                        formatted_json = json.dumps(settings, indent=2) + "\n"
                        atomic_write_file(target, formatted_json, mode=0o600)
                        return True
            except (json.JSONDecodeError, OSError):
                return False
        return False


def setup_claude(
    settings_path: Path | None = None,
    base_url: str | None = None,
    port: int | None = None,
    model: str = "gemini-3.8-flash-high",
    auth_token: str | None = None,
) -> ConfigPath:
    """Configures Claude Code settings.json with agy-model-bridge environment variables."""
    return cast(
        ConfigPath,
        get_configurator("claude").setup(
            base_url=base_url,
            model=model,
            config_path=settings_path,
            port=port,
            auth_token=auth_token,
        ),
    )


def restore_claude(
    settings_path: Path | None = None,
    backup_path: Path | None = None,
) -> bool:
    """Restores Claude Code settings.json from backup or surgically cleans bridge keys."""
    return get_configurator("claude").restore(
        config_path=settings_path,
        backup_path=backup_path,
    )
