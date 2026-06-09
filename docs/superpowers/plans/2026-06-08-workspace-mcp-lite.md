# workspace-mcp-lite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 258k-line fastmcp + google_workspace_mcp stack with a ~1500-line minimal MCP server for Gmail and Calendar.

**Architecture:** Two-port, no-auth model. Each Google account runs as a separate `FastMCP` server process on its own port. Google OAuth tokens stored locally and refreshed via `google-auth`. The `mcp` SDK's built-in `FastMCP` class handles MCP protocol (streamable-http transport) and tool registration.

**Tech Stack:** Python 3.13, `mcp` SDK (includes `FastMCP`), `google-auth`, `google-auth-oauthlib`, `google-api-python-client`, `uvicorn`, `uv` for venv, `ruff`, `pre-commit`, `pytest`, `pytest-asyncio`.

---

## File Structure

```
workspace-mcp-lite/
├── pyproject.toml                  # Project metadata, dependencies, ruff config, CLI entry point
├── .pre-commit-config.yaml         # Pre-commit hooks (ruff)
├── src/
│   └── workspace_mcp_lite/
│       ├── __init__.py             # Package version
│       ├── auth.py                 # Google OAuth token management (save/load/refresh/browser flow)
│       ├── responses.py            # HTML pages for OAuth callback (success/error)
│       ├── gmail.py                # 14 Gmail MCP tools + helpers
│       ├── calendar.py             # 7 Calendar MCP tools + helpers
│       ├── server.py               # FastMCP server setup, Google service construction
│       └── cli.py                  # CLI entry point (auth / serve subcommands)
└── tests/
    ├── conftest.py                 # Shared fixtures (mock credentials, Gmail/Calendar services)
    ├── test_auth.py                # Token save/load/refresh tests
    ├── test_gmail.py               # Gmail tool tests
    └── test_calendar.py            # Calendar tool tests
```

---

### Task 1: Project scaffold (pyproject.toml, pre-commit, package init)

**Files:**
- Create: `pyproject.toml`
- Create: `.pre-commit-config.yaml`
- Create: `src/workspace_mcp_lite/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "workspace-mcp-lite"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "mcp[cli]",
    "google-auth",
    "google-auth-oauthlib",
    "google-api-python-client",
]

[project.scripts]
workspace-mcp-lite = "workspace_mcp_lite.cli:main"

[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-asyncio",
    "ruff",
    "pre-commit",
]

[tool.ruff]
target-version = "py313"
line-length = 99

[tool.ruff.lint]
select = ["E", "F", "I", "W"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create .pre-commit-config.yaml**

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.11.13
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

- [ ] **Step 3: Create src/workspace_mcp_lite/__init__.py**

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: Initialize git repo and uv venv**

```bash
cd ~/Codes/workspace-mcp-lite
git init
uv venv --python 3.13
uv pip install -e ".[dev]"
```

- [ ] **Step 5: Install pre-commit hooks**

```bash
cd ~/Codes/workspace-mcp-lite
uv run pre-commit install
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .pre-commit-config.yaml src/workspace_mcp_lite/__init__.py
git commit -m "chore: scaffold project with pyproject.toml and pre-commit"
```

---

### Task 2: OAuth HTML response pages

**Files:**
- Create: `src/workspace_mcp_lite/responses.py`

- [ ] **Step 1: Create responses.py**

This module provides the HTML pages shown in the browser after OAuth callback. Ported from the existing workspace-mcp's polished design.

```python
from html import escape as html_escape


