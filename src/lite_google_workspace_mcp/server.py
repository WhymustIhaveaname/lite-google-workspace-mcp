import logging

from googleapiclient.discovery import build
from mcp.server.fastmcp import FastMCP

from lite_google_workspace_mcp.auth import TokenManager
from lite_google_workspace_mcp.calendar import register_calendar_tools
from lite_google_workspace_mcp.gmail import register_gmail_tools

logger = logging.getLogger(__name__)


def create_server(account: str, port: int) -> FastMCP:
    manager = TokenManager()
    creds = manager.build_credentials(account)
    if creds is None:
        raise RuntimeError(
            f"No credentials for account '{account}'. "
            f"Run: lite-google-workspace-mcp auth {account}"
        )

    manager.refresh_if_needed(creds, account)

    gmail_service = build("gmail", "v1", credentials=creds)
    calendar_service = build("calendar", "v3", credentials=creds)

    server = FastMCP(
        name=f"workspace-mcp-{account}",
        host="127.0.0.1",
        port=port,
    )

    register_gmail_tools(server, gmail_service)
    register_calendar_tools(server, calendar_service)

    logger.info("Registered 21 tools for account '%s' on port %d", account, port)
    return server
