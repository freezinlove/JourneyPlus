from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from journeyplus.config import Settings
from journeyplus.sources.gmail import ACCOUNT, GMAIL_READONLY_SCOPE


CredentialIssuer = Callable[[Path, list[str]], Credentials]
ProfileLookup = Callable[[str], str]


def authorize_gmail(
    settings: Settings,
    *,
    credential_issuer: CredentialIssuer | None = None,
    profile_lookup: ProfileLookup | None = None,
) -> str:
    client_secret_path = Path(settings.gmail_client_secret_file)
    if not client_secret_path.is_file():
        raise FileNotFoundError(
            f"Google OAuth client JSON was not found: {client_secret_path}"
        )
    os.chmod(client_secret_path, 0o600)
    issuer = credential_issuer or _run_installed_app_flow
    credentials = issuer(client_secret_path, [GMAIL_READONLY_SCOPE])
    if not credentials.token:
        raise RuntimeError("Google OAuth did not return an access token")
    if not credentials.has_scopes([GMAIL_READONLY_SCOPE]):
        raise PermissionError("OAuth grant does not include gmail.readonly")
    email_address = (profile_lookup or gmail_profile_email)(credentials.token)
    if email_address.casefold() != ACCOUNT.casefold():
        raise PermissionError(
            f"Authorized Gmail account is {email_address}, expected {ACCOUNT}"
        )
    _save_credentials(Path(settings.gmail_token_file), credentials)
    return email_address


def load_gmail_access_token(
    settings: Settings,
    *,
    profile_lookup: ProfileLookup | None = None,
) -> str:
    token_path = Path(settings.gmail_token_file)
    if not token_path.is_file():
        raise FileNotFoundError(
            f"Gmail OAuth token was not found: {token_path}; run gmail-authorize"
        )
    credentials = Credentials.from_authorized_user_file(
        str(token_path), [GMAIL_READONLY_SCOPE]
    )
    if not credentials.has_scopes([GMAIL_READONLY_SCOPE]):
        raise PermissionError("Stored OAuth grant does not include gmail.readonly")
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    if not credentials.valid or not credentials.token:
        raise RuntimeError("Stored Gmail OAuth credentials are invalid or expired")
    email_address = (profile_lookup or gmail_profile_email)(credentials.token)
    if email_address.casefold() != ACCOUNT.casefold():
        raise PermissionError(
            f"Stored Gmail account is {email_address}, expected {ACCOUNT}"
        )
    _save_credentials(token_path, credentials)
    return credentials.token


def gmail_profile_email(access_token: str) -> str:
    response = httpx.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/profile",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    response.raise_for_status()
    email_address = str(response.json().get("emailAddress", "")).strip()
    if not email_address:
        raise RuntimeError("Gmail profile response did not include emailAddress")
    return email_address


def _run_installed_app_flow(
    client_secret_path: Path, scopes: list[str]
) -> Credentials:
    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secret_path), scopes=scopes
    )
    return flow.run_local_server(
        host="127.0.0.1",
        port=0,
        access_type="offline",
        prompt="consent",
        open_browser=True,
    )


def _save_credentials(path: Path, credentials: Credentials) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(credentials.to_json(), encoding="utf-8")
    os.chmod(path, 0o600)
