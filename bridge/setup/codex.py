"""Configurator strategy and setup functions for Codex CLI."""

from pathlib import Path
import re
from typing import Any, cast

from bridge.setup.base import ClientConfigurator, ConfigPath, get_configurator
from bridge.setup.common import (
    atomic_write_file,
    create_backup,
    get_active_api_key,
    restore_backup,
)

CODEX_BLOCK_REGEX = re.compile(
    r"^[ \t]*# agy:start[\s\S]*?^[ \t]*# agy:end[ \t]*(?:\r?\n)?",
    re.MULTILINE,
)

CODEX_ROOT_CONFLICT_REGEX = re.compile(
    r"^[ \t]*(model|model_provider|model_context_window|model_auto_compact_token_limit)[ \t]*=.*$",
    re.MULTILINE,
)


def build_codex_block(model: str, base_url: str, auth_token: str | None = None) -> str:
    """Constructs the delimited agy configuration block for Codex config.toml."""
    headers_line = f'http_headers = {{ Authorization = "Bearer {auth_token}" }}\n' if auth_token else ""
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
        f"{headers_line}"
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

        auth_token = kwargs.get("auth_token") or get_active_api_key()
        block = build_codex_block(model=model, base_url=resolved_url, auth_token=auth_token)

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


def setup_codex(
    config_path: Path | None = None,
    base_url: str | None = None,
    port: int | None = None,
    model: str = "gemini-3.8-flash-high",
    auth_token: str | None = None,
) -> ConfigPath:
    """Configures Codex CLI config.toml with delimited agy configuration block."""
    return cast(
        ConfigPath,
        get_configurator("codex").setup(
            base_url=base_url,
            model=model,
            config_path=config_path,
            port=port,
            auth_token=auth_token,
        ),
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
