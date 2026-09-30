"""CLI runner for Antigravity Model Bridge."""

import argparse
import sys
from pathlib import Path

from bridge.server import run_server
from bridge.setup import setup_claude, setup_codex


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
            help="Gateway port (default: 8080)",
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
        print(f"Claude Code configured successfully at {target}")
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
            help="Gateway port (default: 8080)",
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
        print(f"Codex CLI configured successfully at {target}")
        return 0

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
        default=8080,
        help="Port number to bind server (default: 8080)",
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
