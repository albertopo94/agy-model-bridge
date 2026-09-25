"""CLI runner for Antigravity Model Bridge."""

import argparse
from bridge.server import run_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Antigravity Model Bridge")
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
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, project=args.project, base_url=args.base_url)


if __name__ == "__main__":
    main()
