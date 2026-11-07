"""CLI entry point and command dispatcher for agy-model-bridge."""

from pathlib import Path
import sys

from bridge import __version__
from bridge.cli import (
    handle_dashboard,
    handle_restore_cli,
    handle_server,
    handle_setup_claude,
    handle_setup_codex,
    handle_setup_cursor,
    handle_setup_gentle_shell,
    handle_setup_hermes,
    handle_setup_openclaw,
    handle_setup_opencode,
    handle_setup_pi,
    handle_restart,
    handle_start,
    handle_status,
    handle_stop,
    handle_uninstall,
    handle_update,
)
from bridge.daemon import (
    get_daemon_status,
    open_dashboard,
    restart_daemon,
    start_daemon,
    stop_daemon,
)
from bridge.i18n import set_locale
from bridge.server import run_server
from bridge.setup import (
    get_configurator,
    setup_claude,
    setup_codex,
    setup_cursor,
    setup_gentle_shell,
    setup_hermes,
    setup_openclaw,
    setup_opencode,
    setup_pi,
    uninstall,
    update_installation,
)

# Re-export for compatibility with mock patches targeting bridge.__main__
_handle_restore_cli = handle_restore_cli


def main(argv: list[str] | None = None) -> int:
    """Entry point for agy-model-bridge daemon and client setup subcommands."""
    if argv is None:
        argv = sys.argv[1:]

    # Parse and extract optional --lang flag from argv
    clean_argv: list[str] = []
    lang_flag: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--lang" and i + 1 < len(argv):
            lang_flag = argv[i + 1]
            i += 2
        elif arg.startswith("--lang="):
            lang_flag = arg.split("=", 1)[1]
            i += 1
        else:
            clean_argv.append(arg)
            i += 1
    argv = clean_argv
    if lang_flag is not None:
        set_locale(lang_flag)

    raw_prog = Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "abridge"
    if raw_prog in ("abridge", "agy-bridge", "agy-model-bridge"):
        prog_base = raw_prog
    elif raw_prog.endswith(".py"):
        prog_base = "python3 -m bridge"
    else:
        prog_base = "abridge"

    if argv and any(a in ("--version", "-v") for a in argv):
        print(f"{prog_base} v{__version__}")
        return 0

    # Root help must list the real subcommands, not just the foreground-server
    # flags. `-help` is a common single-dash typo; treat it like --help.
    if argv and argv[0] in ("-h", "--help", "-help"):
        _print_root_help(prog_base)
        return 0

    if argv and argv[0] in ("update", "upgrade"):
        return handle_update(argv[1:], prog_base, subcmd=argv[0], update_fn=update_installation)

    if argv and argv[0] == "start":
        return handle_start(argv[1:], prog_base, start_fn=start_daemon)

    if argv and argv[0] == "stop":
        return handle_stop(argv[1:], prog_base, stop_fn=stop_daemon)

    if argv and argv[0] == "restart":
        return handle_restart(argv[1:], prog_base, restart_fn=restart_daemon)

    if argv and argv[0] == "status":
        return handle_status(argv[1:], prog_base, status_fn=get_daemon_status)

    if argv and argv[0] in ("dashboard", "open"):
        return handle_dashboard(
            argv[1:],
            prog_base,
            subcmd=argv[0],
            open_fn=open_dashboard,
            status_fn=get_daemon_status,
        )

    if argv and argv[0] == "setup-claude":
        return handle_setup_claude(argv[1:], prog_base, setup_fn=setup_claude)

    if argv and argv[0] == "setup-codex":
        return handle_setup_codex(argv[1:], prog_base, setup_fn=setup_codex)

    if argv and argv[0] == "setup-hermes":
        return handle_setup_hermes(argv[1:], prog_base, setup_fn=setup_hermes)

    if argv and argv[0] == "setup-opencode":
        return handle_setup_opencode(argv[1:], prog_base, setup_fn=setup_opencode)

    if argv and argv[0] == "setup-openclaw":
        return handle_setup_openclaw(argv[1:], prog_base, setup_fn=setup_openclaw)

    if argv and argv[0] == "setup-cursor":
        return handle_setup_cursor(argv[1:], prog_base, setup_fn=setup_cursor)

    if argv and argv[0] == "setup-pi":
        return handle_setup_pi(argv[1:], prog_base, setup_fn=setup_pi)

    if argv and argv[0] in ("setup-gentle-shell", "setup-gentle"):
        return handle_setup_gentle_shell(
            argv[1:],
            prog_base,
            subcmd=argv[0],
            setup_fn=setup_gentle_shell,
        )

    if argv and argv[0] == "restore-claude":
        return _handle_restore_cli(
            client_name="Claude Code",
            default_target=Path.home() / ".claude" / "settings.json",
            argv=argv[1:],
            prog_name=f"{prog_base} restore-claude",
        )

    if argv and argv[0] == "restore-codex":
        return _handle_restore_cli(
            client_name="Codex CLI",
            default_target=Path.home() / ".codex" / "config.toml",
            argv=argv[1:],
            prog_name=f"{prog_base} restore-codex",
        )

    if argv and argv[0] == "restore-hermes":
        return _handle_restore_cli(
            client_name="Hermes Agent",
            default_target=Path.home() / ".hermes" / "config.yaml",
            argv=argv[1:],
            prog_name=f"{prog_base} restore-hermes",
        )

    if argv and argv[0] == "restore-opencode":
        return _handle_restore_cli(
            client_name="OpenCode",
            default_target=get_configurator("opencode").default_config_path,
            argv=argv[1:],
            prog_name=f"{prog_base} restore-opencode",
        )

    if argv and argv[0] == "restore-openclaw":
        return _handle_restore_cli(
            client_name="OpenClaw",
            default_target=get_configurator("openclaw").default_config_path,
            argv=argv[1:],
            prog_name=f"{prog_base} restore-openclaw",
        )

    if argv and argv[0] == "restore-pi":
        return _handle_restore_cli(
            client_name="Pi",
            default_target=get_configurator("pi").default_config_path,
            argv=argv[1:],
            prog_name=f"{prog_base} restore-pi",
        )

    if argv and argv[0] in ("restore-gentle-shell", "restore-gentle"):
        return _handle_restore_cli(
            client_name="Gentle Shell",
            default_target=get_configurator("gentle-shell").default_config_path,
            argv=argv[1:],
            prog_name=f"{prog_base} {argv[0]}",
        )

    if argv and argv[0] == "uninstall":
        return handle_uninstall(argv[1:], prog_base, uninstall_fn=uninstall)

    # Fallback to daemon server runner
    return handle_server(argv, prog_base, run_server_fn=run_server)





