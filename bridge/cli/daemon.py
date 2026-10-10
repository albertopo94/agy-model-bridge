"""CLI handlers for daemon management (start, stop, status, dashboard)."""

import argparse
from typing import Any

from bridge.daemon import (
    get_daemon_status,
    open_dashboard,
    restart_daemon,
    start_daemon,
    stop_daemon,
)
from bridge.i18n import t


def handle_start(argv: list[str], prog_base: str, start_fn: Any = None) -> int:
    """Handles the 'start' CLI subcommand."""
    fn = start_fn or start_daemon
    parser = argparse.ArgumentParser(
        prog=f"{prog_base} start",
        description="Start AGY Model Bridge in the background as a daemon process.",
    )
    parser.add_argument("--port", type=int, default=24980, help="Gateway port (default: 24980)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--no-open", action="store_true", help="Do not open web browser automatically")
    parser.add_argument("--project", type=str, default=None, help="Google Cloud project ID override")
    parser.add_argument("--base-url", type=str, default=None, help="Upstream API base URL override")
    parser.add_argument("--api-key", type=str, default=None, help="Custom local API key")
    parser.add_argument("--no-auth", action="store_true", help="Disable local API key authentication")
    parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
    args = parser.parse_args(argv)

    res = fn(
        port=args.port,
        host=args.host,
        no_open=args.no_open,
        project=args.project,
        base_url=args.base_url,
        api_key=args.api_key,
        no_auth=args.no_auth,
    )
    st = res.get("status")
    if st == "started":
        browser_hint = t("daemon_browser_opened") if res.get("opened_browser") else ""
        print(t("daemon_running_bg", pid=res["pid"]))
        print(t("daemon_dashboard_url", url=res["url"], browser_hint=browser_hint))
        print(t("daemon_stop_hint", prog_base=prog_base))
        return 0
    elif st == "already_running":
        pid_str = f" (PID {res['pid']})" if res.get("pid") else ""
        print(t("daemon_already_running", pid_str=pid_str))
        print(t("daemon_dashboard_url", url=res["url"], browser_hint=""))
        print(t("daemon_stop_hint", prog_base=prog_base))
        return 0
    else:
        print(f"Error: {res.get('error', t('daemon_start_failed'))}")
        return 1


def handle_stop(argv: list[str], prog_base: str, stop_fn: Any = None) -> int:
    """Handles the 'stop' CLI subcommand."""
    fn = stop_fn or stop_daemon
    parser = argparse.ArgumentParser(
        prog=f"{prog_base} stop",
        description="Stop the running background AGY Model Bridge daemon.",
    )
    parser.add_argument("--port", type=int, default=None, help="Gateway port (default: auto-detect)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
    args = parser.parse_args(argv)
    res = fn(port=args.port, host=args.host)
    if res.get("status") == "stopped":
        pid_str = f" (PID {res['pid']})" if res.get("pid") else ""
        print(t("daemon_stopped", pid_str=pid_str))
        return 0
    elif res.get("status") == "port_mismatch":
        print(f"Error: {res.get('error')}")
        return 1
    elif res.get("status") == "host_mismatch":
        print(f"Error: {res.get('error')}")
        return 1
    else:
        print(t("daemon_not_running"))
        return 0


def handle_restart(argv: list[str], prog_base: str, restart_fn: Any = None) -> int:
    """Handles the 'restart' CLI subcommand."""
    fn = restart_fn or restart_daemon
    parser = argparse.ArgumentParser(
        prog=f"{prog_base} restart",
        description="Restart AGY Model Bridge daemon, preserving active configuration.",
    )
    parser.add_argument("--port", type=int, default=None, help="Gateway port (default: preserve active, or 24980)")
    parser.add_argument("--host", type=str, default=None, help="Host address (default: preserve active, or 127.0.0.1)")
    parser.add_argument("--no-open", action="store_true", help="Do not open web browser automatically")
    parser.add_argument("--project", type=str, default=None, help="Google Cloud project ID override")
    parser.add_argument("--base-url", type=str, default=None, help="Upstream API base URL override")
    parser.add_argument("--api-key", type=str, default=None, help="Custom local API key")
    parser.add_argument("--no-auth", action="store_true", default=None, help="Disable local API key authentication")
    parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
    args = parser.parse_args(argv)

    res = fn(
        port=args.port,
        host=args.host,
        no_open=args.no_open,
        project=args.project,
        base_url=args.base_url,
        api_key=args.api_key,
        no_auth=args.no_auth,
    )
    st = res.get("status")
    if st == "started":
        browser_hint = t("daemon_browser_opened") if res.get("opened_browser") else ""
        print(t("daemon_restarted", pid=res["pid"]))
        print(t("daemon_dashboard_url", url=res["url"], browser_hint=browser_hint))
        print(t("daemon_stop_hint", prog_base=prog_base))
        return 0
    else:
        print(f"Error: {res.get('error', t('daemon_start_failed'))}")
        return 1


def handle_status(argv: list[str], prog_base: str, status_fn: Any = None) -> int:
    """Handles the 'status' CLI subcommand."""
    fn = status_fn or get_daemon_status
    parser = argparse.ArgumentParser(
        prog=f"{prog_base} status",
        description="Check the status of the AGY Model Bridge daemon.",
    )
    parser.add_argument("--port", type=int, default=24980, help="Gateway port (default: 24980)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
    args = parser.parse_args(argv)
    st = fn(port=args.port, host=args.host)
    if st.get("running"):
        auth_st = st.get("auth", {}).get("status", "Valid")
        pid_str = f" (PID {st['pid']})" if st.get("pid") else ""
        print(t("status_active", pid_str=pid_str))
        print(t("status_address", url=st["url"]))
        print(t("status_models", count=st.get("models_count", 0)))
        print(t("status_auth", status=auth_st))
    else:
        print(t("status_stopped"))
        print(t("status_start_hint", prog_base=prog_base))
    return 0


def handle_dashboard(
    argv: list[str],
    prog_base: str,
    subcmd: str,
    open_fn: Any = None,
    status_fn: Any = None,
) -> int:
    """Handles the 'dashboard' and 'open' CLI subcommands."""
    do_open = open_fn or open_dashboard
    do_status = status_fn or get_daemon_status
    parser = argparse.ArgumentParser(
        prog=f"{prog_base} {subcmd}",
        description="Open the AGY Model Bridge local dashboard in the default browser.",
    )
    parser.add_argument("--port", type=int, default=24980, help="Gateway port (default: 24980)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--lang", type=str, default=None, help=t("cli_help_lang"))
    args = parser.parse_args(argv)
    st = do_status(port=args.port, host=args.host)
    if not st.get("running"):
        print(t("dashboard_not_active", url=st["url"]))
        print(t("status_start_hint", prog_base=prog_base))
    print(t("dashboard_opening", url=st["url"]))
    do_open(port=args.port, host=args.host)
    return 0
