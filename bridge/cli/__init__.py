"""CLI command modules and handlers for agy-model-bridge."""

from bridge.cli.daemon import (
    handle_dashboard,
    handle_start,
    handle_status,
    handle_stop,
)
from bridge.cli.lifecycle import (
    handle_uninstall,
    handle_update,
)
from bridge.cli.server import handle_server
from bridge.cli.setup import (
    handle_restore_cli,
    handle_setup_claude,
    handle_setup_codex,
    handle_setup_cursor,
    handle_setup_gentle_shell,
    handle_setup_hermes,
    handle_setup_openclaw,
    handle_setup_opencode,
    handle_setup_pi,
)

__all__ = [
    "handle_dashboard",
    "handle_restore_cli",
    "handle_server",
    "handle_setup_claude",
    "handle_setup_codex",
    "handle_setup_cursor",
    "handle_setup_gentle_shell",
    "handle_setup_hermes",
    "handle_setup_openclaw",
    "handle_setup_opencode",
    "handle_setup_pi",
    "handle_start",
    "handle_status",
    "handle_stop",
    "handle_uninstall",
    "handle_update",
]
