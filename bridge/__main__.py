"""CLI runner for Antigravity Model Bridge."""

import argparse
import sys
from pathlib import Path

from bridge import __version__
from bridge.daemon import (
    get_daemon_status,
    open_dashboard,
    start_daemon,
    stop_daemon,
)
from bridge.i18n import get_locale, is_yes, set_locale, t
from bridge.server import run_server
from bridge.setup import (
    describe_backup,
    get_configurator,
    list_backups,
    restore_backup,
    restore_hermes,
    restore_opencode,
    setup_claude,
    setup_codex,
    setup_hermes,
    setup_opencode,
    uninstall,
    update_installation,
)


def _handle_restore_cli(
    client_name: str,
    default_target: Path,
    argv: list[str],
    prog_name: str,
) -> int:
    """Helper to handle restore CLI subcommand for Claude Code or Codex."""
    parser = argparse.ArgumentParser(
        prog=prog_name,
        description=f"Restore {client_name} configuration from a historical backup.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=default_target,
        help=f"Path to {client_name} config file (default: {default_target})",
    )
    parser.add_argument(
        "--backup",
        type=Path,
        default=None,
        help="Specific backup file path to restore",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Restore the most recent backup directly without interactive prompt",
    )
    parser.add_argument(
        "--lang",
        type=str,
        default=None,
        help=t("cli_help_lang"),
    )
    args = parser.parse_args(argv)
    target = args.path

    if args.backup is not None:
        try:
            restored = restore_backup(target, backup_path=args.backup)
            print(t("restore_restored_from", name=restored.name))
            print(t("restore_client_ready", client_name=client_name, target=target))
            return 0
        except FileNotFoundError as exc:
            print(f"Error: {exc}")
            return 1

    backups = list_backups(target)
    if not backups:
        print(t("restore_no_backups", client_name=client_name, parent=target.parent))
        return 1

    if args.latest:
        restored = restore_backup(target, backup_path=backups[0])
        print(t("restore_restored_from", name=restored.name))
        print(t("restore_client_ready", client_name=client_name, target=target))
        return 0

    print(t("restore_available_title", client_name=client_name))
    for i, b in enumerate(backups, 1):
        tag = describe_backup(b)
        tag_str = f"  [{tag}]"
        if i == 1:
            print(f"  [{i}] {b.name}{tag_str}  {t('restore_immediate_prev')}")
        else:
            print(f"  [{i}] {b.name}{tag_str}")

    count = len(backups)
    range_str = f"1-{count}" if count > 1 else "1"
    prompt_str = t("restore_prompt", range_str=range_str)

    try:
        choice = input(prompt_str).strip()
    except (EOFError, KeyboardInterrupt):
        print("\n" + t("restore_cancelled"))
        return 0

    if choice.lower() in ("q", "quit", "cancel"):
        print(t("restore_cancelled"))
        return 0

    if not choice:
        selected_index = 0
    elif choice.isdigit() and 1 <= int(choice) <= count:
        selected_index = int(choice) - 1
    else:
        print(t("restore_invalid_choice"))
        return 1

    restored = restore_backup(target, backup_path=backups[selected_index])
    print("\n" + t("restore_restored_from", name=restored.name))
    print(t("restore_client_ready", client_name=client_name, target=target))
    return 0


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

    prog_base = Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "agy-bridge"
    if prog_base.endswith(".py"):
        prog_base = "python3 -m bridge"

    if argv and any(a in ("--version", "-v") for a in argv):
        print(f"agy-bridge v{__version__}")
        return 0

    if argv and argv[0] in ("update", "upgrade"):
        subcmd = argv[0]
        parser = argparse.ArgumentParser(
            prog=f"{prog_base} {subcmd}",
            description="Update AGY Model Bridge in-place and optionally restart the daemon.",
        )
        parser.add_argument(
            "--no-restart",
            action="store_true",
            help="Do not restart the background daemon if running",
        )
        parser.add_argument(
            "--dir",
            "--core-dir",
            dest="core_dir",
            type=Path,
            default=None,
            help="Directory of the core repository to update",
        )
        parser.add_argument(
            "--lang",
            type=str,
            default=None,
            help=t("cli_help_lang"),
        )
        args = parser.parse_args(argv[1:])

        res = update_installation(
            core_dir=args.core_dir,
            restart_daemon_if_running=not args.no_restart,
        )
        status = res.get("status")
        ver = res.get("version", __version__)
        if status == "updated":
            print(t("update_success", ver=ver))
            if res.get("restarted_daemon"):
                print(t("update_daemon_restarted"))
            return 0
        elif status == "already_up_to_date":
            print(t("update_already_latest", ver=ver))
            return 0
        else:
            print(f"Error: {res.get('message', t('update_failed'))}")
            return 1

    # Dispatch daemon lifecycle subcommands
    if argv and argv[0] == "start":
        parser = argparse.ArgumentParser(
            prog=f"{prog_base} start",
            description="Start AGY Model Bridge in the background as a daemon process.",
        )
        parser.add_argument("--port", type=int, default=24980, help="Gateway port (default: 24980)")
        parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address (default: 127.0.0.1)")
        parser.add_argument("--no-open", action="store_true", help="Do not open web browser automatically")
        parser.add_argument("--project", type=str, default=None, help="Google Cloud project ID override")
        parser.add_argument("--base-url", type=str, default=None, help="Upstream API base URL override")
        parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
        args = parser.parse_args(argv[1:])

        res = start_daemon(
            port=args.port,
            host=args.host,
            no_open=args.no_open,
            project=args.project,
            base_url=args.base_url,
        )
        st = res.get("status")
        if st == "started":
            browser_hint = t("daemon_browser_opened") if res.get("opened_browser") else ""
            print(t("daemon_running_bg", pid=res['pid']))
            print(t("daemon_dashboard_url", url=res['url'], browser_hint=browser_hint))
            print(t("daemon_stop_hint", prog_base=prog_base))
            return 0
        elif st == "already_running":
            pid_str = f" (PID {res['pid']})" if res.get("pid") else ""
            print(t("daemon_already_running", pid_str=pid_str))
            print(t("daemon_dashboard_url", url=res['url'], browser_hint=""))
            print(t("daemon_stop_hint", prog_base=prog_base))
            return 0
        else:
            print(f"Error: {res.get('error', t('daemon_start_failed'))}")
            return 1

    if argv and argv[0] == "stop":
        parser = argparse.ArgumentParser(
            prog=f"{prog_base} stop",
            description="Stop the running background AGY Model Bridge daemon.",
        )
        parser.add_argument("--port", type=int, default=24980, help="Gateway port (default: 24980)")
        parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address (default: 127.0.0.1)")
        parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
        args = parser.parse_args(argv[1:])
        res = stop_daemon(port=args.port, host=args.host)
        if res.get("status") == "stopped":
            pid_str = f" (PID {res['pid']})" if res.get("pid") else ""
            print(t("daemon_stopped", pid_str=pid_str))
        else:
            print(t("daemon_not_running"))
        return 0

    if argv and argv[0] == "status":
        parser = argparse.ArgumentParser(
            prog=f"{prog_base} status",
            description="Check the status of the AGY Model Bridge daemon.",
        )
        parser.add_argument("--port", type=int, default=24980, help="Gateway port (default: 24980)")
        parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address (default: 127.0.0.1)")
        parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
        args = parser.parse_args(argv[1:])
        st = get_daemon_status(port=args.port, host=args.host)
        if st.get("running"):
            auth_st = st.get("auth", {}).get("status", "Valid")
            pid_str = f" (PID {st['pid']})" if st.get("pid") else ""
            print(t("status_active", pid_str=pid_str))
            print(t("status_address", url=st['url']))
            print(t("status_models", count=st.get('models_count', 0)))
            print(t("status_auth", status=auth_st))
        else:
            print(t("status_stopped"))
            print(t("status_start_hint", prog_base=prog_base))
        return 0

    if argv and argv[0] in ("dashboard", "open"):
        parser = argparse.ArgumentParser(
            prog=f"{prog_base} {argv[0]}",
            description="Open the AGY Model Bridge local dashboard in the default browser.",
        )
        parser.add_argument("--port", type=int, default=24980, help="Gateway port (default: 24980)")
        parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address (default: 127.0.0.1)")
        parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
        args = parser.parse_args(argv[1:])
        st = get_daemon_status(port=args.port, host=args.host)
        if not st.get("running"):
            print(t("dashboard_not_active", url=st['url']))
            print(t("status_start_hint", prog_base=prog_base))
        print(t("dashboard_opening", url=st['url']))
        open_dashboard(port=args.port, host=args.host)
        return 0

    # Dispatch client setup subcommands
    if argv and argv[0] == "setup-claude":
        parser = argparse.ArgumentParser(
            prog=f"{prog_base} setup-claude",
            description="Configure Claude Code settings.json for agy-model-bridge gateway.",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=None,
            help="Gateway port (default: 24980)",
        )
        parser.add_argument(
            "--model",
            type=str,
            default="gemini-3.8-flash-high",
            help="Default model identifier (default: gemini-3.8-flash-high)",
        )
        parser.add_argument(
            "--url",
            "--base-url",
            dest="base_url",
            type=str,
            default=None,
            help="Gateway base URL override (without trailing slash)",
        )
        parser.add_argument(
            "--token",
            "--auth-token",
            dest="auth_token",
            type=str,
            default="antigravity",
            help="Gateway auth token (default: antigravity)",
        )
        parser.add_argument(
            "--path",
            type=Path,
            default=None,
            help="Path to Claude settings.json (default: ~/.claude/settings.json)",
        )
        parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
        args = parser.parse_args(argv[1:])
        target = setup_claude(
            settings_path=args.path,
            base_url=args.base_url,
            port=args.port,
            model=args.model,
            auth_token=args.auth_token,
        )
        if getattr(target, "backup_path", None):
            print(t("setup_backup_label", path=target.backup_path))
        print(t("setup_claude_success", target=target))
        print(t("setup_claude_auto_read"))
        print(t("setup_claude_run_hint"))
        return 0

    if argv and argv[0] == "setup-codex":
        parser = argparse.ArgumentParser(
            prog=f"{prog_base} setup-codex",
            description="Configure Codex CLI config.toml for agy-model-bridge gateway.",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=None,
            help="Gateway port (default: 24980)",
        )
        parser.add_argument(
            "--model",
            type=str,
            default="gemini-3.8-flash-high",
            help="Default model identifier (default: gemini-3.8-flash-high)",
        )
        parser.add_argument(
            "--url",
            "--base-url",
            dest="base_url",
            type=str,
            default=None,
            help="Gateway base URL override (with /v1)",
        )
        parser.add_argument(
            "--path",
            type=Path,
            default=None,
            help="Path to Codex config.toml (default: ~/.codex/config.toml)",
        )
        parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
        args = parser.parse_args(argv[1:])
        target = setup_codex(
            config_path=args.path,
            base_url=args.base_url,
            port=args.port,
            model=args.model,
        )
        if getattr(target, "backup_path", None):
            print(t("setup_backup_label", path=target.backup_path))
        print(t("setup_codex_success", target=target))
        print(t("setup_codex_auto_read"))
        print(t("setup_codex_run_hint"))
        return 0

    if argv and argv[0] == "setup-hermes":
        parser = argparse.ArgumentParser(
            prog=f"{prog_base} setup-hermes",
            description="Configure Hermes Agent config.yaml for agy-model-bridge gateway.",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=None,
            help="Gateway port (default: 24980)",
        )
        parser.add_argument(
            "--model",
            type=str,
            default="gemini-3.8-flash-high",
            help="Default model identifier (default: gemini-3.8-flash-high)",
        )
        parser.add_argument(
            "--url",
            "--base-url",
            dest="base_url",
            type=str,
            default=None,
            help="Gateway base URL override (with /v1)",
        )
        parser.add_argument(
            "--token",
            "--auth-token",
            dest="auth_token",
            type=str,
            default="local-bridge",
            help="Gateway auth token (default: local-bridge)",
        )
        parser.add_argument(
            "--path",
            type=Path,
            default=None,
            help="Path to Hermes config.yaml (default: ~/.hermes/config.yaml)",
        )
        parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
        args = parser.parse_args(argv[1:])
        target = setup_hermes(
            config_path=args.path,
            base_url=args.base_url,
            port=args.port,
            model=args.model,
            auth_token=args.auth_token,
        )
        if getattr(target, "backup_path", None):
            print(t("setup_backup_label", path=target.backup_path))
        print(t("setup_hermes_success", target=target))
        print(t("setup_hermes_auto_read"))
        print(t("setup_hermes_run_hint"))
        return 0

    if argv and argv[0] == "setup-opencode":
        parser = argparse.ArgumentParser(
            prog=f"{prog_base} setup-opencode",
            description="Configure OpenCode for agy-model-bridge gateway.",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=None,
            help="Gateway port (default: 24980)",
        )
        parser.add_argument(
            "--model",
            type=str,
            default="gemini-3.8-flash-high",
            help="Default model identifier (default: gemini-3.8-flash-high)",
        )
        parser.add_argument(
            "--url",
            "--base-url",
            dest="base_url",
            type=str,
            default=None,
            help="Gateway base URL override (with /v1)",
        )
        parser.add_argument(
            "--path",
            type=Path,
            default=None,
            help="Path to OpenCode config (default: ~/.config/opencode/opencode.json)",
        )
        parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
        args = parser.parse_args(argv[1:])
        target = setup_opencode(
            config_path=args.path,
            base_url=args.base_url,
            port=args.port,
            model=args.model,
        )
        if getattr(target, "backup_path", None):
            print(t("setup_backup_label", path=target.backup_path))
        print(t("setup_opencode_success", target=target))
        print(t("setup_opencode_auto_read"))
        print(t("setup_opencode_run_hint"))
        return 0

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
            default_target=get_configurator("opencode").get_config_path(),
            argv=argv[1:],
            prog_name=f"{prog_base} restore-opencode",
        )

    if argv and argv[0] == "uninstall":
        parser = argparse.ArgumentParser(
            prog=f"{prog_base} uninstall",
            description="Uninstall AGY Model Bridge, terminate daemon, and restore client configurations.",
        )
        parser.add_argument(
            "-y",
            "--yes",
            action="store_true",
            help="Skip interactive confirmation prompt",
        )
        parser.add_argument(
            "--purge",
            action="store_true",
            help="Purge all historical configuration backups",
        )
        parser.add_argument(
            "--keep-configs",
            action="store_true",
            help="Do not restore Claude/Codex configurations",
        )
        parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
        args = parser.parse_args(argv[1:])

        if not args.yes:
            choice_label = "s/N" if get_locale() == "es" else "y/N"
            prompt_str = t("uninstall_confirm_prompt", choice=choice_label)
            try:
                confirm = input(prompt_str).strip()
            except (EOFError, KeyboardInterrupt):
                print("\n" + t("uninstall_cancelled"))
                return 0

            if not is_yes(confirm):
                print(t("uninstall_cancelled"))
                return 0

        res = uninstall(
            restore_configs=not args.keep_configs,
            purge_backups=args.purge,
        )

        print(t("uninstall_success"))
        if res.get("daemon_stopped"):
            print(t("uninstall_daemon_stopped"))
        if res.get("binaries_removed"):
            print(t("uninstall_binaries_removed", binaries=", ".join(res["binaries_removed"])))
        if res.get("daemon_dir_removed"):
            print(t("uninstall_daemon_dir_removed"))
        if res.get("claude_restored"):
            print(t("uninstall_claude_restored"))
        if res.get("codex_restored"):
            print(t("uninstall_codex_restored"))
        if res.get("hermes_restored"):
            print(t("uninstall_hermes_restored"))
        if res.get("opencode_restored"):
            print(t("uninstall_opencode_restored"))
        if res.get("backups_purged"):
            print(t("uninstall_backups_purged"))
        return 0

    # Fallback to daemon server runner
    parser = argparse.ArgumentParser(
        prog=prog_base,
        description=t("cli_description"),
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"agy-bridge v{__version__}",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help=t("cli_help_host"),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=24980,
        help=t("cli_help_port"),
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help=t("cli_help_project"),
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help=t("cli_help_base_url"),
    )
    parser.add_argument(
        "--lang",
        type=str,
        default=None,
        help=t("cli_help_lang"),
    )
    args = parser.parse_args(argv)
    run_server(host=args.host, port=args.port, project=args.project, base_url=args.base_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
