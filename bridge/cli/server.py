"""CLI handler for running the foreground bridge server."""

import argparse
from typing import Any

from bridge import __version__
from bridge.i18n import t
from bridge.security import is_loopback_host
from bridge.server import run_server


def handle_server(argv: list[str], prog_base: str, run_server_fn: Any = None) -> int:
    """Handles foreground bridge server execution."""
    fn = run_server_fn or run_server
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
        "--api-key",
        type=str,
        default=None,
        help="Custom local API key",
    )
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Disable local API key authentication",
    )
    parser.add_argument(
        "--lang",
        type=str,
        default=None,
        help=t("cli_help_lang"),
    )
    args = parser.parse_args(argv)

    if args.no_auth and not is_loopback_host(args.host):
        print(
            f"Error: Refusing to disable authentication (--no-auth) on non-loopback host '{args.host}'. "
            "--no-auth is only permitted on loopback addresses."
        )
        return 1

    fn(
        host=args.host,
        port=args.port,
        project=args.project,
        base_url=args.base_url,
        api_key=args.api_key,
        no_auth=args.no_auth,
    )
    return 0
