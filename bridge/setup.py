"""Client setup and configuration file utilities for agy-model-bridge.

Provides atomic file replacement and ISO-8601 timestamped backups for Claude Code
and Codex CLI configuration files.
Zero external dependencies: pure Python standard library.
"""

from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any
import uuid


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


class ConfigPath(type(Path())):
    """Path subclass that carries an optional backup_path attribute."""
    backup_path: Path | None = None


def setup_claude(
    settings_path: Path | None = None,
    base_url: str | None = None,
    port: int | None = None,
    model: str = "gemini-3.8-flash-high",
    auth_token: str = "antigravity",
) -> Path:
    """Configures Claude Code settings.json with agy-model-bridge environment variables.

    Creates a timestamped backup if settings.json exists, surgically merges bridge
    keys into 'env', preserves user keys and top-level settings, and writes atomically
    with mode 0o600.

    Args:
        settings_path: Path to settings.json (defaults to ~/.claude/settings.json).
        base_url: Base URL for gateway (default: http://127.0.0.1:24980 or http://127.0.0.1:{port}).
        port: Gateway port override.
        model: Default model identifier (default: gemini-3.8-flash-high).
        auth_token: Gateway auth token (default: antigravity).

    Returns:
        Path of configured settings.json file.
    """
    if settings_path is None:
        target = Path.home() / ".claude" / "settings.json"
    else:
        target = Path(settings_path)

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

    formatted_json = json.dumps(settings, indent=2) + "\n"
    atomic_write_file(target, formatted_json, mode=0o600)
    res = ConfigPath(target)
    res.backup_path = backup_path
    return res


CODEX_BLOCK_REGEX = re.compile(
    r"^[ \t]*# agy:start[\s\S]*?^[ \t]*# agy:end[ \t]*(?:\r?\n)?",
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


def setup_codex(
    config_path: Path | None = None,
    base_url: str | None = None,
    port: int | None = None,
    model: str = "gemini-3.8-flash-high",
) -> Path:
    """Configures Codex CLI config.toml with delimited agy configuration block.

    Creates a timestamped backup if config.toml exists, replaces or inserts the
    delimited block (# agy:start ... # agy:end), preserves all existing tables and
    content outside the block, and writes atomically with mode 0o600.

    Args:
        config_path: Path to config.toml (defaults to ~/.codex/config.toml).
        base_url: Base URL for gateway (default: http://127.0.0.1:24980/v1 or http://127.0.0.1:{port}/v1).
        port: Gateway port override.
        model: Default model identifier (default: gemini-3.8-flash-high).

    Returns:
        Path of configured config.toml file.
    """
    if config_path is None:
        target = Path.home() / ".codex" / "config.toml"
    else:
        target = Path(config_path)

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
            new_content = CODEX_BLOCK_REGEX.sub(block + "\n", existing_content)
        else:
            table_match = re.search(r"^[ \t]*\[", existing_content, re.MULTILINE)
            if table_match:
                prefix = existing_content[:table_match.start()]
                suffix = existing_content[table_match.start():]
                if prefix.strip():
                    new_content = prefix.rstrip() + "\n\n" + block + "\n\n" + suffix.lstrip()
                else:
                    new_content = block + "\n\n" + suffix.lstrip()
            elif existing_content.strip():
                new_content = block + "\n\n" + existing_content.lstrip()
            else:
                new_content = block + "\n"
    else:
        new_content = block + "\n"

    atomic_write_file(target, new_content, mode=0o600)
    res = ConfigPath(target)
    res.backup_path = backup_path
    return res


