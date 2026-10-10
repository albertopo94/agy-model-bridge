"""Configurator strategies and setup functions for Pi and Gentle Shell."""

import contextlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, cast

from bridge.setup.base import ClientConfigurator, ConfigPath, get_configurator
from bridge.setup.common import (
    _strip_json_comments,
    atomic_write_file,
    create_backup,
    create_zero_state_backup,
    get_active_api_key,
    list_backups,
    restore_backup,
)

DEFAULT_PI_AND_GENTLE_MODELS: list[dict[str, Any]] = [
    {
        "id": "gemini-3.8-flash-high",
        "name": "Gemini 3.8 Flash (High - AGY)",
        "reasoning": True,
        "input": ["text"],
        "contextWindow": 1048576,
        "maxTokens": 65536,
    },
    {
        "id": "gemini-3.8",
        "name": "Gemini 3.8 (AGY)",
        "reasoning": True,
        "input": ["text"],
        "contextWindow": 1048576,
        "maxTokens": 65536,
    },
    {
        "id": "claude-sonnet-5-5-high",
        "name": "Claude Sonnet 5.5 (High - AGY)",
        "reasoning": True,
        "input": ["text"],
        "contextWindow": 1000000,
        "maxTokens": 128000,
    },
    {
        "id": "claude-sonnet-5-5-medium",
        "name": "Claude Sonnet 5.5 (Medium - AGY)",
        "reasoning": True,
        "input": ["text"],
        "contextWindow": 1000000,
        "maxTokens": 128000,
    },
    {
        "id": "claude-sonnet-5-5-low",
        "name": "Claude Sonnet 5.5 (Low - AGY)",
        "reasoning": True,
        "input": ["text"],
        "contextWindow": 1000000,
        "maxTokens": 128000,
    },
    {
        "id": "claude-opus-5-5-high",
        "name": "Claude Opus 5.5 (High - AGY)",
        "reasoning": True,
        "input": ["text"],
        "contextWindow": 1000000,
        "maxTokens": 128000,
    },
    {
        "id": "claude-opus-5-5-medium",
        "name": "Claude Opus 5.5 (Medium - AGY)",
        "reasoning": True,
        "input": ["text"],
        "contextWindow": 1000000,
        "maxTokens": 128000,
    },
    {
        "id": "claude-opus-5-5-low",
        "name": "Claude Opus 5.5 (Low - AGY)",
        "reasoning": True,
        "input": ["text"],
        "contextWindow": 1000000,
        "maxTokens": 128000,
    },
    {
        "id": "claude-haiku-5-5-high",
        "name": "Claude Haiku 5.5 · High (AGY)",
        "reasoning": True,
        "input": ["text"],
        "contextWindow": 1000000,
        "maxTokens": 128000,
    },
    {
        "id": "claude-haiku-5-5-medium",
        "name": "Claude Haiku 5.5 · Medium (AGY)",
        "reasoning": True,
        "input": ["text"],
        "contextWindow": 1000000,
        "maxTokens": 128000,
    },
    {
        "id": "claude-haiku-5-5-low",
        "name": "Claude Haiku 5.5 · Low (AGY)",
        "reasoning": True,
        "input": ["text"],
        "contextWindow": 1000000,
        "maxTokens": 128000,
    },
    {
        "id": "gemini-2.5-pro",
        "name": "Gemini 2.5 Pro (AGY)",
        "reasoning": False,
        "input": ["text"],
        "contextWindow": 1048576,
        "maxTokens": 65536,
    },
    {
        "id": "gemini-2.5-flash",
        "name": "Gemini 2.5 Flash (AGY)",
        "reasoning": False,
        "input": ["text"],
        "contextWindow": 1048576,
        "maxTokens": 65536,
    },
]


