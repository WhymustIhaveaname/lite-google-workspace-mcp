from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from google.oauth2.credentials import Credentials

from lite_google_workspace_mcp.auth import TokenManager


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    monkeypatch.setattr("lite_google_workspace_mcp.auth.CONFIG_DIR", tmp_path)
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

    def test_build_credentials(self, token_manager):
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

    def test_build_credentials_restores_expiry_and_scopes(self, token_manager):
        scopes = ["https://www.googleapis.com/auth/gmail.modify"]
        token_data = {
            "token": "access123",
            "refresh_token": "refresh456",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "client.apps.googleusercontent.com",
            "client_secret": "secret",
            "scopes": scopes,
            "expiry": "2026-06-26T12:34:56",
        }
        token_manager.save_token("testaccount", token_data)

        creds = token_manager.build_credentials("testaccount")
        assert creds is not None
        assert creds.expiry == datetime(2026, 6, 26, 12, 34, 56)
        assert creds.scopes is None

    def test_build_credentials_normalizes_aware_expiry_to_utc(self, token_manager):
        token_data = {
            "token": "access123",
            "refresh_token": "refresh456",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "client.apps.googleusercontent.com",
            "client_secret": "secret",
            "expiry": "2026-06-26T20:00:00+08:00",
        }
        token_manager.save_token("testaccount", token_data)

        creds = token_manager.build_credentials("testaccount")
        assert creds is not None
        assert creds.expiry == datetime(2026, 6, 26, 12, 0, 0)

    def test_build_credentials_without_expiry_forces_refresh(self, token_manager):
        token_data = {
            "token": "access123",
            "refresh_token": "refresh456",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "client.apps.googleusercontent.com",
            "client_secret": "secret",
        }
        token_manager.save_token("testaccount", token_data)

        creds = token_manager.build_credentials("testaccount")
        assert creds is not None
        assert creds.expired

    def test_save_credentials_persists_expiry_and_scopes(self, token_manager):
        scopes = ["https://www.googleapis.com/auth/gmail.modify"]
        expiry = datetime(2026, 6, 26, 12, 34, 56, tzinfo=UTC)
        creds = Credentials(
            token="access123",
            refresh_token="refresh456",
            token_uri="https://oauth2.googleapis.com/token",
            client_id="client.apps.googleusercontent.com",
            client_secret="secret",
            scopes=scopes,
            expiry=expiry,
        )

        token_manager._save_credentials("testaccount", creds)

        loaded = token_manager.load_token_data("testaccount")
        assert loaded is not None
        assert loaded["scopes"] == scopes
        assert loaded["expiry"] == "2026-06-26T12:34:56+00:00"

    def test_build_credentials_missing_returns_none(self, token_manager):
        result = token_manager.build_credentials("nonexistent")
        assert result is None

    @patch("lite_google_workspace_mcp.auth.Request")
    def test_refresh_expired_credentials(self, mock_request_cls, token_manager):
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

        with patch.object(type(creds), "valid", new_callable=lambda: property(lambda self: False)):
            with patch.object(creds, "refresh") as mock_refresh:
                token_manager.refresh_if_needed(creds, "testaccount")

        mock_refresh.assert_called_once()

    @patch("lite_google_workspace_mcp.auth.Request")
    def test_refresh_preserves_saved_scopes(self, mock_request_cls, token_manager):
        scopes = ["https://www.googleapis.com/auth/gmail.modify"]
        token_data = {
            "token": "expired",
            "refresh_token": "refresh456",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "client.apps.googleusercontent.com",
            "client_secret": "secret",
            "scopes": scopes,
        }
        token_manager.save_token("testaccount", token_data)
        creds = token_manager.build_credentials("testaccount")
        assert creds.scopes is None

        def refresh(_request):
            creds.token = "fresh"
            creds.expiry = datetime(2026, 6, 26, 12, 34, 56, tzinfo=UTC)

        with patch.object(creds, "refresh", side_effect=refresh):
            token_manager.refresh_if_needed(creds, "testaccount")

        loaded = token_manager.load_token_data("testaccount")
        assert loaded is not None
        assert loaded["scopes"] == scopes
        assert loaded["token"] == "fresh"

    def test_token_file_permissions(self, token_manager, tmp_config):
        token_manager.save_token("secure", {"token": "secret"})
        path = tmp_config / "tokens" / "secure.json"
        assert oct(path.stat().st_mode & 0o777) == "0o600"
