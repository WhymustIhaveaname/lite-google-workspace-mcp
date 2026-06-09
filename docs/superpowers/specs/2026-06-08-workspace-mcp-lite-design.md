# workspace-mcp-lite Design Spec

Minimal MCP server for Gmail + Google Calendar, replacing the 258k-line
fastmcp + google_workspace_mcp stack with ~1500 lines of Python.

## Problem

The current setup depends on two forked repositories (fastmcp 197k lines,
google_workspace_mcp 61k lines) with a two-layer OAuth proxy
(CC bearer -> fastmcp proxy -> Google tokens). The proxy bridge has a
known bug (#775) where refresh tokens are lost after Google access token
expiry, causing recurring auth failures. The fork patches only address
bearer TTL, not the underlying refresh token propagation issue.

## Goals

1. Drop both fork repositories entirely
2. Implement all 21 existing tools (14 Gmail + 7 Calendar)
3. Single-layer Google OAuth: tokens stored locally, refreshed by google-auth
4. Browser-based OAuth flow with polished success/error pages
5. Two-port architecture: one process per Google account, no OAuth proxy
6. Unit tests, ruff, pre-commit from day one

## Architecture

### Two-port, no-auth model

Each Google account runs as a separate process on its own port.
CC registers each as an independent MCP server entry. No MCP-layer
authentication needed (localhost only). No `user_google_email` parameter
on any tool.

```
CC workspace-mcp-syouran0508 -> localhost:8001 -> Google (syouran0508@gmail.com)
CC workspace-mcp-sun1245     -> localhost:8002 -> Google (sun1245@umd.edu)
```

### Token management

Google OAuth tokens are stored as JSON files at
`~/.config/workspace-mcp-lite/tokens/<account-name>.json`. The file
contains the serialized `google.oauth2.credentials.Credentials` fields:
access_token, refresh_token, token_uri, client_id, client_secret, expiry,
scopes.

On server startup, the token is loaded and refreshed if expired using
`Credentials.refresh(google.auth.transport.requests.Request())`. This is
the standard google-auth refresh mechanism, no proxy or bridge involved.
If the refresh token itself is revoked, the server logs an error and exits
(user must re-run the auth command).

The GCP client secret file lives at
`~/.config/workspace-mcp-lite/client_secret.json`. This is the same GCP
project already configured (personal-workspace-mcp), just a copy of the
downloaded JSON.

### Browser-based OAuth flow

`workspace-mcp-lite auth <account-name>` does:

1. Read client_secret.json
2. Start a temporary local HTTP server on a free port
3. Build a Google OAuth authorization URL with the redirect URI pointing
   to the temporary server
4. Open the URL in the default browser
5. User completes Google consent
6. Google redirects to the temporary server's `/oauth2callback` endpoint
7. Server exchanges code for tokens, stores them to disk
8. Serves a polished HTML success page (gradient background, animated
   checkmark, account email displayed, auto-close after 10 seconds)
9. On error, serves an error page with the message
10. Temporary server shuts down

The `<account-name>` is a short identifier (e.g., `syouran0508`,
`sun1245`). The Google email is determined from the token after the OAuth
flow completes (via the `id_token` or a Gmail profile API call).

### MCP server

Uses the official `mcp` Python SDK with streamable-http transport.
Each server instance:

1. Loads the token for its account
2. Builds `googleapiclient.discovery.Resource` objects for Gmail v1 and
   Calendar v3
3. Registers all 21 tools
4. Runs via uvicorn on the configured port

The google API service objects are rebuilt when credentials are refreshed.

## Project structure

```
workspace-mcp-lite/
├── pyproject.toml
├── .pre-commit-config.yaml
├── src/
│   └── workspace_mcp_lite/
│       ├── __init__.py
│       ├── server.py          # MCP server setup, tool registration, uvicorn
│       ├── auth.py            # Token storage, refresh, browser OAuth flow
│       ├── gmail.py           # 14 Gmail tools
│       ├── calendar.py        # 7 Calendar tools
│       ├── responses.py       # OAuth callback HTML pages
│       └── cli.py             # CLI entry point (auth / serve)
└── tests/
    ├── conftest.py            # Shared fixtures (mock credentials, services)
    ├── test_auth.py
    ├── test_gmail.py
    └── test_calendar.py
```

## Tool inventory

### Gmail (14 tools)

| Tool | Read/Write | Description |
|------|-----------|-------------|
| search_gmail_messages | read | Search by query, return id + snippet list |
| get_gmail_message_content | read | Full content of one message |
| get_gmail_messages_content_batch | read | Full content of multiple messages |
| get_gmail_thread_content | read | All messages in a thread |
| get_gmail_threads_content_batch | read | Multiple threads |
| get_gmail_attachment_content | read | Download attachment by id |
| send_gmail_message | write | Send (new, reply, forward) |
| draft_gmail_message | write | Create draft (new, reply, forward) |
| list_gmail_labels | read | List all labels |
| manage_gmail_label | write | Create/update/delete label |
| list_gmail_filters | read | List all filters |
| manage_gmail_filter | write | Create/delete filter |
| modify_gmail_message_labels | write | Add/remove labels on one message |
| batch_modify_gmail_message_labels | write | Add/remove labels on multiple messages |

### Calendar (7 tools)

| Tool | Read/Write | Description |
|------|-----------|-------------|
| list_calendars | read | List all calendars |
| get_events | read | Query events with time range, search |
| manage_event | write | Create/modify/delete/RSVP events |
| manage_out_of_office | write | Create/list/update/delete OOO events |
| manage_focus_time | write | Create/list/update/delete focus time |
| query_freebusy | read | Check free/busy for time range |
| create_calendar | write | Create a new calendar |

## Dependencies

```toml
[project]
requires-python = ">=3.13"
dependencies = [
    "mcp[cli]",
    "google-auth",
    "google-auth-oauthlib",
    "google-api-python-client",
    "uvicorn",
]

[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-asyncio",
    "ruff",
    "pre-commit",
]
```

## Deployment

### systemd template unit

File: `~/.config/systemd/user/workspace-mcp-lite@.service`

```ini
[Unit]
Description=workspace-mcp-lite (%i)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=<venv-path>/bin/workspace-mcp-lite serve --account %i
Restart=on-failure
RestartSec=5
Environment=WORKSPACE_MCP_LITE_PORT_%i=<port>

[Install]
WantedBy=default.target
```

Port assignment is via environment file or hardcoded per-account config.
Simpler approach: a config file at
`~/.config/workspace-mcp-lite/config.toml`:

```toml
[accounts.syouran0508]
port = 8001

[accounts.sun1245]
port = 8002
```

The `serve` command reads port from this config, falling back to CLI
`--port` flag.

### CC registration

```bash
claude mcp add --scope user --transport http \
    workspace-mcp-syouran0508 http://localhost:8001/mcp
claude mcp add --scope user --transport http \
    workspace-mcp-sun1245 http://localhost:8002/mcp
```

### Migration from current setup

1. Run `workspace-mcp-lite auth syouran0508` and
   `workspace-mcp-lite auth sun1245` to get fresh tokens
2. Stop old service: `systemctl --user stop workspace-mcp`
3. Update CC MCP entries to point to new ports (or reuse 8000 for one)
4. Start new services: `systemctl --user start workspace-mcp-lite@syouran0508 workspace-mcp-lite@sun1245`
5. Verify in CC with `/mcp`

## Testing strategy

All tests mock the Google API layer (`googleapiclient.discovery.Resource`).
No real API calls in tests.

- **test_auth.py**: Token save/load roundtrip, refresh on expired token
  (mock `Credentials.refresh`), error on revoked refresh token, browser
  OAuth flow (mock the HTTP server and token exchange)
- **test_gmail.py**: Each of 14 tools gets at least one test. Mock the
  Gmail API service. Verify correct API method calls, parameter passing,
  and output formatting.
- **test_calendar.py**: Each of 7 tools gets at least one test. Same
  mock pattern.
- **conftest.py**: Shared fixtures for mock credentials, mock Gmail/Calendar
  service objects.

## OAuth scopes

```python
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]
```

`gmail.modify` covers read + label modification. `gmail.compose` covers
drafts. `gmail.send` covers sending. `calendar` covers full calendar
access.

## What is NOT included

- No MCP-layer OAuth/authentication (localhost only)
- No multi-tenant support (one account per process)
- No attachment serving endpoint (attachments returned as base64 in tool
  response)
- No Valkey/Redis storage backend
- No Kubernetes/Helm chart
- No Google Docs/Sheets/Drive/Chat/Tasks/Contacts/Forms/Slides/Search
  tools
- No external OAuth provider mode
