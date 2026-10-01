"""Client setup and configuration file utilities for agy-model-bridge.

Provides atomic file replacement and ISO-8601 timestamped backups for Claude Code
and Codex CLI configuration files.
Zero external dependencies: pure Python standard library.
"""

from abc import ABC, abstractmethod
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any
import uuid

from bridge import __version__
import bridge.daemon
from bridge.i18n import t


def atomic_write_file(path: Path, content: str, mode: int = 0o600) -> None:
    """Atomically writes content to path using a tempfile and os.replace.

    Ensures parent directories exist with 0o700 permissions, fsyncs data to disk,
    sets file mode to 0o600 (or specified mode), and atomically renames.

    Args:
        path: Target file Path.
        content: String content to write (UTF-8).
        mode: Octal file permissions (default 0o600).
    """
    path = Path(path)
    parent = path.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
        os.chmod(parent, 0o700)

    tmp_path = parent / f"{path.name}.tmp.{uuid.uuid4().hex}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def create_backup(path: Path) -> Path | None:
    """Creates a timestamped backup of path if it exists.

    Backup filename pattern: <path>.backup-YYYY-MM-DDTHH-MM-SS

    Args:
        path: Path to file to backup.

    Returns:
        Path of created backup file, or None if source file does not exist.
    """
    path = Path(path)
    if not path.exists() or not path.is_file():
        return None

    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    backup_path = path.with_name(f"{path.name}.backup-{timestamp}")
    shutil.copy2(path, backup_path)
    return backup_path


def list_backups(config_path: Path) -> list[Path]:
    """Lists all historical backup files for config_path sorted by mtime descending.

    Discovers both agy-model-bridge (.backup-YYYY-MM-DDTHH-MM-SS) and FreeLLMAPI
    (.backup-YYYY-MM-DDTHH-MM-SS-mmmZ) backups.

    Args:
        config_path: Path to the target configuration file.

    Returns:
        List of Path objects sorted with most recent backup first.
    """
    path = Path(config_path)
    parent = path.parent
    if not parent.exists() or not parent.is_dir():
        return []

    pattern = f"{path.name}.backup-*"
    backups = [p for p in parent.glob(pattern) if p.is_file()]
    backups.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return backups


def describe_backup(backup_path: Path) -> str:
    """Identifies the provenance/origin of a configuration backup file.

    Inspects content and naming patterns to classify backups as:
    - "AGY Bridge": Antigravity Model Bridge configuration
    - "FreeLLMAPI": FreeLLMAPI configuration
    - "Anthropic Original": Original un-proxied Claude Code configuration
    - "Codex Original": Original un-proxied Codex CLI configuration
    - "Personalizado": Other custom proxy/endpoint configuration
    - "Desconocido": Unreadable or empty file

    Args:
        backup_path: Path to the backup file to inspect.

    Returns:
        Provenance string tag.
    """
    path = Path(backup_path)
    if not path.exists() or not path.is_file():
        return "Desconocido"

    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return "Desconocido"

    if not content.strip():
        return "Desconocido"

    # Claude Code JSON settings inspection
    if "settings.json" in path.name or content.lstrip().startswith("{"):
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                env = data.get("env")
                if not isinstance(env, dict):
                    env = {}
                base_url = str(env.get("ANTHROPIC_BASE_URL", "")).lower()
                auth_token = str(env.get("ANTHROPIC_AUTH_TOKEN", "")).lower()
                model = str(env.get("ANTHROPIC_MODEL", "")).lower()

                if "24980" in base_url or auth_token == "antigravity" or "gemini-3.8-flash-high" in model:
                    return "AGY Bridge"
                if "31415" in base_url or "freellmapi" in auth_token or "freellmapi" in base_url:
                    return "FreeLLMAPI"
                if not base_url or "anthropic.com" in base_url:
                    return "Anthropic Original"
                return "Personalizado"
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    # Codex TOML config inspection
    if "# agy:start" in content or "[model_providers.agy]" in content or 'model_provider = "agy"' in content or ":24980" in content:
        return "AGY Bridge"
    if "# freellmapi:start" in content or "[model_providers.freellmapi]" in content or 'model_provider = "freellmapi"' in content or ":31415" in content or "freellmapi" in content.lower():
        return "FreeLLMAPI"
    if "config.toml" in path.name or "[projects" in content or "model = " in content or "personality" in content:
        return "Codex Original"

    return "Desconocido"