def success_html(email: str) -> str:
    safe_email = html_escape(email)
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Authentication Successful</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #0f172a, #1e293b, #334155);
            min-height: 100vh;
            display: flex; align-items: center; justify-content: center;
        }}
        .container {{
            background: rgba(255,255,255,0.95); backdrop-filter: blur(10px);
            padding: 60px; border-radius: 20px;
            box-shadow: 0 30px 60px rgba(0,0,0,0.12);
            text-align: center; max-width: 480px; width: 90%;
            animation: slideUp 0.6s ease-out;
        }}
        @keyframes slideUp {{
            from {{ opacity: 0; transform: translateY(20px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .icon {{
            width: 80px; height: 80px; margin: 0 auto 30px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            border-radius: 50%; display: flex; align-items: center; justify-content: center;
            font-size: 40px; color: white;
        }}
        h1 {{
            font-size: 28px; font-weight: 600; margin-bottom: 20px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        }}
        .message {{ font-size: 16px; line-height: 1.6; color: #4a5568; margin-bottom: 20px; }}
        .user-id {{
            font-weight: 600; color: #667eea;
            padding: 4px 12px; background: rgba(102,126,234,0.1); border-radius: 6px;
        }}
        .button {{
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white; padding: 16px 40px; border: none; border-radius: 30px;
            font-size: 16px; cursor: pointer; margin-top: 30px;
            box-shadow: 0 4px 15px rgba(102,126,234,0.3);
        }}
        .auto-close {{ font-size: 13px; color: #a0aec0; margin-top: 30px; }}
    </style>
    <script>
        function tryClose() {{
            window.close();
            setTimeout(function() {{
                var btn = document.querySelector('.button');
                if (btn) btn.textContent = 'You can close this tab manually';
            }}, 500);
        }}
        setTimeout(tryClose, 10000);
    </script>
</head>
<body>
    <div class="container">
        <div class="icon">✓</div>
        <h1>Authentication Successful</h1>
        <div class="message">
            Authenticated as <span class="user-id">{safe_email}</span>
        </div>
        <div class="message">Credentials saved. You can close this tab.</div>
        <button class="button" onclick="tryClose()">Close Tab</button>
        <div class="auto-close">This tab will close automatically in 10 seconds</div>
    </div>
</body>
</html>"""


def error_html(message: str) -> str:
    safe_msg = html_escape(message)
    return f"""<!DOCTYPE html>
<html>
<head><title>Authentication Error</title></head>
<body style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 40px auto;
             padding: 20px; text-align: center;">
    <h2 style="color: #d32f2f;">Authentication Error</h2>
    <p>{safe_msg}</p>
    <p>You can close this tab and try again.</p>
</body>
</html>"""
```

- [ ] **Step 2: Run ruff**

```bash
cd ~/Codes/workspace-mcp-lite
uv run ruff check src/workspace_mcp_lite/responses.py
uv run ruff format src/workspace_mcp_lite/responses.py
```

- [ ] **Step 3: Commit**

```bash
git add src/workspace_mcp_lite/responses.py
git commit -m "feat: add OAuth callback HTML pages"
```

---

### Task 3: Auth module (token storage, refresh, browser OAuth flow)

**Files:**
- Create: `src/workspace_mcp_lite/auth.py`
- Create: `tests/conftest.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write test_auth.py with failing tests**

```python
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from workspace_mcp_lite.auth import (
    CONFIG_DIR,
    TokenManager,
)


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    monkeypatch.setattr("workspace_mcp_lite.auth.CONFIG_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def token_manager(tmp_config):
    return TokenManager(tmp_config)


class TestTokenManager:
    def test_save_and_load_roundtrip(self, token_manager, tmp_config):
        token_data = {
            "token": "access123",
            "refresh_token": "refresh456",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "client.apps.googleusercontent.com",
            "client_secret": "secret",
            "scopes": ["https://www.googleapis.com/auth/gmail.modify"],
        }
        token_manager.save_token("testaccount", token_data)

        token_path = tmp_config / "tokens" / "testaccount.json"
        assert token_path.exists()

        loaded = token_manager.load_token_data("testaccount")
        assert loaded["refresh_token"] == "refresh456"

    def test_load_missing_token_returns_none(self, token_manager):
        result = token_manager.load_token_data("nonexistent")
        assert result is None

    def test_build_credentials(self, token_manager, tmp_config):
        token_data = {
            "token": "access123",
            "refresh_token": "refresh456",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "client.apps.googleusercontent.com",
            "client_secret": "secret",
            "scopes": ["https://www.googleapis.com/auth/gmail.modify"],
        }
        token_manager.save_token("testaccount", token_data)

        creds = token_manager.build_credentials("testaccount")
        assert creds is not None
        assert creds.refresh_token == "refresh456"

    def test_build_credentials_missing_returns_none(self, token_manager):
        result = token_manager.build_credentials("nonexistent")
        assert result is None

    @patch("workspace_mcp_lite.auth.Request")
    def test_refresh_expired_credentials(self, mock_request_cls, token_manager, tmp_config):
        token_data = {
            "token": "expired",
            "refresh_token": "refresh456",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "client.apps.googleusercontent.com",
            "client_secret": "secret",
            "scopes": ["https://www.googleapis.com/auth/gmail.modify"],
        }
        token_manager.save_token("testaccount", token_data)
        creds = token_manager.build_credentials("testaccount")

        creds.valid = False
        creds.expired = True
        creds.refresh_token = "refresh456"

        with patch.object(creds, "refresh") as mock_refresh:
            mock_refresh.side_effect = lambda req: setattr(creds, "token", "new_access")
            token_manager.refresh_if_needed(creds, "testaccount")

        mock_refresh.assert_called_once()
```

- [ ] **Step 2: Create conftest.py**

```python
```

Empty for now; fixtures live in test files until shared.

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd ~/Codes/workspace-mcp-lite
uv run pytest tests/test_auth.py -v
```

Expected: FAIL (module `workspace_mcp_lite.auth` does not exist).

- [ ] **Step 4: Implement auth.py**

```python
import json
import logging
import socket
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlparse

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from workspace_mcp_lite.responses import error_html, success_html

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".config" / "workspace-mcp-lite"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]


class TokenManager:
    def __init__(self, config_dir: Path = CONFIG_DIR):
        self.config_dir = config_dir
        self.tokens_dir = config_dir / "tokens"

    def save_token(self, account: str, token_data: dict[str, Any]) -> None:
        self.tokens_dir.mkdir(parents=True, exist_ok=True)
        path = self.tokens_dir / f"{account}.json"
        path.write_text(json.dumps(token_data, indent=2))
        path.chmod(0o600)

    def load_token_data(self, account: str) -> dict[str, Any] | None:
        path = self.tokens_dir / f"{account}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def build_credentials(self, account: str) -> Credentials | None:
        data = self.load_token_data(account)
        if data is None:
            return None
        return Credentials(
            token=data.get("token"),
            refresh_token=data.get("refresh_token"),
            token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            scopes=data.get("scopes"),
        )

    def refresh_if_needed(self, creds: Credentials, account: str) -> None:
        if creds.valid:
            return
        if not creds.refresh_token:
            raise RuntimeError(f"No refresh token for account '{account}'. Re-run: workspace-mcp-lite auth {account}")
        creds.refresh(Request())
        self._save_credentials(account, creds)

    def _save_credentials(self, account: str, creds: Credentials) -> None:
        self.save_token(account, {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes) if creds.scopes else [],
        })

    def get_client_secret_path(self) -> Path:
        return self.config_dir / "client_secret.json"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_auth_flow(account: str, config_dir: Path = CONFIG_DIR) -> str:
    """Run browser-based OAuth flow. Returns the authenticated email address."""
    manager = TokenManager(config_dir)
    client_secret_path = manager.get_client_secret_path()
    if not client_secret_path.exists():
        raise FileNotFoundError(
            f"Client secret not found at {client_secret_path}. "
            "Download it from GCP Console > APIs & Services > Credentials."
        )

    port = _find_free_port()
    redirect_uri = f"http://localhost:{port}/oauth2callback"

    flow = Flow.from_client_secrets_file(
        str(client_secret_path),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )

    result: dict[str, Any] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path != "/oauth2callback":
                self.send_response(404)
                self.end_headers()
                return

            params = parse_qs(parsed.query)
            if "error" in params:
                err_msg = params["error"][0]
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(error_html(err_msg).encode())
                result["error"] = err_msg
                return

            code = params.get("code", [""])[0]
            if not code:
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(error_html("No authorization code received.").encode())
                result["error"] = "No authorization code"
                return

            try:
                flow.fetch_token(code=code)
                creds = flow.credentials
                email = _get_email_from_credentials(creds)
                manager._save_credentials(account, creds)

                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(success_html(email).encode())
                result["email"] = email
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(error_html(str(e)).encode())
                result["error"] = str(e)

        def log_message(self, format, *args):
            logger.debug(format, *args)

    server = HTTPServer(("127.0.0.1", port), CallbackHandler)
    server_thread = Thread(target=server.handle_request, daemon=True)
    server_thread.start()

    webbrowser.open(auth_url)
    logger.info("Opened browser for Google authorization. Waiting for callback...")

    server_thread.join(timeout=120)
    server.server_close()

    if "error" in result:
        raise RuntimeError(f"OAuth flow failed: {result['error']}")
    return result.get("email", account)


def _get_email_from_credentials(creds: Credentials) -> str:
    """Extract email from the ID token, or fall back to a Gmail API call."""
    from google.oauth2 import id_token
    from google.auth.transport.requests import Request as AuthRequest

    if hasattr(creds, "id_token") and creds.id_token:
        try:
            info = id_token.verify_oauth2_token(creds.id_token, AuthRequest())
            return info.get("email", "unknown")
        except Exception:
            pass

    from googleapiclient.discovery import build

    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "unknown")
```

- [ ] **Step 5: Run tests**

```bash
cd ~/Codes/workspace-mcp-lite
uv run pytest tests/test_auth.py -v
```

Expected: all PASS.

- [ ] **Step 6: Run ruff**

```bash
uv run ruff check src/workspace_mcp_lite/auth.py --fix
uv run ruff format src/workspace_mcp_lite/auth.py
```

- [ ] **Step 7: Commit**

```bash
git add src/workspace_mcp_lite/auth.py tests/conftest.py tests/test_auth.py
git commit -m "feat: add auth module with token management and browser OAuth flow"
```

---

### Task 4: Gmail tools (14 tools + helpers)

**Files:**
- Create: `src/workspace_mcp_lite/gmail.py`
- Create: `tests/test_gmail.py`

- [ ] **Step 1: Write test_gmail.py with tests for key tools**

```python
import asyncio
import base64
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from workspace_mcp_lite.gmail import (
    extract_headers,
    extract_message_bodies,
    extract_attachments,
    format_body_content,
    format_gmail_results,
    format_message_header_lines,
    format_thread_content,
    html_to_text,
    prepare_gmail_message,
    register_gmail_tools,
)


class TestHelpers:
    def test_html_to_text(self):
        html = "<p>Hello <b>world</b></p><script>evil()</script>"
        result = html_to_text(html)
        assert "Hello" in result
        assert "world" in result
        assert "evil" not in result

    def test_extract_headers(self):
        payload = {
            "headers": [
                {"name": "Subject", "value": "Test"},
                {"name": "From", "value": "alice@example.com"},
                {"name": "Date", "value": "Mon, 1 Jan 2026 00:00:00 +0000"},
            ]
        }
        result = extract_headers(payload, ["Subject", "From", "Date"])
        assert result["Subject"] == "Test"
        assert result["From"] == "alice@example.com"

    def test_extract_message_bodies_plain(self):
        data = base64.urlsafe_b64encode(b"Hello plain").decode()
        payload = {"mimeType": "text/plain", "body": {"data": data}}
        bodies = extract_message_bodies(payload)
        assert bodies["text"] == "Hello plain"

    def test_extract_message_bodies_multipart(self):
        text_data = base64.urlsafe_b64encode(b"Plain text").decode()
        html_data = base64.urlsafe_b64encode(b"<b>HTML</b>").decode()
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": text_data}},
                {"mimeType": "text/html", "body": {"data": html_data}},
            ],
        }
        bodies = extract_message_bodies(payload)
        assert bodies["text"] == "Plain text"
        assert bodies["html"] == "<b>HTML</b>"

    def test_extract_attachments(self):
        payload = {
            "parts": [
                {
                    "filename": "report.pdf",
                    "mimeType": "application/pdf",
                    "body": {"attachmentId": "att123", "size": 1024},
                },
                {
                    "mimeType": "text/plain",
                    "body": {"data": "dGVzdA=="},
                },
            ]
        }
        atts = extract_attachments(payload)
        assert len(atts) == 1
        assert atts[0]["filename"] == "report.pdf"
        assert atts[0]["attachmentId"] == "att123"

    def test_format_body_content_prefers_text(self):
        result = format_body_content("Plain body", "<b>HTML</b>", body_format="text")
        assert result == "Plain body"

    def test_format_body_content_html_mode(self):
        result = format_body_content("Plain", "<b>HTML</b>", body_format="html")
        assert "<b>HTML</b>" in result

    def test_format_gmail_results_empty(self):
        result = format_gmail_results([], "test query")
        assert "No messages found" in result

    def test_format_gmail_results_with_messages(self):
        messages = [{"id": "msg1", "threadId": "t1"}, {"id": "msg2", "threadId": "t2"}]
        result = format_gmail_results(messages, "test")
        assert "msg1" in result
        assert "msg2" in result

    def test_format_message_header_lines(self):
        headers = {"Subject": "Test", "From": "alice@x.com", "Date": "2026-01-01"}
        lines = format_message_header_lines(headers)
        assert any("Test" in l for l in lines)

    def test_prepare_gmail_message_basic(self):
        raw, tid, count, errors = prepare_gmail_message(
            subject="Hello", body="World", to="bob@example.com"
        )
        assert isinstance(raw, str)
        assert count == 0
        decoded = base64.urlsafe_b64decode(raw)
        assert b"Hello" in decoded
        assert b"World" in decoded

    def test_prepare_gmail_message_reply(self):
        raw, tid, count, errors = prepare_gmail_message(
            subject="Meeting",
            body="Sure",
            to="bob@example.com",
            thread_id="t123",
            in_reply_to="<orig@gmail.com>",
        )
        decoded = base64.urlsafe_b64decode(raw)
        assert b"Re: Meeting" in decoded
        assert b"In-Reply-To" in decoded

    def test_format_thread_content(self):
        text_data = base64.urlsafe_b64encode(b"Thread msg body").decode()
        thread_data = {
            "messages": [
                {
                    "id": "m1",
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "Topic"},
                            {"name": "From", "value": "alice@x.com"},
                            {"name": "Date", "value": "2026-01-01"},
                        ],
                        "mimeType": "text/plain",
                        "body": {"data": text_data},
                    },
                }
            ]
        }
        result = format_thread_content(thread_data, "t1")
        assert "Topic" in result
        assert "Thread msg body" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/Codes/workspace-mcp-lite
uv run pytest tests/test_gmail.py -v
```

Expected: FAIL (module does not exist).

- [ ] **Step 3: Implement gmail.py**

This is the largest file. It contains all 14 Gmail tools and helpers. The tools are registered via a `register_gmail_tools(server, gmail_service)` function that captures the `gmail_service` in a closure.

Reference implementation at `~/Codes/google_workspace_mcp/gmail/gmail_tools.py` for Google API call patterns. Key differences from the original:
- No `user_google_email` parameter on any tool (single-account per process)
- No `@require_google_service` decorator (service passed at registration time)
- No `@handle_http_errors` decorator (errors propagate naturally via MCP)
- Helper functions are module-level, not closures
- `asyncio.to_thread()` for all Google API calls (same pattern as original)

The file should contain:

1. **Helper functions** (all public, tested independently):
   - `html_to_text(html)` - HTML to plaintext using stdlib HTMLParser
   - `extract_headers(payload, header_names)` - extract specified headers from payload
   - `extract_message_bodies(payload)` - extract text/html bodies from MIME payload
   - `extract_attachments(payload)` - extract attachment metadata recursively
   - `format_body_content(text_body, html_body, body_format)` - format body with HTML fallback
   - `format_message_header_lines(headers, message_id=None)` - format headers for display
   - `format_gmail_results(messages, query, next_page_token=None)` - format search results
   - `format_thread_content(thread_data, thread_id, body_format, raw_contents=None)` - format thread
   - `prepare_gmail_message(subject, body, to, ...)` - build raw MIME message

2. **`register_gmail_tools(server, service)`** function that registers all 14 `@server.tool()` handlers:
   - `search_gmail_messages(query, page_size=10, page_token=None)`
   - `get_gmail_message_content(message_id, body_format="text")`
   - `get_gmail_messages_content_batch(message_ids, format="full", body_format="text")`
   - `get_gmail_thread_content(thread_id, body_format="text")`
   - `get_gmail_threads_content_batch(thread_ids, body_format="text")`
   - `get_gmail_attachment_content(message_id, attachment_id, return_base64=False)`
   - `send_gmail_message(to, subject, body, ...)`
   - `draft_gmail_message(subject, body, ...)`
   - `list_gmail_labels()`
   - `manage_gmail_label(action, name=None, label_id=None, ...)`
   - `list_gmail_filters()`
   - `manage_gmail_filter(action, criteria=None, filter_action=None, filter_id=None)`
   - `modify_gmail_message_labels(message_id, add_label_ids=None, remove_label_ids=None)`
   - `batch_modify_gmail_message_labels(message_ids, add_label_ids=None, remove_label_ids=None)`

Port each tool's logic from the reference implementation. The API call patterns are identical (e.g., `service.users().messages().list(**params).execute()`), just wrapped in `asyncio.to_thread()`.

- [ ] **Step 4: Run tests**

```bash
cd ~/Codes/workspace-mcp-lite
uv run pytest tests/test_gmail.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run ruff**

```bash
uv run ruff check src/workspace_mcp_lite/gmail.py --fix
uv run ruff format src/workspace_mcp_lite/gmail.py
```

- [ ] **Step 6: Commit**

```bash
git add src/workspace_mcp_lite/gmail.py tests/test_gmail.py
git commit -m "feat: add 14 Gmail MCP tools with helpers"
```

---

### Task 5: Calendar tools (7 tools + helpers)

**Files:**
- Create: `src/workspace_mcp_lite/calendar.py`
- Create: `tests/test_calendar.py`

- [ ] **Step 1: Write test_calendar.py with tests for key tools**

```python
import asyncio
import datetime
from unittest.mock import MagicMock, patch

import pytest

from workspace_mcp_lite.calendar import (
    correct_time_format,
    format_attendee_details,
    get_meeting_link,
    register_calendar_tools,
)


class TestHelpers:
    def test_correct_time_format_date_only(self):
        result = correct_time_format("2026-06-15")
        assert result.startswith("2026-06-15T")

    def test_correct_time_format_full_rfc3339(self):
        result = correct_time_format("2026-06-15T10:00:00Z")
        assert result == "2026-06-15T10:00:00Z"

    def test_correct_time_format_none(self):
        result = correct_time_format(None)
        assert result is None

    def test_format_attendee_details(self):
        attendees = [
            {"email": "a@x.com", "responseStatus": "accepted"},
            {"email": "b@x.com", "responseStatus": "declined", "organizer": True},
        ]
        result = format_attendee_details(attendees)
        assert "a@x.com" in result
        assert "accepted" in result
        assert "organizer" in result.lower()

    def test_get_meeting_link_hangout(self):
        event = {"hangoutLink": "https://meet.google.com/abc-def"}
        assert get_meeting_link(event) == "https://meet.google.com/abc-def"

    def test_get_meeting_link_conference(self):
        event = {
            "conferenceData": {
                "entryPoints": [{"entryPointType": "video", "uri": "https://meet.google.com/xyz"}]
            }
        }
        assert "meet.google.com" in get_meeting_link(event)

    def test_get_meeting_link_none(self):
        assert get_meeting_link({}) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/Codes/workspace-mcp-lite
uv run pytest tests/test_calendar.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement calendar.py**

Reference implementation at `~/Codes/google_workspace_mcp/gcalendar/calendar_tools.py`. Same pattern as gmail.py:

1. **Helper functions:**
   - `correct_time_format(time_str)` - normalize date/datetime strings for Google API
   - `format_attendee_details(attendees, indent="  ")` - format attendee list
   - `get_meeting_link(event)` - extract Google Meet link from event
   - `format_attachment_details(attachments, indent="  ")` - format calendar attachment list
   - `parse_reminders(reminders_input)` - parse/validate reminder objects

2. **`register_calendar_tools(server, service)`** function registering 7 `@server.tool()` handlers:
   - `list_calendars()`
   - `get_events(calendar_id="primary", event_id=None, time_min=None, time_max=None, max_results=25, query=None, detailed=False)`
   - `manage_event(action, summary=None, start_time=None, end_time=None, event_id=None, calendar_id="primary", ...)` - create/update/delete/rsvp
   - `manage_out_of_office(action, start_time=None, end_time=None, ...)` - create/list/update/delete OOO events
   - `manage_focus_time(action, start_time=None, end_time=None, ...)` - create/list/update/delete focus time
   - `query_freebusy(time_min, time_max, calendars=None)`
   - `create_calendar(summary, description=None, timezone=None)`

Port the logic from the reference, especially:
- `_create_event_impl`, `_modify_event_impl`, `_delete_event_impl`, `_rsvp_event_impl`
- OOO and focus time event impl functions
- Time format correction logic
- All wrapped in `asyncio.to_thread()`

- [ ] **Step 4: Run tests**

```bash
cd ~/Codes/workspace-mcp-lite
uv run pytest tests/test_calendar.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run ruff**

```bash
uv run ruff check src/workspace_mcp_lite/calendar.py --fix
uv run ruff format src/workspace_mcp_lite/calendar.py
```

- [ ] **Step 6: Commit**

```bash
git add src/workspace_mcp_lite/calendar.py tests/test_calendar.py
git commit -m "feat: add 7 Calendar MCP tools with helpers"
```

---

### Task 6: Server module (FastMCP setup, Google service construction)

**Files:**
- Create: `src/workspace_mcp_lite/server.py`

- [ ] **Step 1: Implement server.py**

```python
import logging

from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from mcp.server.fastmcp import FastMCP

from workspace_mcp_lite.auth import SCOPES, TokenManager
from workspace_mcp_lite.calendar import register_calendar_tools
from workspace_mcp_lite.gmail import register_gmail_tools

logger = logging.getLogger(__name__)


def create_server(account: str, port: int) -> FastMCP:
    manager = TokenManager()
    creds = manager.build_credentials(account)
    if creds is None:
        raise RuntimeError(
            f"No credentials for account '{account}'. "
            f"Run: workspace-mcp-lite auth {account}"
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
```

- [ ] **Step 2: Run ruff**

```bash
uv run ruff check src/workspace_mcp_lite/server.py --fix
uv run ruff format src/workspace_mcp_lite/server.py
```

- [ ] **Step 3: Commit**

```bash
git add src/workspace_mcp_lite/server.py
git commit -m "feat: add server module with FastMCP setup and Google service construction"
```

---

### Task 7: CLI entry point (auth and serve subcommands)

**Files:**
- Create: `src/workspace_mcp_lite/cli.py`

- [ ] **Step 1: Implement cli.py**

```python
import argparse
import logging
import sys
import tomllib
from pathlib import Path

from workspace_mcp_lite.auth import CONFIG_DIR, TokenManager, run_auth_flow


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
        print(f"Error: No port specified. Use --port or set it in {CONFIG_DIR}/config.toml", file=sys.stderr)
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
```

- [ ] **Step 2: Verify CLI entry point works**

```bash
cd ~/Codes/workspace-mcp-lite
uv run workspace-mcp-lite --help
uv run workspace-mcp-lite auth --help
uv run workspace-mcp-lite serve --help
```

Expected: help text for each subcommand.

- [ ] **Step 3: Run ruff**

```bash
uv run ruff check src/workspace_mcp_lite/cli.py --fix
uv run ruff format src/workspace_mcp_lite/cli.py
```

- [ ] **Step 4: Commit**

```bash
git add src/workspace_mcp_lite/cli.py
git commit -m "feat: add CLI with auth and serve subcommands"
```

---

### Task 8: Run full test suite, ruff, and fix any issues

**Files:**
- Modify: any files with issues

- [ ] **Step 1: Run full test suite**

```bash
cd ~/Codes/workspace-mcp-lite
uv run pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 2: Run ruff on entire project**

```bash
uv run ruff check src/ tests/ --fix
uv run ruff format src/ tests/
```

- [ ] **Step 3: Run pre-commit on all files**

```bash
uv run pre-commit run --all-files
```

Expected: all hooks pass.

- [ ] **Step 4: Commit any fixes**

```bash
git add -u
git commit -m "chore: fix lint and formatting issues"
```

---

### Task 9: Create config.toml and systemd template unit

**Files:**
- Create: `~/.config/workspace-mcp-lite/config.toml` (on user's system, not in repo)
- Create: `contrib/workspace-mcp-lite@.service` (in repo, for reference)

- [ ] **Step 1: Create default config.toml**

```bash
mkdir -p ~/.config/workspace-mcp-lite
```

Write `~/.config/workspace-mcp-lite/config.toml`:

```toml
[accounts.syouran0508]
port = 8001

[accounts.sun1245]
port = 8002
```

- [ ] **Step 2: Create systemd template unit in repo**

Create `contrib/workspace-mcp-lite@.service`:

```ini
[Unit]
Description=workspace-mcp-lite (%i)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=%h/Codes/workspace-mcp-lite/.venv/bin/workspace-mcp-lite serve --account %i
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

- [ ] **Step 3: Commit**

```bash
cd ~/Codes/workspace-mcp-lite
git add contrib/
git commit -m "chore: add systemd template unit and config example"
```

---

### Task 10: End-to-end smoke test

- [ ] **Step 1: Copy client_secret.json to config dir**

```bash
cp ~/.config/workspace-mcp/.env /dev/null  # just checking old config exists
# The user's GCP client_secret.json needs to be placed at:
# ~/.config/workspace-mcp-lite/client_secret.json
# This is a manual step - download from GCP Console or copy from existing setup.
```

- [ ] **Step 2: Run auth for one account**

```bash
cd ~/Codes/workspace-mcp-lite
uv run workspace-mcp-lite auth syouran0508
```

Expected: browser opens, Google consent screen, callback succeeds, token saved.

- [ ] **Step 3: Start server and verify with a quick tool call**

```bash
uv run workspace-mcp-lite serve --account syouran0508 --port 8001
```

In another terminal, verify MCP endpoint responds:

```bash
curl -s http://localhost:8001/mcp -X POST -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"0.1"}},"id":1}'
```

Expected: JSON-RPC response with server capabilities.

- [ ] **Step 4: Register with Claude Code and test**

```bash
claude mcp add --scope user --transport http workspace-mcp-syouran0508 http://localhost:8001/mcp
```

Open new CC session, run `/mcp` to verify tools are listed.
