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
from bridge.server import run_server
from bridge.setup import (
    describe_backup,
    list_backups,
    restore_backup,
    setup_claude,
    setup_codex,
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
        tag = describe_backup(b)
        tag_str = f"  [{tag}]"
        if i == 1:
            print(f"  [{i}] {b.name}{tag_str}  <-- Anterior inmediata")
        else:
            print(f"  [{i}] {b.name}{tag_str}")

    count = len(backups)
    range_str = f"1-{count}" if count > 1 else "1"
    prompt_str = f"\nIngrese un número ({range_str}), presione Enter para [1], o 'q' para cancelar: "

    try:
        choice = input(prompt_str).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nOperación cancelada.")
        return 0

    if choice.lower() in ("q", "quit", "cancel"):
        print("Operación cancelada.")
        return 0

    if not choice:
        selected_index = 0
    elif choice.isdigit() and 1 <= int(choice) <= count:
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
        args = parser.parse_args(argv[1:])

        res = update_installation(
            core_dir=args.core_dir,
            restart_daemon_if_running=not args.no_restart,
        )
        status = res.get("status")
        ver = res.get("version", __version__)
        if status == "updated":
            print(f"✔ Repositorio actualizado a la versión v{ver}.")
            if res.get("restarted_daemon"):
                print("✔ Servicio en segundo plano reiniciado con el nuevo código.")
            return 0
        elif status == "already_up_to_date":
            print(f"✔ Ya tenés la versión más reciente (v{ver}).")
            return 0
        else:
            print(f"Error: {res.get('message', 'Fallo al actualizar el repositorio')}")
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
            browser_hint = " (abierto en el navegador)" if res.get("opened_browser") else ""
            print(f"✔ AGY Model Bridge corriendo en segundo plano (PID {res['pid']})")
            print(f"➜ Dashboard: {res['url']}{browser_hint}")
            print(f"➜ Para detener el servicio: {prog_base} stop")
            return 0
        elif st == "already_running":
            pid_str = f" (PID {res['pid']})" if res.get("pid") else ""
            print(f"AGY Model Bridge ya está corriendo{pid_str}")
            print(f"➜ Dashboard: {res['url']}")
            print(f"➜ Para detener el servicio: {prog_base} stop")
            return 0
        else:
            print(f"Error: {res.get('error', 'Fallo al iniciar el daemon')}")
            return 1

    if argv and argv[0] == "stop":
        parser = argparse.ArgumentParser(
            prog=f"{prog_base} stop",
            description="Stop the running background AGY Model Bridge daemon.",
        )
        parser.add_argument("--port", type=int, default=24980, help="Gateway port (default: 24980)")
        parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address (default: 127.0.0.1)")
        args = parser.parse_args(argv[1:])
        res = stop_daemon(port=args.port, host=args.host)
        if res.get("status") == "stopped":
            pid_str = f" (PID {res['pid']})" if res.get("pid") else ""
            print(f"✔ AGY Model Bridge detenido{pid_str}")
        else:
            print("AGY Model Bridge no está corriendo.")
        return 0

    if argv and argv[0] == "status":
        parser = argparse.ArgumentParser(
            prog=f"{prog_base} status",
            description="Check the status of the AGY Model Bridge daemon.",
        )
        parser.add_argument("--port", type=int, default=24980, help="Gateway port (default: 24980)")
        parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address (default: 127.0.0.1)")
        args = parser.parse_args(argv[1:])
        st = get_daemon_status(port=args.port, host=args.host)
        if st.get("running"):
            auth_st = st.get("auth", {}).get("status", "Valid")
            pid_str = f" (PID {st['pid']})" if st.get("pid") else ""
            print(f"✔ Estado: Activo{pid_str}")
            print(f"➜ Dirección: {st['url']}")
            print(f"➜ Modelos disponibles: {st.get('models_count', 0)}")
            print(f"➜ Autenticación Keychain: {auth_st}")
        else:
            print("Estado: Detenido")
            print(f"Ejecute '{prog_base} start' para iniciar el servicio en segundo plano.")
        return 0

    if argv and argv[0] in ("dashboard", "open"):
        parser = argparse.ArgumentParser(
            prog=f"{prog_base} {argv[0]}",
            description="Open the AGY Model Bridge local dashboard in the default browser.",
        )
        parser.add_argument("--port", type=int, default=24980, help="Gateway port (default: 24980)")
        parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address (default: 127.0.0.1)")
        args = parser.parse_args(argv[1:])
        st = get_daemon_status(port=args.port, host=args.host)
        if not st.get("running"):
            print(f"Aviso: El bridge no parece estar activo en {st['url']}")
            print(f"Ejecute '{prog_base} start' para iniciarlo.")
        print(f"Abriendo dashboard en {st['url']}...")
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
        args = parser.parse_args(argv[1:])

        if not args.yes:
            try:
                confirm = input("¿Estás seguro de que deseas desinstalar AGY Model Bridge? [s/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nOperación de desinstalación cancelada.")
                return 0

            if confirm not in ("s", "si", "sí", "y", "yes"):
                print("Operación de desinstalación cancelada.")
                return 0

        res = uninstall(
            restore_configs=not args.keep_configs,
            purge_backups=args.purge,
        )

        print("✔ AGY Model Bridge desinstalado correctamente.")
        if res.get("daemon_stopped"):
            print("  - Servicio en segundo plano detenido.")
        if res.get("binaries_removed"):
            print(f"  - Binarios eliminados: {', '.join(res['binaries_removed'])}")
        if res.get("daemon_dir_removed"):
            print("  - Directorio ~/.agy-bridge eliminado.")
        if res.get("claude_restored"):
            print("  - Configuración de Claude Code restaurada.")
        if res.get("codex_restored"):
            print("  - Configuración de Codex CLI restaurada.")
        if res.get("backups_purged"):
            print("  - Historial de backups purgado.")
        return 0

    # Fallback to daemon server runner
    parser = argparse.ArgumentParser(
        prog=prog_base,
        description="Antigravity Model Bridge - Local AI Gateway",
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