def restore_backup(config_path: Path, backup_path: Path | None = None) -> Path:
    """Restores config_path from a backup file without creating redundant backups.

    Args:
        config_path: Target configuration file to overwrite.
        backup_path: Specific backup Path to restore. If None, restores the most
            recent backup found by list_backups(config_path).

    Returns:
        Path of the restored backup file.

    Raises:
        FileNotFoundError: If no backup exists or specified backup is missing.
    """
    target = Path(config_path)
    if backup_path is None:
        backups = list_backups(target)
        if not backups:
            raise FileNotFoundError(f"No backups found for {target}")
        chosen_backup = backups[0]
    else:
        chosen_backup = Path(backup_path)
        if not chosen_backup.exists() or not chosen_backup.is_file():
            raise FileNotFoundError(f"Backup file not found: {chosen_backup}")

    content = chosen_backup.read_text(encoding="utf-8")
    atomic_write_file(target, content, mode=0o600)
    return chosen_backup


class ConfigPath(type(Path())):
    """Path subclass that carries an optional backup_path attribute."""
    backup_path: Path | None = None


DEFAULT_CLAUDE_MODEL_PICKER_OPTIONS: list[dict[str, str]] = [
    {
        "model": "gemini-3.8-flash-high",
        "label": "Gemini 3.8 Flash · high (1M)",
        "behavesAs": "claude-3-7-sonnet",
    },
    {
        "model": "gemini-3.7-flash-tiered",
        "label": "Gemini 3.7 Flash",
        "behavesAs": "claude-3-7-sonnet",
    },
    {
        "model": "gemini-3.6-flash-tiered",
        "label": "Gemini 3.6 Flash",
        "behavesAs": "claude-3-7-sonnet",
    },
    {
        "model": "claude-sonnet-4-6",
        "label": "Claude Sonnet 4.6 (Cloud Code)",
        "behavesAs": "claude-3-7-sonnet",
    },
    {
        "model": "claude-opus-4-6-thinking",
        "label": "Claude Opus 4.6 Thinking (Cloud Code)",
        "behavesAs": "claude-3-7-sonnet",
    },
]


class ClientConfigurator(ABC):
    """Abstract base class (Strategy) for client configuration management."""

    name: str = ""
    display_name: str = ""

    @property
    @abstractmethod
    def default_config_path(self) -> Path:
        """Default filesystem path for this client's configuration file."""
        pass

    def get_config_path(self, custom_path: Path | None = None) -> Path:
        """Returns custom_path if provided, else default_config_path."""
        if custom_path is not None:
            return Path(custom_path)
        return self.default_config_path

    @abstractmethod
    def is_configured(self, config_path: Path | None = None) -> bool:
        """Returns True if AGY configuration settings or blocks are present in the target config."""
        pass

    @abstractmethod
    def setup(
        self,
        base_url: str | None = None,
        model: str = "gemini-3.8-flash-high",
        config_path: Path | None = None,
        **kwargs: Any,
    ) -> Path:
        """Configures the client file to point to AGY model bridge."""
        pass

    @abstractmethod
    def restore(
        self,
        config_path: Path | None = None,
        backup_path: Path | None = None,
        **kwargs: Any,
    ) -> bool:
        """Restores the client configuration from a backup or performs surgical removal."""
        pass

    def list_backups(self, config_path: Path | None = None) -> list[Path]:
        """Lists historical backup files for this client, sorted by mtime descending."""
        target = self.get_config_path(config_path)
        return list_backups(target)

    def purge_backups(self, config_path: Path | None = None) -> int:
        """Deletes all historical backup files for this client. Returns number of purged files."""
        target = self.get_config_path(config_path)
        purged = 0
        for b in self.list_backups(target):
            try:
                b.unlink()
                purged += 1
            except OSError:
                pass
        return purged


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
        auth_token = kwargs.get("auth_token", "antigravity")

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


CODEX_BLOCK_REGEX = re.compile(
    r"^[ \t]*# agy:start[\s\S]*?^[ \t]*# agy:end[ \t]*(?:\r?\n)?",
    re.MULTILINE,
)

