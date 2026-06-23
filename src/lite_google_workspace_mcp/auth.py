import json
import logging
import os
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlparse

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".config" / "lite-google-workspace-mcp"

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
        )

    def refresh_if_needed(self, creds: Credentials, account: str) -> None:
        if creds.valid:
            return
        if not creds.refresh_token:
            raise RuntimeError(
                f"No refresh token for account '{account}'. "
                f"Re-run: lite-google-workspace-mcp auth {account}"
            )
        creds.refresh(Request())
        self._save_credentials(account, creds)

    def _save_credentials(self, account: str, creds: Credentials) -> None:
        self.save_token(
            account,
            {
                "token": creds.token,
                "refresh_token": creds.refresh_token,
                "token_uri": creds.token_uri,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "scopes": list(creds.scopes) if creds.scopes else [],
            },
        )

    def get_client_secret_path(self) -> Path:
        return self.config_dir / "client_secret.json"


AUTH_PORT = 8000
AUTH_REDIRECT_URI = f"http://localhost:{AUTH_PORT}/oauth2callback"


def run_auth_flow(account: str, config_dir: Path = CONFIG_DIR) -> str:
    """Run browser-based OAuth flow. Returns the authenticated email address."""
    manager = TokenManager(config_dir)
    client_secret_path = manager.get_client_secret_path()
    if not client_secret_path.exists():
        raise FileNotFoundError(
            f"Client secret not found at {client_secret_path}. "
            "Download it from GCP Console > APIs & Services > Credentials."
        )

    flow = Flow.from_client_secrets_file(
        str(client_secret_path),
        scopes=SCOPES,
        redirect_uri=AUTH_REDIRECT_URI,
    )
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")

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
                self.send_response(400)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(params["error"][0].encode())
                result["error"] = params["error"][0]
                return

            code = params.get("code", [""])[0]
            if not code:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"No authorization code received.")
                result["error"] = "No authorization code"
                return

            try:
                flow.fetch_token(code=code)
                creds = flow.credentials
                email = _get_email_from_credentials(creds)
                manager._save_credentials(account, creds)
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(f"Authorized as {email}. You can close this tab.".encode())
                result["email"] = email
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(str(e).encode())
                result["error"] = str(e)

        def log_message(self, format, *args):
            logger.debug(format, *args)

    server = HTTPServer(("127.0.0.1", AUTH_PORT), CallbackHandler)
    server_thread = Thread(target=server.handle_request, daemon=True)
    server_thread.start()

    print(f"\nAuthorization URL:\n{auth_url}\n")
    webbrowser.open(auth_url)
    print(f"Waiting for callback on port {AUTH_PORT}...")

    server_thread.join(timeout=120)
    server.server_close()

    if "error" in result:
        raise RuntimeError(f"OAuth flow failed: {result['error']}")
    return result.get("email", account)


def _get_email_from_credentials(creds: Credentials) -> str:
    if hasattr(creds, "id_token") and creds.id_token:
        try:
            from google.auth.transport.requests import Request as AuthRequest
            from google.oauth2 import id_token

            info = id_token.verify_oauth2_token(creds.id_token, AuthRequest())
            email = info.get("email")
            if email:
                return email
        except Exception:
            pass

    from googleapiclient.discovery import build

    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "unknown")
