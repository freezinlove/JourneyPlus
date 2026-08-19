from __future__ import annotations

import stat
from datetime import UTC, datetime, timedelta

import pytest
from google.oauth2.credentials import Credentials

from journeyplus.config import Settings
from journeyplus.sources.gmail import GMAIL_READONLY_SCOPE
from journeyplus.sources.gmail_auth import authorize_gmail, load_gmail_access_token


def _credentials() -> Credentials:
    return Credentials(
        token="test-access-token",
        refresh_token="test-refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="test-client",
        client_secret="test-secret",
        scopes=[GMAIL_READONLY_SCOPE],
        expiry=datetime.now(UTC) + timedelta(hours=1),
    )


def test_authorization_saves_restricted_token_and_loads_it(tmp_path) -> None:
    client_file = tmp_path / "client.json"
    token_file = tmp_path / "token.json"
    client_file.write_text("{}")
    settings = Settings(
        gmail_client_secret_file=str(client_file),
        gmail_token_file=str(token_file),
    )
    issued: dict = {}

    def issuer(path, scopes):
        issued["path"] = path
        issued["scopes"] = scopes
        return _credentials()

    account = authorize_gmail(
        settings,
        credential_issuer=issuer,
        profile_lookup=lambda _token: "kirikoomiku@gmail.com",
    )

    assert account == "kirikoomiku@gmail.com"
    assert issued["scopes"] == [GMAIL_READONLY_SCOPE]
    assert stat.S_IMODE(client_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    assert load_gmail_access_token(
        settings, profile_lookup=lambda _token: "kirikoomiku@gmail.com"
    ) == "test-access-token"


def test_authorization_rejects_the_wrong_google_account(tmp_path) -> None:
    client_file = tmp_path / "client.json"
    token_file = tmp_path / "token.json"
    client_file.write_text("{}")
    settings = Settings(
        gmail_client_secret_file=str(client_file),
        gmail_token_file=str(token_file),
    )
    with pytest.raises(PermissionError, match="expected kirikoomiku@gmail.com"):
        authorize_gmail(
            settings,
            credential_issuer=lambda _path, _scopes: _credentials(),
            profile_lookup=lambda _token: "wrong@gmail.com",
        )
    assert not token_file.exists()
