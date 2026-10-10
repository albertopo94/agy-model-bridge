"""CLI handlers for client setup and restore subcommands."""

import argparse
from pathlib import Path
from typing import Any

from bridge.i18n import t
from bridge.setup import (
    describe_backup,
    get_configurator,
    list_backups,
    list_configurators,
    restore_backup,
    restore_gentle_shell,
    restore_pi,
    setup_claude,
    setup_codex,
    setup_cursor,
    setup_gentle_shell,
    setup_hermes,
    setup_openclaw,
    setup_opencode,
    setup_pi,
)


def handle_restore_cli(
    client_name: str,
    default_target: Path,
    argv: list[str],
    prog_name: str,
) -> int:
    """Helper to handle restore CLI subcommand for any configured client."""
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
        "--clean",
        "--factory-reset",
        action="store_true",
        dest="factory_reset",
        help="Reset configuration to clean factory defaults without prompting",
    )
    parser.add_argument(
        "--lang",
        type=str,
        default=None,
        help=t("cli_help_lang"),
    )
    args = parser.parse_args(argv)
    target = args.path

    cfg = None
    for c in list_configurators():
        if c.display_name == client_name or c.name == client_name:
            cfg = c
            break

    if args.factory_reset:
        if cfg is not None and cfg.factory_reset(config_path=target):
            print(t("restore_factory_reset_success", client_name=client_name))
            print(t("restore_client_ready", client_name=client_name, target=target))
            return 0
        print(f"Error: Failed to perform factory reset for {client_name}")
        return 1

    if args.backup is not None:
        try:
            restored = restore_backup(target, backup_path=args.backup)
            if client_name == "Gentle Shell":
                restore_gentle_shell(config_path=target, backup_path=args.backup)
            elif client_name == "Pi":
                restore_pi(config_path=target, backup_path=args.backup)
            print(t("restore_restored_from", name=restored.name))
            print(t("restore_client_ready", client_name=client_name, target=target))
            return 0
        except FileNotFoundError as exc:
            print(f"Error: {exc}")
            return 1

    backups = list_backups(target)
    if not backups:
        if cfg is not None and target.exists() and target.is_file():
            if cfg.restore(config_path=target):
                print(t("restore_client_ready", client_name=client_name, target=target))
                return 0
        print(t("restore_no_backups", client_name=client_name, parent=target.parent))
        return 1

    if args.latest:
        restored = restore_backup(target, backup_path=backups[0])
        if client_name == "Gentle Shell":
            restore_gentle_shell(config_path=target, backup_path=backups[0])
        elif client_name == "Pi":
            restore_pi(config_path=target, backup_path=backups[0])
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
    print(f"  [0] {t('restore_factory_reset_option')}")

    count = len(backups)
    range_str = f"0-{count}"
    prompt_str = t("restore_prompt", range_str=range_str)

    try:
        choice = input(prompt_str).strip()
    except (EOFError, KeyboardInterrupt):
        print("\n" + t("restore_cancelled"))
        return 0

    if choice.lower() in ("q", "quit", "cancel"):
        print(t("restore_cancelled"))
        return 0

    if choice == "0":
        if cfg is not None and cfg.factory_reset(config_path=target):
            print("\n" + t("restore_factory_reset_success", client_name=client_name))
            print(t("restore_client_ready", client_name=client_name, target=target))
            return 0
        print(t("restore_invalid_choice"))
        return 1

    if not choice:
        selected_index = 0
    elif choice.isdigit() and 1 <= int(choice) <= count:
        selected_index = int(choice) - 1
    else:
        print(t("restore_invalid_choice"))
        return 1

    restored = restore_backup(target, backup_path=backups[selected_index])
    if client_name == "Gentle Shell":
        restore_gentle_shell(config_path=target, backup_path=backups[selected_index])
    elif client_name == "Pi":
        restore_pi(config_path=target, backup_path=backups[selected_index])
    print("\n" + t("restore_restored_from", name=restored.name))
    print(t("restore_client_ready", client_name=client_name, target=target))
    return 0


