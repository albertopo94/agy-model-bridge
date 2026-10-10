"""Lifecycle management utilities (uninstall and in-place update) for agy-model-bridge."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

from bridge import __version__
import bridge.daemon
from bridge.i18n import t
from bridge.setup.base import ClientConfigurator, list_configurators


def uninstall(
    daemon_dir: Path | None = None,
    bin_dir: Path | None = None,
    configurators: list[ClientConfigurator] | None = None,
    custom_config_paths: dict[str, Path] | None = None,
    restore_configs: bool = True,
    purge_backups: bool = False,
    claude_settings_path: Path | None = None,
    codex_config_path: Path | None = None,
    hermes_config_path: Path | None = None,
    opencode_config_path: Path | None = None,
    openclaw_config_path: Path | None = None,
    pi_config_path: Path | None = None,
    gentle_shell_config_path: Path | None = None,
) -> dict[str, Any]:
    """Uninstalls Antigravity Model Bridge and optionally restores client configurations.

    Args:
        daemon_dir: Path to daemon directory (default: ~/.agy-bridge).
        bin_dir: Path to launcher binary directory (default: ~/.local/bin).
        configurators: Optional list of ClientConfigurators to handle (defaults to all registered).
        custom_config_paths: Optional mapping of client name to custom config Path.
        restore_configs: Whether to restore client configurations.
        purge_backups: Whether to delete historical configuration backups.
        claude_settings_path: Backward-compatible override for Claude settings.json path.
        codex_config_path: Backward-compatible override for Codex config.toml path.
        hermes_config_path: Backward-compatible override for Hermes config.yaml path.
        opencode_config_path: Backward-compatible override for OpenCode opencode.json path.
        openclaw_config_path: Backward-compatible override for OpenClaw openclaw.json path.
        pi_config_path: Backward-compatible override for Pi models.json path.
        gentle_shell_config_path: Backward-compatible override for Gentle Shell models.json path.

    Returns:
        Structured dictionary reporting actions performed:
        {
            "daemon_stopped": bool,
            "claude_restored": bool,
            "codex_restored": bool,
            "hermes_restored": bool,
            "opencode_restored": bool,
            "openclaw_restored": bool,
            "pi_restored": bool,
            "gentle_shell_restored": bool,
            "restored_clients": dict[str, bool],
            "binaries_removed": list[str],
            "daemon_dir_removed": bool,
            "backups_purged": bool,
        }
    """
    default_daemon = Path(os.environ.get("AGY_BRIDGE_STATE_DIR", Path.home() / ".agy-bridge"))
    resolved_daemon_dir = Path(daemon_dir) if daemon_dir is not None else default_daemon
    if bin_dir is not None:
        resolved_bin_dir = Path(bin_dir)
    elif os.environ.get("AGY_BRIDGE_BIN"):
        resolved_bin_dir = Path(os.environ["AGY_BRIDGE_BIN"])
    else:
        resolved_bin_dir = Path.home() / ".local" / "bin"
    core_dir_env = os.environ.get("AGY_BRIDGE_CORE_DIR")
    resolved_core_dir = Path(core_dir_env) if core_dir_env else None

    # 1. Stop daemon if running
    pid_file = resolved_daemon_dir / "bridge.pid"
    stop_result = bridge.daemon.stop_daemon(pid_file=pid_file)
    daemon_stopped = stop_result.get("status") == "stopped"

    # 2. Determine configurators and paths
    active_configurators = list(configurators) if configurators is not None else list_configurators()
    paths_map: dict[str, Path] = {}
    if custom_config_paths:
        paths_map.update(custom_config_paths)
    if claude_settings_path is not None:
        paths_map["claude"] = Path(claude_settings_path)
    if codex_config_path is not None:
        paths_map["codex"] = Path(codex_config_path)
    if hermes_config_path is not None:
        paths_map["hermes"] = Path(hermes_config_path)
    if opencode_config_path is not None:
        paths_map["opencode"] = Path(opencode_config_path)
    if openclaw_config_path is not None:
        paths_map["openclaw"] = Path(openclaw_config_path)
    if pi_config_path is not None:
        paths_map["pi"] = Path(pi_config_path)
    if gentle_shell_config_path is not None:
        paths_map["gentle-shell"] = Path(gentle_shell_config_path)

    # 3. Restore or surgically clean client configurations & purge backups if requested
    restored_clients: dict[str, bool] = {}
    for cfg in active_configurators:
        target_path = cfg.get_config_path(paths_map.get(cfg.name))
        if restore_configs:
            restored = cfg.restore(config_path=target_path)
        else:
            restored = False
        restored_clients[cfg.name] = restored

        if purge_backups:
            cfg.purge_backups(config_path=target_path)

    backups_purged = bool(purge_backups)

    # 4. Remove launcher scripts
    binaries_removed: list[str] = []
    for binary_name in ("agy-bridge", "agy-model-bridge"):
        target_bin = resolved_bin_dir / binary_name
        if target_bin.exists() or target_bin.is_symlink():
            try:
                target_bin.unlink()
                binaries_removed.append(str(target_bin))
            except OSError:
                pass

    # 5. Remove daemon and core directory
    daemon_dir_removed = False
    if resolved_daemon_dir.exists():
        try:
            real_daemon = resolved_daemon_dir.resolve()
            real_home = Path.home().resolve()
            real_cwd = Path.cwd().resolve()
            real_root = Path("/").resolve()

            if (
                real_daemon != real_home
                and real_daemon != real_cwd
                and real_daemon != real_root
            ):
                if resolved_daemon_dir.is_dir():
                    # Surgically remove only known bridge artifacts
                    known_bridge_files = {
                        "bridge.pid",
                        "bridge.lock",
                        "bridge.log",
                        "bridge.json",
                        "api_key",
                        ".core_dir",
                    }
                    for item_name in known_bridge_files:
                        target_file = resolved_daemon_dir / item_name
                        if target_file.is_file() or target_file.is_symlink():
                            try:
                                target_file.unlink()
                            except OSError:
                                pass

                    # Remove internal core directory only if it has the installed marker
                    core_sub = resolved_daemon_dir / "core"
                    if core_sub.is_dir():
                        try:
                            if (core_sub / ".agy-bridge-installed").is_file():
                                shutil.rmtree(core_sub)
                        except OSError:
                            pass

                    # Attempt to remove state dir only if it is completely empty
                    try:
                        resolved_daemon_dir.rmdir()
                        daemon_dir_removed = True
                    except OSError:
                        daemon_dir_removed = False
                else:
                    resolved_daemon_dir.unlink()
                    daemon_dir_removed = True
        except OSError:
            daemon_dir_removed = False

    if resolved_core_dir is not None and resolved_core_dir.exists():
        try:
            real_core = resolved_core_dir.resolve()
            real_daemon = resolved_daemon_dir.resolve()
            real_home = Path.home().resolve()
            real_cwd = Path.cwd().resolve()
            real_root = Path("/").resolve()
            if (
                real_core != real_daemon
                and real_core != real_home
                and real_core != real_cwd
                and real_core != real_root
            ):
                if resolved_core_dir.is_dir():
                    # Only delete core dir if it was explicitly marked as installed by agy-bridge
                    # Never delete active dev repositories with bridge/__init__.py!
                    if (resolved_core_dir / ".agy-bridge-installed").is_file():
                        shutil.rmtree(resolved_core_dir)
                else:
                    resolved_core_dir.unlink()
        except OSError:
            pass

    return {
        "daemon_stopped": daemon_stopped,
        "claude_restored": restored_clients.get("claude", False),
        "codex_restored": restored_clients.get("codex", False),
        "hermes_restored": restored_clients.get("hermes", False),
        "opencode_restored": restored_clients.get("opencode", False),
        "openclaw_restored": restored_clients.get("openclaw", False),
        "pi_restored": restored_clients.get("pi", False),
        "gentle_shell_restored": restored_clients.get("gentle-shell", False),
        "restored_clients": restored_clients,
        "binaries_removed": binaries_removed,
        "daemon_dir_removed": daemon_dir_removed,
        "backups_purged": backups_purged,
    }


def _get_installed_version(target_dir: Path | None = None) -> str:
    """Reads the installed version from target_dir/bridge/__init__.py or falls back to __version__."""
    if target_dir is not None:
        init_file = target_dir / "bridge" / "__init__.py"
        if init_file.is_file():
            try:
                match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', init_file.read_text(encoding="utf-8"))
                if match:
                    return match.group(1)
            except OSError:
                pass
    return __version__


def update_installation(
    core_dir: Path | None = None,
    restart_daemon_if_running: bool = True,
) -> dict[str, Any]:
    """Updates the AGY Model Bridge installation in-place via git pull.

    Discovers core repo location:
    If core_dir is None: checks Path.home() / ".agy-bridge" / "core".
    If that does not exist or lacks .git, falls back to checking current working directory / repo parent.

    Runs git -C <dir> pull --ff-only.
    Detects if changes were pulled or if already up to date.
    If restart_daemon_if_running and changes were pulled:
      Checks if daemon is currently running via bridge.daemon.read_pid() and bridge.daemon.is_pid_alive().
      If running: calls bridge.daemon.stop_daemon(), then bridge.daemon.start_daemon(no_open=True).

    Returns:
        dict[str, Any]: {
            "status": "updated" | "already_up_to_date" | "error",
            "message": str,
            "restarted_daemon": bool,
            "version": str,
        }
    """
    target_dir: Path | None = None
    if core_dir is not None:
        target_dir = Path(core_dir)
    elif os.environ.get("AGY_BRIDGE_CORE_DIR"):
        target_dir = Path(os.environ["AGY_BRIDGE_CORE_DIR"])
    else:
        state_dir_env = os.environ.get("AGY_BRIDGE_STATE_DIR")
        base_state = Path(state_dir_env) if state_dir_env else Path.home() / ".agy-bridge"
        persisted_core = base_state / ".core_dir"
        if persisted_core.is_file():
            try:
                candidate = persisted_core.read_text(encoding="utf-8").strip()
                target_dir = Path(candidate) if candidate else None
            except OSError:
                target_dir = None
        else:
            target_dir = None

        if target_dir is None:
            default_dir = base_state / "core"
            if (default_dir / ".git").exists():
                target_dir = default_dir
            elif (Path.cwd() / ".git").exists():
                target_dir = Path.cwd()
            else:
                repo_root = Path(__file__).resolve().parents[2]
                if (repo_root / ".git").exists():
                    target_dir = repo_root
                else:
                    target_dir = default_dir

    if target_dir is None or not target_dir.exists() or not (target_dir / ".git").exists():
        return {
            "status": "error",
            "message": t("update_not_git_repo", target_dir=target_dir or Path("")),
            "restarted_daemon": False,
            "version": _get_installed_version(target_dir) if target_dir is not None else "",
        }

    cmd = ["git", "-C", str(target_dir), "pull", "--ff-only"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return {
            "status": "error",
            "message": t("update_git_not_found"),
            "restarted_daemon": False,
            "version": _get_installed_version(target_dir),
        }
    except OSError as exc:
        return {
            "status": "error",
            "message": t("update_git_error", exc=exc),
            "restarted_daemon": False,
            "version": _get_installed_version(target_dir),
        }

    if res.returncode != 0:
        err_msg = res.stderr.strip() or res.stdout.strip() or f"git pull falló con código {res.returncode}"
        return {
            "status": "error",
            "message": err_msg,
            "restarted_daemon": False,
            "version": _get_installed_version(target_dir),
        }

    new_ver = _get_installed_version(target_dir)
    installed_marker = target_dir / ".agy-bridge-installed"
    if installed_marker.is_file():
        try:
            from bridge.security import write_secret_file
            write_secret_file(installed_marker, f"{new_ver}\n", mode=0o600)
        except OSError as err:
            sys.stderr.write(f"Warning: could not update marker file: {err}\n")

    stdout_lower = res.stdout.lower()
    is_up_to_date = "already up to date" in stdout_lower or "already up-to-date" in stdout_lower

    pid = bridge.daemon.read_pid()
    running_daemon_outdated = False
    if pid is not None and bridge.daemon.is_pid_alive(pid):
        info = bridge.daemon.read_daemon_info()
        eff_host = info.get("host", "127.0.0.1") if info else "127.0.0.1"
        eff_port = info.get("port", 24980) if info else 24980
        status_data = bridge.daemon.fetch_status_json(eff_host, eff_port, timeout=1.0) or {}
        running_ver = status_data.get("version")
        if running_ver and running_ver != new_ver:
            running_daemon_outdated = True

    if is_up_to_date and not (restart_daemon_if_running and running_daemon_outdated):
        return {
            "status": "already_up_to_date",
            "message": t("update_up_to_date"),
            "restarted_daemon": False,
            "version": new_ver,
        }

    restarted_daemon = False
    if restart_daemon_if_running:
        if pid is not None and bridge.daemon.is_pid_alive(pid):
            bridge.daemon.stop_daemon()
            if info:
                start_res = bridge.daemon.start_daemon(
                    no_open=True,
                    host=info.get("host", "127.0.0.1"),
                    port=info.get("port", 24980),
                    project=info.get("project"),
                    base_url=info.get("base_url"),
                    no_auth=info.get("no_auth", False),
                )
            else:
                start_res = bridge.daemon.start_daemon(no_open=True)
            if start_res.get("status") == "started":
                restarted_daemon = True

    return {
        "status": "already_up_to_date" if is_up_to_date else "updated",
        "message": t("update_up_to_date") if is_up_to_date else t("update_completed"),
        "restarted_daemon": restarted_daemon,
        "version": new_ver,
    }