CODEX_ROOT_CONFLICT_REGEX = re.compile(
    r"^[ \t]*(model|model_provider|model_context_window|model_auto_compact_token_limit)[ \t]*=.*$",
    re.MULTILINE,
)


def build_codex_block(model: str, base_url: str) -> str:
    """Constructs the delimited agy configuration block for Codex config.toml."""
    return (
        "# agy:start\n"
        f'model = "{model}"\n'
        'model_provider = "agy"\n'
        "model_context_window = 1048576\n"
        "model_auto_compact_token_limit = 943718\n\n"
        "[model_providers.agy]\n"
        'name = "agy"\n'
        f'base_url = "{base_url}"\n'
        'wire_api = "responses"\n'
        "requires_openai_auth = false\n"
        "# agy:end"
    )


class CodexConfigurator(ClientConfigurator):
    """Configurator strategy for Codex CLI."""

    name = "codex"
    display_name = "Codex CLI"

    @property
    def default_config_path(self) -> Path:
        return Path.home() / ".codex" / "config.toml"

    def is_configured(self, config_path: Path | None = None) -> bool:
        target = self.get_config_path(config_path)
        if not target.exists() or not target.is_file():
            return False
        try:
            content = target.read_text(encoding="utf-8")
            if (
                CODEX_BLOCK_REGEX.search(content)
                or "# agy:start" in content
                or "[model_providers.agy]" in content
                or 'model_provider = "agy"' in content
                or ":24980" in content
            ):
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

        if base_url:
            resolved_url = base_url.rstrip("/")
        elif port is not None:
            resolved_url = f"http://127.0.0.1:{port}/v1"
        else:
            resolved_url = "http://127.0.0.1:24980/v1"

        block = build_codex_block(model=model, base_url=resolved_url)

        backup_path = None
        if target.exists():
            backup_path = create_backup(target)
            existing_content = target.read_text(encoding="utf-8")
            if CODEX_BLOCK_REGEX.search(existing_content):
                existing_content = CODEX_BLOCK_REGEX.sub("", existing_content)

            table_match = re.search(r"^[ \t]*\[", existing_content, re.MULTILINE)
            if table_match:
                prefix = existing_content[:table_match.start()]
                suffix = existing_content[table_match.start():]
                cleaned_prefix = CODEX_ROOT_CONFLICT_REGEX.sub(r"# \g<0>  # agy-override", prefix)
                if cleaned_prefix.strip():
                    new_content = cleaned_prefix.rstrip() + "\n\n" + block + "\n\n" + suffix.lstrip()
                else:
                    new_content = block + "\n\n" + suffix.lstrip()
            elif existing_content.strip():
                cleaned_prefix = CODEX_ROOT_CONFLICT_REGEX.sub(r"# \g<0>  # agy-override", existing_content)
                if cleaned_prefix.strip():
                    new_content = cleaned_prefix.rstrip() + "\n\n" + block + "\n"
                else:
                    new_content = block + "\n"
            else:
                new_content = block + "\n"
        else:
            new_content = block + "\n"

        atomic_write_file(target, new_content, mode=0o600)
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
                content = target.read_text(encoding="utf-8")
                if CODEX_BLOCK_REGEX.search(content):
                    cleaned = CODEX_BLOCK_REGEX.sub("", content).strip()
                    cleaned = re.sub(
                        r"^[ \t]*#[ \t]*(.*?)[ \t]*#[ \t]*agy-override\s*$",
                        r"\1",
                        cleaned,
                        flags=re.MULTILINE,
                    )
                    if cleaned:
                        cleaned += "\n"
                    atomic_write_file(target, cleaned, mode=0o600)
                    return True
            except OSError:
                return False
        return False


CLIENT_CONFIGURATORS: dict[str, ClientConfigurator] = {
    "claude": ClaudeConfigurator(),
    "codex": CodexConfigurator(),
}


def register_configurator(configurator: ClientConfigurator) -> None:
    """Registers a client configurator into the global registry."""
    CLIENT_CONFIGURATORS[configurator.name] = configurator


def get_configurator(name: str) -> ClientConfigurator:
    """Retrieves a client configurator by name from the registry."""
    if name not in CLIENT_CONFIGURATORS:
        raise KeyError(f"Unknown client configurator: '{name}'")
    return CLIENT_CONFIGURATORS[name]


