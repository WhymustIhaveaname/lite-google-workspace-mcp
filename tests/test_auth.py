from unittest.mock import patch

import pytest

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

    def test_token_file_permissions(self, token_manager, tmp_config):
        token_manager.save_token("secure", {"token": "secret"})
        path = tmp_config / "tokens" / "secure.json"
        assert oct(path.stat().st_mode & 0o777) == "0o600"