def handle_setup_claude(argv: list[str], prog_base: str, setup_fn: Any = None) -> int:
    """Handles the 'setup-claude' CLI subcommand."""
    fn = setup_fn or setup_claude
    parser = argparse.ArgumentParser(
        prog=f"{prog_base} setup-claude",
        description="Configure Claude Code settings.json for agy-model-bridge gateway.",
    )
    parser.add_argument("--port", type=int, default=None, help="Gateway port (default: 24980)")
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
        default=None,
        help="Gateway auth token (default: persistent key)",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Path to Claude settings.json (default: ~/.claude/settings.json)",
    )
    parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
    args = parser.parse_args(argv)
    target = fn(
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


def handle_setup_codex(argv: list[str], prog_base: str, setup_fn: Any = None) -> int:
    """Handles the 'setup-codex' CLI subcommand."""
    fn = setup_fn or setup_codex
    parser = argparse.ArgumentParser(
        prog=f"{prog_base} setup-codex",
        description="Configure Codex CLI config.toml for agy-model-bridge gateway.",
    )
    parser.add_argument("--port", type=int, default=None, help="Gateway port (default: 24980)")
    parser.add_argument(
        "--model",
        type=str,
        default="gemini-3.8-flash-high",
        help="Default model identifier (default: gemini-3.8-flash-high, also supports claude-sonnet-5-5-high, claude-opus-5-5-high, etc.)",
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
        default=None,
        help="Gateway auth token (default: persistent key)",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Path to Codex config.toml (default: ~/.codex/config.toml)",
    )
    parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
    args = parser.parse_args(argv)
    target = fn(
        config_path=args.path,
        base_url=args.base_url,
        port=args.port,
        model=args.model,
        auth_token=args.auth_token,
    )
    if getattr(target, "backup_path", None):
        print(t("setup_backup_label", path=target.backup_path))
    print(t("setup_codex_success", target=target))
    print(t("setup_codex_auto_read"))
    print(t("setup_codex_run_hint"))
    return 0


def handle_setup_hermes(argv: list[str], prog_base: str, setup_fn: Any = None) -> int:
    """Handles the 'setup-hermes' CLI subcommand."""
    fn = setup_fn or setup_hermes
    parser = argparse.ArgumentParser(
        prog=f"{prog_base} setup-hermes",
        description="Configure Hermes Agent config.yaml for agy-model-bridge gateway.",
    )
    parser.add_argument("--port", type=int, default=None, help="Gateway port (default: 24980)")
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
        default=None,
        help="Gateway auth token (default: persistent key)",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Path to Hermes config.yaml (default: ~/.hermes/config.yaml)",
    )
    parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
    args = parser.parse_args(argv)
    target = fn(
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


def handle_setup_opencode(argv: list[str], prog_base: str, setup_fn: Any = None) -> int:
    """Handles the 'setup-opencode' CLI subcommand."""
    fn = setup_fn or setup_opencode
    parser = argparse.ArgumentParser(
        prog=f"{prog_base} setup-opencode",
        description="Configure OpenCode for agy-model-bridge gateway.",
    )
    parser.add_argument("--port", type=int, default=None, help="Gateway port (default: 24980)")
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
        default=None,
        help="Gateway auth token (default: persistent key)",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Path to OpenCode config (default: ~/.config/opencode/opencode.json)",
    )
    parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
    args = parser.parse_args(argv)
    target = fn(
        config_path=args.path,
        base_url=args.base_url,
        port=args.port,
        model=args.model,
        auth_token=args.auth_token,
    )
    if getattr(target, "backup_path", None):
        print(t("setup_backup_label", path=target.backup_path))
    print(t("setup_opencode_success", target=target))
    print(t("setup_opencode_auto_read"))
    print(t("setup_opencode_run_hint"))
    return 0


def handle_setup_openclaw(argv: list[str], prog_base: str, setup_fn: Any = None) -> int:
    """Handles the 'setup-openclaw' CLI subcommand."""
    fn = setup_fn or setup_openclaw
    parser = argparse.ArgumentParser(
        prog=f"{prog_base} setup-openclaw",
        description="Configure OpenClaw for agy-model-bridge gateway.",
    )
    parser.add_argument("--port", type=int, default=None, help="Gateway port (default: 24980)")
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
        default=None,
        help="Gateway auth token (default: persistent key)",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help=f"Path to OpenClaw config (default: {get_configurator('openclaw').default_config_path})",
    )
    parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
    args = parser.parse_args(argv)
    target = fn(
        config_path=args.path,
        base_url=args.base_url,
        port=args.port,
        model=args.model,
        auth_token=args.auth_token,
    )
    if getattr(target, "backup_path", None):
        print(t("setup_backup_label", path=target.backup_path))
    print(t("setup_openclaw_success", target=target))
    print(t("setup_openclaw_auto_read"))
    print(t("setup_openclaw_run_hint"))
    return 0


