"""CLI runner for Antigravity Model Bridge."""

import argparse
import sys
from pathlib import Path

from bridge.server import run_server
from bridge.setup import list_backups, restore_backup, setup_claude, setup_codex


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
    args = parser.parse_args(argv)
    target = args.path

    if args.backup is not None:
        try:
            restored = restore_backup(target, backup_path=args.backup)
            print(f"Restaurada configuración desde: {restored.name}")
            print(f"{client_name} listo en {target}")
            return 0
        except FileNotFoundError as exc:
            print(f"Error: {exc}")
            return 1

    backups = list_backups(target)
    if not backups:
        print(f"No se encontraron backups para {client_name} en {target.parent}")
        return 1

    if args.latest:
        restored = restore_backup(target, backup_path=backups[0])
        print(f"Restaurada configuración desde: {restored.name}")
        print(f"{client_name} listo en {target}")
        return 0

    print(f"\nBackups disponibles para {client_name}:")
    for i, b in enumerate(backups, 1):
        if i == 1:
            print(f"  [{i}] {b.name}  <-- Anterior inmediata (Presione Enter para seleccionar)")
        else:
            print(f"  [{i}] {b.name}")

    try:
        choice = input("\nSeleccione una opción [1]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nOperación cancelada.")
        return 1

    if not choice:
        selected_index = 0
    elif choice.isdigit() and 1 <= int(choice) <= len(backups):
        selected_index = int(choice) - 1
    else:
        print("Opción inválida.")
        return 1

    restored = restore_backup(target, backup_path=backups[selected_index])
    print(f"\nRestaurada configuración desde: {restored.name}")
    print(f"{client_name} listo en {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for agy-model-bridge daemon and client setup subcommands."""
    if argv is None:
        argv = sys.argv[1:]

    prog_base = Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "agy-bridge"
    if prog_base.endswith(".py"):
        prog_base = "python3 -m bridge"

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
        args = parser.parse_args(argv[1:])
        target = setup_claude(
            settings_path=args.path,
            base_url=args.base_url,
            port=args.port,
            model=args.model,
            auth_token=args.auth_token,
        )
        if getattr(target, "backup_path", None):
            print(f"Backup: {target.backup_path}")
        print(f"Claude Code configured successfully at {target}\n")
        print("Claude Code will read this configuration automatically.")
        print("Run 'claude' to start coding with Gemini 3.8 Flash · high (1M context).")
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
        args = parser.parse_args(argv[1:])
        target = setup_codex(
            config_path=args.path,
            base_url=args.base_url,
            port=args.port,
            model=args.model,
        )
        if getattr(target, "backup_path", None):
            print(f"Backup: {target.backup_path}")
        print(f"Codex CLI configured successfully at {target}\n")
        print("Codex CLI will read this configuration automatically.")
        print("Run 'codex' to start coding with Gemini 3.8 Flash · high (1M context).")
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

    # Fallback to daemon server runner
    parser = argparse.ArgumentParser(
        prog=prog_base,
        description="Antigravity Model Bridge - Local AI Gateway",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host address to bind server (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=24980,
        help="Port number to bind server (default: 24980)",
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help="Google Cloud project ID override",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="Upstream Google Cloud Code Assist base URL override",
    )
    args = parser.parse_args(argv)
    run_server(host=args.host, port=args.port, project=args.project, base_url=args.base_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
