"""CLI handlers for update and uninstall lifecycle operations."""

import argparse
from pathlib import Path
from typing import Any

from bridge import __version__
from bridge.i18n import get_locale, is_yes, t
from bridge.setup import uninstall, update_installation


def handle_update(
    argv: list[str],
    prog_base: str,
    subcmd: str,
    update_fn: Any = None,
) -> int:
    """Handles 'update' and 'upgrade' CLI subcommands."""
    fn = update_fn or update_installation
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
    args = parser.parse_args(argv)

    res = fn(
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


def handle_uninstall(
    argv: list[str],
    prog_base: str,
    uninstall_fn: Any = None,
) -> int:
    """Handles the 'uninstall' CLI subcommand."""
    fn = uninstall_fn or uninstall
    parser = argparse.ArgumentParser(
        prog=f"{prog_base} uninstall",
        description="Uninstall AGY Model Bridge and restore client configurations.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip interactive confirmation prompt",
    )
    parser.add_argument(
        "--keep-configs",
        action="store_true",
        help="Do not restore original client configurations",
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Permanently delete historical configuration backups",
    )
    parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
    args = parser.parse_args(argv)

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

    res = fn(
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
    if res.get("openclaw_restored"):
        print(t("uninstall_openclaw_restored"))
    if res.get("pi_restored"):
        print(t("uninstall_pi_restored"))
    if res.get("gentle_shell_restored"):
        print(t("uninstall_gentle_shell_restored"))
    if res.get("backups_purged"):
        print(t("uninstall_backups_purged"))
    return 0
