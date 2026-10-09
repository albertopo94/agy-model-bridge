"""Configurator strategy and setup functions for Hermes Agent."""

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

HERMES_BLOCK_REGEX = re.compile(
    r"^[ \t]*# agy:start[\s\S]*?^[ \t]*# agy:end[ \t]*(?:\r?\n)?",
    re.MULTILINE,
)


def build_hermes_block(
    base_url: str,
    model: str = "gemini-3.8-flash-high",
    auth_token: str = "local-bridge",
    port: int = 24980,
) -> str:
    """Constructs the delimited agy configuration block for Hermes config.yaml."""
    return (
        "# agy:start\n"
        "model:\n"
        f'  default: "{model}"\n'
        f'  provider: "custom:local-(127.0.0.1:{port})"\n'
        f'  base_url: "{base_url}"\n'
        '  api_mode: "chat_completions"\n'
        f'  api_key: "{auth_token}"\n'
        "# agy:end"
    )


def comment_out_hermes_model_block(text: str) -> str:
    """Comments out any pre-existing un-commented model: block in YAML to prevent duplicate keys."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_model_section = False
    for line in lines:
        stripped = line.strip()
        if re.match(r"^model\s*:", line) and not line.startswith("#"):
            in_model_section = True
            out.append(f"# [agy-disabled] {line}")
            continue
        if in_model_section:
            if line.startswith(" ") or line.startswith("\t"):
                out.append(f"# [agy-disabled] {line}")
            elif not stripped:
                out.append(line)
            else:
                in_model_section = False
                out.append(line)
        else:
            out.append(line)
    return "".join(out)


class HermesConfigurator(ClientConfigurator):
    """Configurator strategy for Hermes Agent."""

    name = "hermes"
    display_name = "Hermes Agent"

    @property
    def default_config_path(self) -> Path:
        return Path.home() / ".hermes" / "config.yaml"

    def is_configured(self, config_path: Path | None = None) -> bool:
        target = self.get_config_path(config_path)
        if not target.exists() or not target.is_file():
            return False
        try:
            content = target.read_text(encoding="utf-8")
            if (
                HERMES_BLOCK_REGEX.search(content)
                or "# agy:start" in content
                or "custom:local-" in content
                or ":24980" in content
                or "127.0.0.1:24980" in content
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
        auth_token = kwargs.get("auth_token") or get_active_api_key()

        if base_url:
            resolved_url = base_url.rstrip("/")
            if not resolved_url.endswith("/v1"):
                resolved_url = f"{resolved_url}/v1"
        elif port is not None:
            resolved_url = f"http://127.0.0.1:{port}/v1"
        else:
            resolved_url = "http://127.0.0.1:24980/v1"

        if port is not None:
            resolved_port = port
        else:
            m = re.search(r":(\d+)", resolved_url)
            resolved_port = int(m.group(1)) if m else 24980

        block = build_hermes_block(
            base_url=resolved_url,
            model=model,
            auth_token=auth_token,
            port=resolved_port,
        )

        backup_path = None
        if target.exists():
            backup_path = create_backup(target)
            existing_content = target.read_text(encoding="utf-8")
            if HERMES_BLOCK_REGEX.search(existing_content):
                existing_content = HERMES_BLOCK_REGEX.sub("", existing_content)

            existing_content = comment_out_hermes_model_block(existing_content)
            if existing_content.strip():
                new_content = block + "\n\n" + existing_content.strip() + "\n"
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
                if HERMES_BLOCK_REGEX.search(content) or "# [agy-disabled]" in content:
                    cleaned = HERMES_BLOCK_REGEX.sub("", content).strip()
                    cleaned = re.sub(
                        r"^[ \t]*#[ \t]*\[agy-disabled\][ \t]?",
                        "",
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


def setup_hermes(
    config_path: Path | None = None,
    base_url: str | None = None,
    port: int | None = None,
    model: str = "gemini-3.8-flash-high",
    auth_token: str | None = None,
) -> ConfigPath:
    """Configures Hermes Agent config.yaml with delimited agy configuration block."""
    return cast(
        ConfigPath,
        get_configurator("hermes").setup(
            base_url=base_url,
            model=model,
            config_path=config_path,
            port=port,
            auth_token=auth_token,
        ),
    )


def restore_hermes(
    config_path: Path | None = None,
    backup_path: Path | None = None,
) -> bool:
    """Restores Hermes Agent config.yaml from backup or surgically removes agy block."""
    return get_configurator("hermes").restore(
        config_path=config_path,
        backup_path=backup_path,
    )
