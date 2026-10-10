"""Common utilities for client configuration and backups."""

from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil

from bridge.security import get_or_create_api_key, write_secret_file

BACKUP_TIMESTAMP_REGEX = re.compile(r"\.backup-(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}(?:-\d+)?)$")


def atomic_write_file(path: Path, content: str, mode: int = 0o600) -> None:
    """Atomically writes content to path using a tempfile and os.replace.

    Ensures parent directories exist with 0o700 permissions, fsyncs data to disk,
    sets file mode to 0o600 (or specified mode), and atomically renames.

    Args:
        path: Target file Path.
        content: String content to write (UTF-8).
        mode: Octal file permissions (default 0o600).
    """
    write_secret_file(path, content, mode=mode, encoding="utf-8")


def _strip_json_comments(text: str) -> str:
    """Strips single-line and multi-line comments from JSONC text while preserving string literals."""
    def replacer(match: re.Match[str]) -> str:
        s = match.group(0)
        if s.startswith("/"):
            return " "
        return s

    pattern = re.compile(
        r'//.*?$|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"',
        re.DOTALL | re.MULTILINE,
    )
    return pattern.sub(replacer, text)


def create_backup(path: Path) -> Path | None:
    """Creates a timestamped backup of path if it exists.

    Backup filename pattern: <path>.backup-YYYY-MM-DDTHH-MM-SS-ffffff

    Args:
        path: Path to file to backup.

    Returns:
        Path of created backup file, or None if source file does not exist.
    """
    path = Path(path)
    if not path.exists() or not path.is_file():
        return None

    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")
    backup_path = path.with_name(f"{path.name}.backup-{timestamp}")
    shutil.copy2(path, backup_path)
    return backup_path


def create_zero_state_backup(target_path: Path) -> Path:
    """Creates a zero-state marker backup file when target configuration did not exist previously."""
    target_path = Path(target_path)
    parent = target_path.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    else:
        try:
            os.chmod(parent, 0o700)
        except OSError:
            pass

    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")
    backup_path = target_path.with_name(f"{target_path.name}.backup-{timestamp}-original")
    content = json.dumps({"_zero_state": True}, indent=2) + "\n"
    atomic_write_file(backup_path, content, mode=0o600)
    return backup_path


def list_backups(config_path: Path) -> list[Path]:
    """Lists all historical backup files for config_path sorted by mtime descending.

    Discovers both agy-model-bridge (.backup-YYYY-MM-DDTHH-MM-SS) and FreeLLMAPI
    (.freellmapi-backup-YYYY-MM-DDTHH-MM-SS) backups.

    Args:
        config_path: Path to configuration file.

    Returns:
        List of backup Paths sorted newest first. Empty list if none found.
    """
    target = Path(config_path)
    parent = target.parent
    if not parent.exists() or not parent.is_dir():
        return []

    prefix = f"{target.name}.backup-"
    prefix_freellmapi = f"{target.name}.freellmapi-backup-"

    backups: list[Path] = []
    try:
        for entry in parent.iterdir():
            if not entry.is_file():
                continue
            name = entry.name
            if name.startswith(prefix) or name.startswith(prefix_freellmapi):
                backups.append(entry)
    except OSError:
        return []

    backups.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return backups


def describe_backup(backup_path: Path) -> str:
    """Identifies the provenance/origin of a configuration backup file.

    Inspects content and naming patterns to classify backups as:
    - "AGY Bridge": Antigravity Model Bridge configuration
    - "FreeLLMAPI": FreeLLMAPI configuration
    - "Anthropic Original": Original un-proxied Claude Code configuration
    - "Codex Original": Original un-proxied Codex CLI configuration
    - "OpenCode Original": Original un-proxied OpenCode configuration
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

    if "_zero_state" in content or path.name.endswith("-original"):
        if ".gentle-shell" in str(path):
            return "Gentle Shell Original"
        if "models.json" in path.name:
            return "Pi Original"
        return "Original Clean State"

    # OpenCode JSON config inspection
    if "opencode.json" in path.name or "opencode.jsonc" in path.name:
        if '"agy"' in content or ":24980" in content or "agy/" in content:
            return "AGY Bridge"
        return "OpenCode Original"

    # OpenClaw JSON config inspection
    if "openclaw.json" in path.name or "openclaw" in content.lower():
        if '"agy"' in content or ":24980" in content or "agy/" in content:
            return "AGY Bridge"
        return "OpenClaw Original"

    # Gentle Shell models.json config inspection
    if ".gentle-shell" in str(path):
        if '"freellmapi"' in content or ":31415" in content or "freellmapi/" in content:
            if '"agy"' not in content and ":24980" not in content:
                return "FreeLLMAPI"
        if '"agy"' in content or ":24980" in content or "agy/" in content:
            return "AGY Bridge"
        return "Gentle Shell Original"

    # Pi models.json config inspection
    if "models.json" in path.name:
        if '"freellmapi"' in content or ":31415" in content or "freellmapi/" in content:
            if '"agy"' not in content and ":24980" not in content:
                return "FreeLLMAPI"
        if '"agy"' in content or ":24980" in content or "agy/" in content:
            return "AGY Bridge"
        return "Pi Original"

    # Claude Code / Gentle Shell / Pi JSON settings inspection
    if "settings.json" in path.name or content.lstrip().startswith("{"):
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                default_prov = str(data.get("defaultProvider", "")).lower()
                if default_prov == "freellmapi":
                    return "FreeLLMAPI"
                if default_prov == "agy":
                    return "AGY Bridge"

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

    # Codex TOML and Hermes YAML config inspection
    if (
        "# agy:start" in content
        or "[model_providers.agy]" in content
        or 'model_provider = "agy"' in content
        or ":24980" in content
        or "custom:local-" in content
    ):
        return "AGY Bridge"
    if (
        "# freellmapi:start" in content
        or "[model_providers.freellmapi]" in content
        or 'model_provider = "freellmapi"' in content
        or ":31415" in content
        or "freellmapi" in content.lower()
    ):
        return "FreeLLMAPI"
    if "config.toml" in path.name or "[projects" in content or "model = " in content or "personality" in content:
        return "Codex Original"
    if (
        "config.yaml" in path.name
        or "config.yml" in path.name
        or "terminal:" in content
        or re.search(r"^[ \t]*model\s*:", content, re.MULTILINE)
    ):
        return "Hermes Original"

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

    try:
        content = chosen_backup.read_text(encoding="utf-8")
    except OSError as exc:
        raise OSError(f"Cannot read backup file {chosen_backup}: {exc}") from exc

    if "_zero_state" in content or chosen_backup.name.endswith("-original"):
        if target.exists() and target.is_file():
            target.unlink(missing_ok=True)
        return target

    atomic_write_file(target, content, mode=0o600)
    return chosen_backup


def get_active_api_key(daemon_dir: Path | None = None) -> str:
    """Returns the active persistent API key for the bridge."""
    return get_or_create_api_key(daemon_dir=daemon_dir)
