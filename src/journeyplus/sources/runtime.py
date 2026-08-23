from __future__ import annotations

from journeyplus.config import Settings
from journeyplus.sources.base import SourceAdapter
from journeyplus.sources.factory import build_adapter
from journeyplus.sources.gmail import HttpGmailClient
from journeyplus.sources.gmail_auth import gmail_profile_email, load_gmail_access_token


def build_configured_adapter(
    source_id: str,
    settings: Settings,
) -> SourceAdapter:
    gmail_client = None
    if source_id == "status_services_mail":
        access_token = settings.gmail_access_token
        if access_token:
            account = gmail_profile_email(access_token)
            if account.casefold() != "kirikoomiku@gmail.com":
                raise ValueError(
                    f"Authorized Gmail account is {account}, expected "
                    "kirikoomiku@gmail.com"
                )
        else:
            access_token = load_gmail_access_token(settings)
        gmail_client = HttpGmailClient(access_token)
    return build_adapter(source_id, gmail_client=gmail_client)