def handle_setup_cursor(argv: list[str], prog_base: str, setup_fn: Any = None) -> int:
    """Handles the 'setup-cursor' CLI subcommand."""
    fn = setup_fn or setup_cursor
    parser = argparse.ArgumentParser(
        prog=f"{prog_base} setup-cursor",
        description="Guide for configuring Cursor to use agy-model-bridge gateway.",
    )
    parser.add_argument("--port", type=int, default=None, help="Gateway port (default: 24980)")
    parser.add_argument(
        "--url",
        "--base-url",
        dest="base_url",
        type=str,
        default=None,
        help="Gateway base URL override (with /v1)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gemini-3.8-flash-high",
        help="Default model identifier (default: gemini-3.8-flash-high)",
    )
    parser.add_argument(
        "--token",
        "--auth-token",
        dest="auth_token",
        type=str,
        default=None,
        help="Gateway auth token (default: persistent key)",
    )
    parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
    args = parser.parse_args(argv)

    res = fn(
        base_url=args.base_url,
        port=args.port,
        model=args.model,
        lang=args.lang,
        auth_token=args.auth_token,
    )

    print(t("setup_cursor_title"))
    print(t("setup_cursor_notice"))
    print(t("setup_cursor_step1", url=res["url"]))
    print(t("setup_cursor_step2", url=res["url"]))
    print(t("setup_cursor_step3", api_key=res["apiKey"]))
    model_names = [res["model"]] + [
        m
        for m in (
            "gemini-3.8-flash-high",
            "claude-sonnet-5-5-high",
            "claude-opus-5-5-high",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
        )
        if m != res["model"]
    ]
    models_str = ", ".join(model_names)
    print(t("setup_cursor_step4", models=models_str))
    return 0


def handle_setup_pi(argv: list[str], prog_base: str, setup_fn: Any = None) -> int:
    """Handles the 'setup-pi' CLI subcommand."""
    fn = setup_fn or setup_pi
    parser = argparse.ArgumentParser(
        prog=f"{prog_base} setup-pi",
        description="Configure Pi for agy-model-bridge gateway.",
    )
    parser.add_argument("--port", type=int, default=None, help="Gateway port (default: 24980)")
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
        default=None,
        help="Gateway auth token (default: persistent key)",
    )
    parser.add_argument(
        "--set-default",
        action="store_true",
        help="Set agy as defaultProvider and model as defaultModel in settings.json",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help=f"Path to Pi models.json (default: {get_configurator('pi').default_config_path})",
    )
    parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
    args = parser.parse_args(argv)
    target = fn(
        config_path=args.path,
        base_url=args.base_url,
        port=args.port,
        model=args.model,
        auth_token=args.auth_token,
        set_default=args.set_default,
    )
    if getattr(target, "backup_path", None):
        print(t("setup_backup_label", path=target.backup_path))
    print(t("setup_pi_success", target=target))
    print(t("setup_pi_auto_read"))
    print(t("setup_pi_run_hint"))
    if not args.set_default:
        print(t("setup_pi_set_default_tip"))
    else:
        print(t("setup_pi_set_default_done"))
    return 0


def handle_setup_gentle_shell(
    argv: list[str],
    prog_base: str,
    subcmd: str,
    setup_fn: Any = None,
) -> int:
    """Handles 'setup-gentle-shell' and 'setup-gentle' CLI subcommands."""
    fn = setup_fn or setup_gentle_shell
    parser = argparse.ArgumentParser(
        prog=f"{prog_base} {subcmd}",
        description="Configure Gentle Shell for agy-model-bridge gateway.",
    )
    parser.add_argument("--port", type=int, default=None, help="Gateway port (default: 24980)")
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
        default=None,
        help="Gateway auth token (default: persistent key)",
    )
    parser.add_argument(
        "--set-default",
        action="store_true",
        help="Set agy as defaultProvider and model as defaultModel in settings.json",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help=f"Path to Gentle Shell models.json (default: {get_configurator('gentle-shell').default_config_path})",
    )
    parser.add_argument(
        "--provider",
        choices=["agy", "freellmapi"],
        default="agy",
        help="Provider to configure (default: agy)",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="API key for provider",
    )
    parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
    args = parser.parse_args(argv)

    if args.provider == "freellmapi" and not args.api_key:
        print("Error: --api-key is required when configuring FreeLLMAPI.")
        return 1

    target = fn(
        config_path=args.path,
        base_url=args.base_url,
        port=args.port,
        model=args.model,
        auth_token=args.auth_token,
        set_default=args.set_default,
        provider=args.provider,
        api_key=args.api_key,
    )
    if getattr(target, "backup_path", None):
        print(t("setup_backup_label", path=target.backup_path))
    print(t("setup_gentle_shell_success", target=target))
    print(t("setup_gentle_shell_auto_read"))
    print(t("setup_gentle_shell_run_hint"))
    if not args.set_default:
        print(t("setup_gentle_shell_set_default_tip"))
    else:
        print(t("setup_gentle_shell_set_default_done"))
    return 0
