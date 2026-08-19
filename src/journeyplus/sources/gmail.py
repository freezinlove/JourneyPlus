from __future__ import annotations

import base64
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

import httpx

from journeyplus.contracts import DiscoveredItem, RawDocument


GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
ACCOUNT = "kirikoomiku@gmail.com"
LABEL_NAME = "statusmatch"
RECIPIENT_ALIAS = "kirikoomiku+statusmatch@gmail.com"
QUERY = f"to:({RECIPIENT_ALIAS})"


class GmailClient(Protocol):
    def list_labels(self) -> list[dict[str, Any]]: ...

    def list_messages(self, *, label_id: str, query: str) -> list[dict[str, Any]]: ...

    def get_message(self, message_id: str) -> dict[str, Any]: ...


class HttpGmailClient:
    """Minimal Gmail REST client using an externally managed readonly token."""

    def __init__(self, access_token: str) -> None:
        if not access_token:
            raise ValueError("A Gmail readonly access token is required")
        self._client = httpx.Client(
            base_url="https://gmail.googleapis.com/gmail/v1/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )

    def list_labels(self) -> list[dict[str, Any]]:
        response = self._client.get("/labels")
        response.raise_for_status()
        return list(response.json().get("labels", []))

    def list_messages(self, *, label_id: str, query: str) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params = {"labelIds": label_id, "q": query, "maxResults": "500"}
            if page_token:
                params["pageToken"] = page_token
            response = self._client.get("/messages", params=params)
            response.raise_for_status()
            payload = response.json()
            messages.extend(payload.get("messages", []))
            page_token = payload.get("nextPageToken")
            if not page_token:
                return messages

    def get_message(self, message_id: str) -> dict[str, Any]:
        response = self._client.get(f"/messages/{message_id}", params={"format": "full"})
        response.raise_for_status()
        return dict(response.json())


class GmailStatusServicesAdapter:
    source_id = "status_services_mail"

    def __init__(self, client: GmailClient) -> None:
        self._client = client
        self._message_cache: dict[str, dict[str, Any]] = {}
        self._label_id: str | None = None

    def discover(self) -> list[DiscoveredItem]:
        label_id = self._resolve_label_id()
        results: list[DiscoveredItem] = []
        for reference in self._client.list_messages(label_id=label_id, query=QUERY):
            message_id = str(reference["id"])
            message = self._client.get_message(message_id)
            headers = _headers(message)
            label_ids = set(message.get("labelIds", []))
            if label_id not in label_ids or RECIPIENT_ALIAS.casefold() not in headers.get(
                "to", ""
            ).casefold():
                continue
            self._message_cache[message_id] = message
            results.append(
                DiscoveredItem(
                    source_id=self.source_id,
                    external_id=message_id,
                    discovered_url=f"gmail://{ACCOUNT}/{message_id}",
                    canonical_url=(
                        "https://mail.google.com/mail/u/0/"
                        f"?account={ACCOUNT}&message_id={message_id}"
                    ),
                    title=headers.get("subject", ""),
                    published_at=_message_date(headers.get("date")),
                    raw_metadata={
                        "gmail_message_id": message_id,
                        "rfc_message_id": headers.get("message-id"),
                        "thread_id": message.get("threadId"),
                        "to": headers.get("to"),
                        "origin_provider": _origin_provider(headers, message),
                        "label": LABEL_NAME,
                    },
                )
            )
        return results

    def fetch(self, item: DiscoveredItem) -> RawDocument:
        message = self._message_cache.pop(
            item.external_id, None
        ) or self._client.get_message(item.external_id)
        headers = _headers(message)
        if RECIPIENT_ALIAS.casefold() not in headers.get("to", "").casefold():
            raise PermissionError("Message recipient is outside the dedicated alias")
        body, content_type = _message_body(message.get("payload", {}))
        if not body.strip():
            raise ValueError(f"Gmail message {item.external_id} has no supported body")
        return RawDocument(
            source_id=self.source_id,
            external_id=item.external_id,
            canonical_url=item.canonical_url,
            body=body,
            content_type=content_type,
            storage_mode="restricted_mail_snapshot",
            metadata={
                "rfc_message_id": headers.get("message-id"),
                "origin_provider": item.raw_metadata.get("origin_provider", "UNKNOWN"),
            },
        )

    def _resolve_label_id(self) -> str:
        if self._label_id:
            return self._label_id
        for label in self._client.list_labels():
            if str(label.get("name", "")).casefold() == LABEL_NAME:
                self._label_id = str(label["id"])
                return self._label_id
        raise LookupError(f"Gmail label {LABEL_NAME!r} was not found")


def _headers(message: dict[str, Any]) -> dict[str, str]:
    return {
        str(item.get("name", "")).casefold(): str(item.get("value", ""))
        for item in message.get("payload", {}).get("headers", [])
    }


def _message_body(payload: dict[str, Any]) -> tuple[str, str]:
    bodies: dict[str, list[str]] = {"text/plain": [], "text/html": []}

    def walk(part: dict[str, Any]) -> None:
        mime = str(part.get("mimeType", "")).casefold()
        data = part.get("body", {}).get("data")
        if data and mime in bodies:
            padding = "=" * (-len(data) % 4)
            bodies[mime].append(
                base64.urlsafe_b64decode(data + padding).decode("utf-8", errors="replace")
            )
        for child in part.get("parts", []):
            walk(child)

    walk(payload)
    if bodies["text/plain"]:
        return "\n\n".join(bodies["text/plain"]), "text/plain"
    return "\n\n".join(bodies["text/html"]), "text/html"


def _message_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        result = parsedate_to_datetime(value)
        return result if result.tzinfo else result.replace(tzinfo=UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def _origin_provider(headers: dict[str, str], message: dict[str, Any]) -> str:
    value = " ".join(
        (
            headers.get("subject", ""),
            headers.get("from", ""),
            str(message.get("snippet", "")),
        )
    ).casefold()
    if "getstatus" in value:
        return "GETSTATUS"
    if "statusmatch" in value or "status match" in value:
        return "STATUSMATCH"
    return "UNKNOWN"

