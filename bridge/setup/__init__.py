"""Client setup and configuration file utilities for agy-model-bridge.

Provides atomic file replacement and ISO-8601 timestamped backups for Claude Code,
Codex CLI, Hermes Agent, OpenCode, OpenClaw, Cursor, Pi, and Gentle Shell.
Zero external dependencies: pure Python standard library.
"""

import subprocess

from bridge.setup.base import (
    CLIENT_CONFIGURATORS,
    ClientConfigurator,
    ConfigPath,
    get_configurator,
    list_configurators,
    register_configurator,
)
from bridge.setup.claude import (
    DEFAULT_CLAUDE_MODEL_PICKER_OPTIONS,
    ClaudeConfigurator,
    restore_claude,
    setup_claude,
)
from bridge.setup.codex import (
    CODEX_BLOCK_REGEX,
    CODEX_ROOT_CONFLICT_REGEX,
    CodexConfigurator,
    build_codex_block,
    restore_codex,
    setup_codex,
)
from bridge.setup.common import (
    BACKUP_TIMESTAMP_REGEX,
    _strip_json_comments,
    atomic_write_file,
    create_backup,
    create_zero_state_backup,
    describe_backup,
    get_active_api_key,
    list_backups,
    restore_backup,
)
from bridge.setup.cursor import (
    CursorConfigurator,
    setup_cursor,
)
from bridge.setup.hermes import (
    HERMES_BLOCK_REGEX,
    HermesConfigurator,
    build_hermes_block,
    comment_out_hermes_model_block,
    restore_hermes,
    setup_hermes,
)
from bridge.setup.lifecycle import (
    _get_installed_version,
    uninstall,
    update_installation,
)
from bridge.setup.openclaw import (
    OpenClawConfigurator,
    restore_openclaw,
    setup_openclaw,
)
from bridge.setup.opencode import (
    OpenCodeConfigurator,
    restore_opencode,
    setup_opencode,
)
from bridge.setup.pi_gentle import (
    DEFAULT_PI_AND_GENTLE_MODELS,
    GentleShellConfigurator,
    PiConfigurator,
    _cleanup_pi_or_gentle_settings,
    restore_gentle_shell,
    restore_pi,
    setup_gentle_shell,
    setup_pi,
)

# Register default configurators
register_configurator(ClaudeConfigurator())
register_configurator(CodexConfigurator())
register_configurator(HermesConfigurator())
register_configurator(OpenCodeConfigurator())
register_configurator(OpenClawConfigurator())
register_configurator(CursorConfigurator())
register_configurator(PiConfigurator())
_gentle_shell = GentleShellConfigurator()
register_configurator(_gentle_shell)
CLIENT_CONFIGURATORS["gentle"] = _gentle_shell

__all__ = [
    "BACKUP_TIMESTAMP_REGEX",
    "CLIENT_CONFIGURATORS",
    "CODEX_BLOCK_REGEX",
    "CODEX_ROOT_CONFLICT_REGEX",
    "ClaudeConfigurator",
    "ClientConfigurator",
    "CodexConfigurator",
    "ConfigPath",
    "CursorConfigurator",
    "DEFAULT_CLAUDE_MODEL_PICKER_OPTIONS",
    "DEFAULT_PI_AND_GENTLE_MODELS",
    "GentleShellConfigurator",
    "HERMES_BLOCK_REGEX",
    "HermesConfigurator",
    "OpenClawConfigurator",
    "OpenCodeConfigurator",
    "PiConfigurator",
    "_cleanup_pi_or_gentle_settings",
    "_get_installed_version",
    "_strip_json_comments",
    "atomic_write_file",
    "build_codex_block",
    "build_hermes_block",
    "comment_out_hermes_model_block",
    "create_backup",
    "create_zero_state_backup",
    "describe_backup",
    "get_active_api_key",
    "get_configurator",
    "list_backups",
    "list_configurators",
    "register_configurator",
    "restore_backup",
    "restore_claude",
    "restore_codex",
    "restore_gentle_shell",
    "restore_hermes",
    "restore_openclaw",
    "restore_opencode",
    "restore_pi",
    "setup_claude",
    "setup_codex",
    "setup_cursor",
    "setup_gentle_shell",
    "setup_hermes",
    "setup_openclaw",
    "setup_opencode",
    "setup_pi",
    "subprocess",
    "uninstall",
    "update_installation",
]