def _cleanup_pi_or_gentle_settings(settings_path: Path) -> None:
    """Restores settings.json from backup or surgically cleans agy provider and models."""
    settings_backups = list_backups(settings_path)
    if settings_backups:
        try:
            restore_backup(settings_path, backup_path=settings_backups[0])
            settings_backups[0].unlink(missing_ok=True)
        except OSError:
            pass
    elif settings_path.exists() and settings_path.is_file():
        try:
            raw_s = settings_path.read_text(encoding="utf-8").strip()
            if raw_s:
                try:
                    s_data = json.loads(raw_s)
                except json.JSONDecodeError:
                    s_cleaned = _strip_json_comments(raw_s)
                    s_data = json.loads(s_cleaned)
                if isinstance(s_data, dict):
                    modified = False
                    agy_model_ids = {m["id"] for m in DEFAULT_PI_AND_GENTLE_MODELS} | {"gemini-3.8-flash-high", "gemini-3.8"}
                    if s_data.get("defaultProvider") == "agy":
                        s_data.pop("defaultProvider", None)
                        modified = True
                        def_model = s_data.get("defaultModel")
                        if def_model in agy_model_ids or (isinstance(def_model, str) and def_model.startswith("agy/")):
                            s_data.pop("defaultModel", None)
                            modified = True
                    if "enabledModels" in s_data and isinstance(s_data["enabledModels"], list):
                        new_models = [
                            m for m in s_data["enabledModels"]
                            if not (m in agy_model_ids or (isinstance(m, str) and m.startswith("agy/")))
                        ]
                        if len(new_models) != len(s_data["enabledModels"]):
                            s_data["enabledModels"] = new_models
                            modified = True
                    if modified:
                        atomic_write_file(settings_path, json.dumps(s_data, indent=2) + "\n", mode=0o600)
        except (json.JSONDecodeError, OSError):
            pass


class PiConfigurator(ClientConfigurator):
    """Configurator strategy for Pi Coding Agent."""

    name = "pi"
    display_name = "Pi"

    @property
    def default_config_path(self) -> Path:
        pi_dir = os.environ.get("PI_CODING_AGENT_DIR")
        if pi_dir and pi_dir.strip():
            return Path(pi_dir.strip()) / "models.json"
        return Path.home() / ".pi" / "agent" / "models.json"

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
                providers = data.get("providers")
                if isinstance(providers, dict) and "agy" in providers:
                    return True
            if ":24980" in content:
                return True
            if '"providers"' in content and '"agy"' in content:
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
        if target.exists() and target.is_file():
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
        else:
            backup_path = create_zero_state_backup(target)

        providers = config.setdefault("providers", {})
        providers["agy"] = {
            "name": "AGY Bridge",
            "baseUrl": resolved_url,
            "api": "openai-completions",
            "apiKey": auth_token,
            "headers": {"User-Agent": "pi-coding-agent"},
            "models": [dict(m) for m in DEFAULT_PI_AND_GENTLE_MODELS],
        }

        if kwargs.get("set_default"):
            settings_path = target.parent / "settings.json"
            settings_config: dict[str, Any] = {}
            if settings_path.exists() and settings_path.is_file():
                create_backup(settings_path)
                try:
                    raw_s = settings_path.read_text(encoding="utf-8").strip()
                    if raw_s:
                        try:
                            s_loaded = json.loads(raw_s)
                        except json.JSONDecodeError:
                            s_cleaned = _strip_json_comments(raw_s)
                            s_loaded = json.loads(s_cleaned)
                        if isinstance(s_loaded, dict):
                            settings_config = s_loaded
                except (json.JSONDecodeError, OSError):
                    settings_config = {}
            settings_config["defaultProvider"] = "agy"
            settings_config["defaultModel"] = model
            if "enabledModels" in settings_config and isinstance(settings_config["enabledModels"], list):
                scoped_name = f"agy/{model}"
                if scoped_name not in settings_config["enabledModels"]:
                    settings_config["enabledModels"].append(scoped_name)
            atomic_write_file(settings_path, json.dumps(settings_config, indent=2) + "\n", mode=0o600)

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
        restored = False

        chosen_backup = None
        if backup_path is not None:
            chosen_backup = Path(backup_path)
            if not chosen_backup.exists() or not chosen_backup.is_file():
                return False
        else:
            backups = self.list_backups(target)
            if backups:
                chosen_backup = backups[0]

        if chosen_backup is not None:
            is_zero_state = False
            if chosen_backup.name.endswith("-original"):
                is_zero_state = True
            else:
                try:
                    b_content = chosen_backup.read_text(encoding="utf-8")
                    if "_zero_state" in b_content:
                        is_zero_state = True
                except OSError:
                    pass

            if is_zero_state:
                if target.exists() and target.is_file():
                    target.unlink(missing_ok=True)
                chosen_backup.unlink(missing_ok=True)
                _cleanup_pi_or_gentle_settings(target.parent / "settings.json")
                return True
            else:
                try:
                    restore_backup(target, backup_path=chosen_backup)
                    restored = True
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
                        prov = config.get("providers")
                        if isinstance(prov, dict):
                            prov.pop("agy", None)

                        providers_empty = not prov
                        if providers_empty and set(config.keys()) <= {"providers"}:
                            target.unlink(missing_ok=True)
                        else:
                            formatted_json = json.dumps(config, indent=2) + "\n"
                            atomic_write_file(target, formatted_json, mode=0o600)
                        restored = True
            except (json.JSONDecodeError, OSError):
                return False

        if restored:
            _cleanup_pi_or_gentle_settings(target.parent / "settings.json")

        return restored


