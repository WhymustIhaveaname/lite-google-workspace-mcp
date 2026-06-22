# lite-google-workspace-mcp

Lightweight MCP server for Gmail and Google Calendar. Each Google account runs as an independent process on its own port.

## How it works

```
Claude Code  --HTTP-->  lite-google-workspace-mcp (port 8001)  --Google API-->  account-A@gmail.com
             --HTTP-->  lite-google-workspace-mcp (port 8002)  --Google API-->  account-B@umd.edu
```

- One process per Google account, each listening on a separate port
- OAuth tokens stored locally at `~/.config/lite-google-workspace-mcp/tokens/<account>.json`
- Token refresh handled automatically via `google-auth`
- 21 tools exposed per account: Gmail (search, read, send, draft, labels, filters) + Calendar (events, free/busy, OOO, focus time)

## Prerequisites

1. A GCP project with Gmail API and Google Calendar API enabled
2. An OAuth 2.0 credential (Web application type) with redirect URI `http://localhost:8000/oauth2callback`
3. Download the credential JSON and save it as `~/.config/lite-google-workspace-mcp/client_secret.json`

## Install

```bash
git clone https://github.com/WhymustIhaveaname/lite-google-workspace-mcp.git
cd lite-google-workspace-mcp
uv sync
```

## First-time setup

### 1. Configure ports

Create `~/.config/lite-google-workspace-mcp/config.toml`:

```toml
[accounts.myaccount]
port = 8001

[accounts.work]
port = 8002
allowed_recipients = ["boss@company.com", "team@company.com"]
```

The account name is just a label you choose. It maps to a token file and a port.

`allowed_recipients` is optional. When set, `send_gmail_message` and `draft_gmail_message` will only allow sending to the listed addresses (checked against to/cc/bcc, case-insensitive). Omit it to allow sending to anyone.

### 2. Authorize accounts

```bash
uv run lite-google-workspace-mcp auth myaccount
```

This prints an OAuth URL and opens your browser. Sign in with the Google account you want to link, grant permissions (you can skip some scopes if you want), and the token is saved locally.

Repeat for each account.

### 3. Start the server

Manual:

```bash
uv run lite-google-workspace-mcp serve --account myaccount
```

With systemd (recommended):

```bash
cp contrib/lite-google-workspace-mcp@.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now lite-google-workspace-mcp@myaccount
```

### 4. Connect to Claude Code

```bash
claude mcp add --scope user --transport http lite-gmail-myaccount http://localhost:8001/mcp
```

## Re-authorization

If a token expires or you want to change granted scopes:

```bash
# Stop the service first (auth uses port 8000 which must be free)
systemctl --user stop lite-google-workspace-mcp@myaccount

# Re-authorize
uv run lite-google-workspace-mcp auth myaccount

# Restart
systemctl --user start lite-google-workspace-mcp@myaccount
```

## Tools

### Gmail (13 tools)

| Tool | Description |
|------|-------------|
| search_gmail_messages | Search by Gmail query syntax |
| get_gmail_message_content | Read a single message |
| get_gmail_messages_content_batch | Read multiple messages |
| get_gmail_thread_content | Read an entire thread |
| get_gmail_threads_content_batch | Read multiple threads |
| get_gmail_attachment_content | Download attachment |
| send_gmail_message | Send (plain text or HTML, with attachments) |
| draft_gmail_message | Create a draft |
| list_gmail_labels | List all labels |
| manage_gmail_label | Create/update/delete labels |
| list_gmail_filters | List all filters |
| manage_gmail_filter | Create/delete filters |
| modify_gmail_message_labels | Add/remove labels on a message |
| batch_modify_gmail_message_labels | Bulk label modification |

### Calendar (8 tools)

| Tool | Description |
|------|-------------|
| list_calendars | List all calendars |
| get_events | Query events by time range |
| manage_event | Create/update/delete events |
| manage_out_of_office | Create/update/delete OOO blocks |
| manage_focus_time | Create/update/delete focus time |
| query_freebusy | Check availability |
| create_calendar | Create a new calendar |

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src/
```