def list_configurators() -> list[ClientConfigurator]:
    """Returns a list of all registered client configurators."""
    return list(CLIENT_CONFIGURATORS.values())


def setup_claude(
    settings_path: Path | None = None,
    base_url: str | None = None,
    port: int | None = None,
    model: str = "gemini-3.8-flash-high",
    auth_token: str = "antigravity",
) -> Path:
    """Configures Claude Code settings.json with agy-model-bridge environment variables."""
    return get_configurator("claude").setup(
        base_url=base_url,
        model=model,
        config_path=settings_path,
        port=port,
        auth_token=auth_token,
    )


def setup_codex(
    config_path: Path | None = None,
    base_url: str | None = None,
    port: int | None = None,
    model: str = "gemini-3.8-flash-high",
) -> Path:
    """Configures Codex CLI config.toml with delimited agy configuration block."""
    return get_configurator("codex").setup(
        base_url=base_url,
        model=model,
        config_path=config_path,
        port=port,
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


def restore_codex(
    config_path: Path | None = None,
    backup_path: Path | None = None,
) -> bool:
    """Restores Codex CLI config.toml from backup or surgically removes agy block."""
    return get_configurator("codex").restore(
        config_path=config_path,
        backup_path=backup_path,
    )


def uninstall(
    daemon_dir: Path | None = None,
    bin_dir: Path | None = None,
    configurators: list[ClientConfigurator] | None = None,
    custom_config_paths: dict[str, Path] | None = None,
    restore_configs: bool = True,
    purge_backups: bool = False,
    claude_settings_path: Path | None = None,
    codex_config_path: Path | None = None,
) -> dict[str, Any]:
    """Uninstalls Antigravity Model Bridge and optionally restores client configurations.

    Args:
        daemon_dir: Path to daemon directory (default: ~/.agy-bridge).
        bin_dir: Path to launcher binary directory (default: ~/.local/bin).
        configurators: Optional list of ClientConfigurators to handle (defaults to all registered).
        custom_config_paths: Optional mapping of client name to custom config Path.
        restore_configs: Whether to restore client configurations.
        purge_backups: Whether to delete historical configuration backups.
        claude_settings_path: Backward-compatible override for Claude settings.json path.
        codex_config_path: Backward-compatible override for Codex config.toml path.

    Returns:
        Structured dictionary reporting actions performed:
        {
            "daemon_stopped": bool,
            "claude_restored": bool,
            "codex_restored": bool,
            "restored_clients": dict[str, bool],
            "binaries_removed": list[str],
            "daemon_dir_removed": bool,
            "backups_purged": bool,
        }
    """
    resolved_daemon_dir = Path(daemon_dir) if daemon_dir is not None else Path.home() / ".agy-bridge"
    resolved_bin_dir = Path(bin_dir) if bin_dir is not None else Path.home() / ".local" / "bin"

    # 1. Stop daemon if running
    pid_file = resolved_daemon_dir / "bridge.pid"
    stop_result = bridge.daemon.stop_daemon(pid_file=pid_file)
    daemon_stopped = stop_result.get("status") == "stopped"

    # 2. Determine configurators and paths
    active_configurators = list(configurators) if configurators is not None else list_configurators()
    paths_map: dict[str, Path] = {}
    if custom_config_paths:
        paths_map.update(custom_config_paths)
    if claude_settings_path is not None:
        paths_map["claude"] = Path(claude_settings_path)
    if codex_config_path is not None:
        paths_map["codex"] = Path(codex_config_path)

    # 3. Restore or surgically clean client configurations & purge backups if requested
    restored_clients: dict[str, bool] = {}
    for cfg in active_configurators:
        target_path = cfg.get_config_path(paths_map.get(cfg.name))
        if restore_configs:
            restored = cfg.restore(config_path=target_path)
        else:
            restored = False
        restored_clients[cfg.name] = restored

        if purge_backups:
            cfg.purge_backups(config_path=target_path)

    backups_purged = bool(purge_backups)

    # 4. Remove launcher scripts
    binaries_removed: list[str] = []
    for binary_name in ("agy-bridge", "agy-model-bridge"):
        target_bin = resolved_bin_dir / binary_name
        if target_bin.exists() or target_bin.is_symlink():
            try:
                target_bin.unlink()
                binaries_removed.append(str(target_bin))
            except OSError:
                pass

    # 5. Remove daemon and core directory
    daemon_dir_removed = False
    if resolved_daemon_dir.exists():
        try:
            if resolved_daemon_dir.is_dir():
                shutil.rmtree(resolved_daemon_dir)
            else:
                resolved_daemon_dir.unlink()
            daemon_dir_removed = True
        except OSError:
            daemon_dir_removed = False

    return {
        "daemon_stopped": daemon_stopped,
        "claude_restored": restored_clients.get("claude", False),
        "codex_restored": restored_clients.get("codex", False),
        "restored_clients": restored_clients,
        "binaries_removed": binaries_removed,
        "daemon_dir_removed": daemon_dir_removed,
        "backups_purged": backups_purged,
    }


def _get_installed_version(target_dir: Path | None = None) -> str:
    """Reads the installed version from target_dir/bridge/__init__.py or falls back to __version__."""
    if target_dir is not None:
        init_file = target_dir / "bridge" / "__init__.py"
        if init_file.is_file():
            try:
                match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', init_file.read_text(encoding="utf-8"))
                if match:
                    return match.group(1)
            except OSError:
                pass
    return __version__


def update_installation(
    core_dir: Path | None = None,
    restart_daemon_if_running: bool = True,
) -> dict[str, Any]:
    """Updates the AGY Model Bridge installation in-place via git pull.

    Discovers core repo location:
    If core_dir is None: checks Path.home() / ".agy-bridge" / "core".
    If that does not exist or lacks .git, falls back to checking current working directory / repo parent.

    Runs git -C <dir> pull --ff-only.
    Detects if changes were pulled or if already up to date.
    If restart_daemon_if_running and changes were pulled:
      Checks if daemon is currently running via bridge.daemon.read_pid() and bridge.daemon.is_pid_alive().
      If running: calls bridge.daemon.stop_daemon(), then bridge.daemon.start_daemon(no_open=True).

    Returns:
        dict[str, Any]: {
            "status": "updated" | "already_up_to_date" | "error",
            "message": str,
            "restarted_daemon": bool,
            "version": str,
        }
    """
    if core_dir is not None:
        target_dir = Path(core_dir)
    else:
        default_dir = Path.home() / ".agy-bridge" / "core"
        if (default_dir / ".git").exists():
            target_dir = default_dir
        elif (Path.cwd() / ".git").exists():
            target_dir = Path.cwd()
        else:
            repo_root = Path(__file__).resolve().parent.parent
            if (repo_root / ".git").exists():
                target_dir = repo_root
            else:
                target_dir = default_dir

    if not target_dir.exists() or not (target_dir / ".git").exists():
        return {
            "status": "error",
            "message": t("update_not_git_repo", target_dir=target_dir),
            "restarted_daemon": False,
            "version": _get_installed_version(target_dir),
        }

    cmd = ["git", "-C", str(target_dir), "pull", "--ff-only"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return {
            "status": "error",
            "message": t("update_git_not_found"),
            "restarted_daemon": False,
            "version": _get_installed_version(target_dir),
        }
    except OSError as exc:
        return {
            "status": "error",
            "message": t("update_git_error", exc=exc),
            "restarted_daemon": False,
            "version": _get_installed_version(target_dir),
        }

    if res.returncode != 0:
        err_msg = res.stderr.strip() or res.stdout.strip() or f"git pull falló con código {res.returncode}"
        return {
            "status": "error",
            "message": err_msg,
            "restarted_daemon": False,
            "version": _get_installed_version(target_dir),
        }

    stdout_lower = res.stdout.lower()
    if "already up to date" in stdout_lower or "already up-to-date" in stdout_lower:
        return {
            "status": "already_up_to_date",
            "message": t("update_up_to_date"),
            "restarted_daemon": False,
            "version": _get_installed_version(target_dir),
        }

    restarted_daemon = False
    if restart_daemon_if_running:
        pid = bridge.daemon.read_pid()
        if pid is not None and bridge.daemon.is_pid_alive(pid):
            bridge.daemon.stop_daemon()
            start_res = bridge.daemon.start_daemon(no_open=True)
            if start_res.get("status") == "started":
                restarted_daemon = True

    return {
        "status": "updated",
        "message": t("update_completed"),
        "restarted_daemon": restarted_daemon,
        "version": _get_installed_version(target_dir),
    }