class GentleShellConfigurator(ClientConfigurator):
    """Configurator strategy for Gentle Shell companion."""

    name = "gentle-shell"
    display_name = "Gentle Shell"

    @property
    def default_config_path(self) -> Path:
        gs_home = os.environ.get("GENTLE_SHELL_HOME")
        if gs_home and gs_home.strip():
            return Path(gs_home.strip()) / "models.json"
        return Path.home() / ".gentle-shell" / "agent" / "models.json"

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
                providers = data.get("providers")
                if isinstance(providers, dict) and "agy" in providers:
                    return True
            if ":24980" in content:
                return True
            if '"providers"' in content and '"agy"' in content:
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
        provider = kwargs.get("provider") or "agy"

        if provider == "freellmapi":
            api_key = kwargs.get("api_key") or kwargs.get("auth_token")
            if not api_key:
                raise ValueError("API key is required when configuring FreeLLMAPI.")

            backup_path = None
            if target.exists() and target.is_file():
                backup_path = create_backup(target)
            else:
                backup_path = create_zero_state_backup(target)

            settings_path = target.parent / "settings.json"
            if settings_path.exists() and settings_path.is_file():
                create_backup(settings_path)
            else:
                create_zero_state_backup(settings_path)

            freellmapi_url = base_url or kwargs.get("freellmapi_url") or "http://127.0.0.1:31415"
            cmd = [
                "npx", "freellmapi", "setup-pi",
                "--url", freellmapi_url,
                "--api-key", api_key,
            ]
            env = os.environ.copy()
            env["PI_CODING_AGENT_DIR"] = str(target.parent)
            runner = kwargs.get("runner") or subprocess.run
            proc = runner(cmd, env=env, capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                err_msg = proc.stderr.strip() if proc.stderr else (proc.stdout.strip() if proc.stdout else "unknown error")
                raise RuntimeError(f"FreeLLMAPI setup command failed: {err_msg}")

            res = ConfigPath(target)
            res.backup_path = backup_path
            return res

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
        if target.exists() and target.is_file():
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
        else:
            backup_path = create_zero_state_backup(target)

        providers = config.setdefault("providers", {})
        providers["agy"] = {
            "name": "AGY Bridge",
            "baseUrl": resolved_url,
            "api": "openai-completions",
            "apiKey": auth_token,
            "headers": {"User-Agent": "gentle-shell"},
            "models": [dict(m) for m in DEFAULT_PI_AND_GENTLE_MODELS],
        }

        if kwargs.get("set_default"):
            settings_path = target.parent / "settings.json"
            settings_config: dict[str, Any] = {}
            if settings_path.exists() and settings_path.is_file():
                create_backup(settings_path)
                try:
                    raw_s = settings_path.read_text(encoding="utf-8").strip()
                    if raw_s:
                        try:
                            s_loaded = json.loads(raw_s)
                        except json.JSONDecodeError:
                            s_cleaned = _strip_json_comments(raw_s)
                            s_loaded = json.loads(s_cleaned)
                        if isinstance(s_loaded, dict):
                            settings_config = s_loaded
                except (json.JSONDecodeError, OSError):
                    settings_config = {}
            settings_config["defaultProvider"] = "agy"
            settings_config["defaultModel"] = model
            if "enabledModels" in settings_config and isinstance(settings_config["enabledModels"], list):
                scoped_name = f"agy/{model}"
                if scoped_name not in settings_config["enabledModels"]:
                    settings_config["enabledModels"].append(scoped_name)
            atomic_write_file(settings_path, json.dumps(settings_config, indent=2) + "\n", mode=0o600)

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
        restored = False
        provider = kwargs.get("provider")

        # Auto-detect provider if not explicitly specified
        if not provider and target.exists() and target.is_file():
            with contextlib.suppress(Exception):
                raw_text = target.read_text(encoding="utf-8").strip()
                if raw_text:
                    config = json.loads(_strip_json_comments(raw_text))
                    if isinstance(config, dict):
                        prov = config.get("providers", {})
                        if isinstance(prov, dict):
                            if ("freellmapi" in prov or any(k.startswith("freellmapi-") for k in prov)) and "agy" not in prov:
                                provider = "freellmapi"
                            elif "agy" in prov:
                                provider = "agy"
        if not provider:
            provider = "agy"

        if provider == "freellmapi":
            if not target.exists() or not target.is_file():
                return False
            try:
                raw_text = target.read_text(encoding="utf-8").strip()
                if raw_text:
                    try:
                        config = json.loads(raw_text)
                    except json.JSONDecodeError:
                        cleaned = _strip_json_comments(raw_text)
                        config = json.loads(cleaned)

                    if isinstance(config, dict):
                        prov = config.get("providers")
                        if isinstance(prov, dict):
                            keys_to_remove = [k for k in prov if k == "freellmapi" or k.startswith("freellmapi-")]
                            for k in keys_to_remove:
                                prov.pop(k, None)

                        providers_empty = not prov
                        if providers_empty and set(config.keys()) <= {"providers"}:
                            target.unlink(missing_ok=True)
                        else:
                            formatted_json = json.dumps(config, indent=2) + "\n"
                            atomic_write_file(target, formatted_json, mode=0o600)
                        restored = True
            except (json.JSONDecodeError, OSError):
                return False

            if restored:
                settings_path = target.parent / "settings.json"
                settings_backups = list_backups(settings_path)
                if settings_backups:
                    try:
                        restore_backup(settings_path, backup_path=settings_backups[0])
                        settings_backups[0].unlink(missing_ok=True)
                    except OSError:
                        pass
                elif settings_path.exists() and settings_path.is_file():
                    with contextlib.suppress(Exception):
                        raw_s = settings_path.read_text(encoding="utf-8").strip()
                        if raw_s:
                            s_data = json.loads(_strip_json_comments(raw_s))
                            if isinstance(s_data, dict):
                                def_p = s_data.get("defaultProvider")
                                if def_p and (def_p == "freellmapi" or def_p.startswith("freellmapi-")):
                                    has_agy = False
                                    if target.exists():
                                        with contextlib.suppress(Exception):
                                            m_data = json.loads(target.read_text(encoding="utf-8"))
                                            has_agy = "agy" in m_data.get("providers", {})
                                    if has_agy:
                                        s_data["defaultProvider"] = "agy"
                                    else:
                                        s_data.pop("defaultProvider", None)

                                if str(s_data.get("defaultModel", "")).startswith("freellmapi/") or s_data.get("defaultModel") == "auto":
                                    s_data.pop("defaultModel", None)

                                if "enabledModels" in s_data and isinstance(s_data["enabledModels"], list):
                                    s_data["enabledModels"] = [
                                        m for m in s_data["enabledModels"]
                                        if not (str(m).startswith("freellmapi/") or m == "auto")
                                    ]
                                atomic_write_file(settings_path, json.dumps(s_data, indent=2) + "\n", mode=0o600)
            return restored

        chosen_backup = None
        if backup_path is not None:
            chosen_backup = Path(backup_path)
            if not chosen_backup.exists() or not chosen_backup.is_file():
                return False
        else:
            backups = self.list_backups(target)
            if backups:
                chosen_backup = backups[0]

        if chosen_backup is not None:
            is_zero_state = False
            if chosen_backup.name.endswith("-original"):
                is_zero_state = True
            else:
                try:
                    b_content = chosen_backup.read_text(encoding="utf-8")
                    if "_zero_state" in b_content:
                        is_zero_state = True
                except OSError:
                    pass

            if is_zero_state:
                if target.exists() and target.is_file():
                    target.unlink(missing_ok=True)
                chosen_backup.unlink(missing_ok=True)
                _cleanup_pi_or_gentle_settings(target.parent / "settings.json")
                return True
            else:
                try:
                    restore_backup(target, backup_path=chosen_backup)
                    restored = True
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
                        prov = config.get("providers")
                        if isinstance(prov, dict):
                            prov.pop("agy", None)

                        providers_empty = not prov
                        if providers_empty and set(config.keys()) <= {"providers"}:
                            target.unlink(missing_ok=True)
                        else:
                            formatted_json = json.dumps(config, indent=2) + "\n"
                            atomic_write_file(target, formatted_json, mode=0o600)
                        restored = True
            except (json.JSONDecodeError, OSError):
                return False

        if restored:
            _cleanup_pi_or_gentle_settings(target.parent / "settings.json")

        return restored


def setup_pi(
    config_path: Path | None = None,
    base_url: str | None = None,
    port: int | None = None,
    model: str = "gemini-3.8-flash-high",
    auth_token: str | None = None,
    set_default: bool = False,
) -> ConfigPath:
    """Configures Pi models.json for agy-model-bridge gateway."""
    return cast(
        ConfigPath,
        get_configurator("pi").setup(
            base_url=base_url,
            model=model,
            config_path=config_path,
            port=port,
            auth_token=auth_token,
            set_default=set_default,
        ),
    )


def restore_pi(
    config_path: Path | None = None,
    backup_path: Path | None = None,
) -> bool:
    """Restores Pi models.json from backup or surgically removes agy provider."""
    return get_configurator("pi").restore(
        config_path=config_path,
        backup_path=backup_path,
    )


def setup_gentle_shell(
    config_path: Path | None = None,
    base_url: str | None = None,
    port: int | None = None,
    model: str = "gemini-3.8-flash-high",
    auth_token: str | None = None,
    set_default: bool = False,
    provider: str = "agy",
    api_key: str | None = None,
) -> ConfigPath:
    """Configures Gentle Shell models.json for agy-model-bridge gateway or FreeLLMAPI."""
    return cast(
        ConfigPath,
        get_configurator("gentle-shell").setup(
            base_url=base_url,
            model=model,
            config_path=config_path,
            port=port,
            auth_token=auth_token,
            set_default=set_default,
            provider=provider,
            api_key=api_key,
        ),
    )


def restore_gentle_shell(
    config_path: Path | None = None,
    backup_path: Path | None = None,
    provider: str | None = None,
) -> bool:
    """Restores Gentle Shell models.json from backup or surgically removes agy/freellmapi provider."""
    return get_configurator("gentle-shell").restore(
        config_path=config_path,
        backup_path=backup_path,
        provider=provider,
    )

