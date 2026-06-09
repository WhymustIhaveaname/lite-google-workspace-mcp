import argparse
import logging
import sys
import tomllib

from workspace_mcp_lite.auth import CONFIG_DIR, run_auth_flow


def _load_account_port(account: str) -> int | None:
    config_path = CONFIG_DIR / "config.toml"
    if not config_path.exists():
        return None
    with open(config_path, "rb") as f:
        config = tomllib.load(f)
    return config.get("accounts", {}).get(account, {}).get("port")


def cmd_auth(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    account = args.account
    print(f"Starting OAuth flow for account '{account}'...")
    email = run_auth_flow(account)
    print(f"Authenticated as {email}. Token saved for account '{account}'.")


def cmd_serve(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    account = args.account
    port = args.port or _load_account_port(account)
    if port is None:
        print(
            f"Error: No port specified. Use --port or set it in {CONFIG_DIR}/config.toml",
            file=sys.stderr,
        )
        sys.exit(1)

    from workspace_mcp_lite.server import create_server

    server = create_server(account, port)
    server.run(transport="streamable-http")


def main() -> None:
    parser = argparse.ArgumentParser(prog="workspace-mcp-lite")
    sub = parser.add_subparsers(dest="command", required=True)

    auth_parser = sub.add_parser("auth", help="Authorize a Google account")
    auth_parser.add_argument("account", help="Account name (e.g. syouran0508)")

    serve_parser = sub.add_parser("serve", help="Start the MCP server")
    serve_parser.add_argument("--account", required=True, help="Account name")
    serve_parser.add_argument("--port", type=int, default=None, help="Port to listen on")

    args = parser.parse_args()
    if args.command == "auth":
        cmd_auth(args)
    elif args.command == "serve":
        cmd_serve(args)


if __name__ == "__main__":
    main()