def _print_root_help(prog_base: str) -> None:
    """Prints a top-level help listing the available subcommands."""
    from bridge.i18n import t

    title = t("cli_description")
    print(f"usage: {prog_base} <command> [options]\n")
    print(title)
    print("\nCommands:")
    cmds = [
        ("start", t("cli_cmd_start")),
        ("stop", t("cli_cmd_stop")),
        ("restart", t("cli_cmd_restart")),
        ("status", t("cli_cmd_status")),
        ("dashboard", t("cli_cmd_dashboard")),
        ("setup-claude", t("cli_cmd_setup_claude")),
        ("setup-codex", t("cli_cmd_setup_codex")),
        ("setup-hermes", t("cli_cmd_setup_hermes")),
        ("setup-opencode", t("cli_cmd_setup_opencode")),
        ("setup-openclaw", t("cli_cmd_setup_openclaw")),
        ("setup-cursor", t("cli_cmd_setup_cursor")),
        ("setup-pi", t("cli_cmd_setup_pi")),
        ("setup-gentle-shell", t("cli_cmd_setup_gentle")),
        ("update", t("cli_cmd_update")),
        ("uninstall", t("cli_cmd_uninstall")),
        ("--version", "Show version"),
        ("--help", "Show this help"),
    ]
    width = max(len(c) for c, _ in cmds)
    for cmd, desc in cmds:
        print(f"  {cmd.ljust(width)}  {desc}")
    print("\nRun `{0} <command> --help` for command details.".format(prog_base))


if __name__ == "__main__":
    sys.exit(main())
