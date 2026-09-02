from __future__ import annotations

import base64
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

import httpx

from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.sources.base import Fetcher, HttpxFetcher
from journeyplus.sources.statusmatch_links import (
    extract_statusmatch_project_links,
    statusmatch_project_page_urls,
)
from journeyplus.statusmatch.watchlist import statusmatch_page_item
from journeyplus.statusmatch.fetching import fetch_statusmatch_page


GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
ACCOUNT = "kirikoomiku@gmail.com"
LABEL_NAME = "statusmatch"
RECIPIENT_ALIAS = "kirikoomiku+statusmatch@gmail.com"
QUERY = f"to:({RECIPIENT_ALIAS})"


class GmailClient(Protocol):
    def list_labels(self) -> list[dict[str, Any]]: ...

    def list_messages(self, *, label_id: str, query: str) -> list[dict[str, Any]]: ...

    def get_message(self, message_id: str) -> dict[str, Any]: ...


class GmailHistoryCursorExpired(RuntimeError):
    """The saved Gmail history ID is no longer available from Gmail."""


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

    def get_profile_history_id(self) -> str:
        response = self._client.get("/profile")
        response.raise_for_status()
        history_id = str(response.json().get("historyId") or "")
        if not history_id:
            raise ValueError("Gmail profile did not contain a historyId")
        return history_id

    def list_history_messages(
        self, *, start_history_id: str, label_id: str
    ) -> tuple[list[dict[str, Any]], str]:
        messages: list[dict[str, Any]] = []
        seen: set[str] = set()
        page_token: str | None = None
        latest_history_id = start_history_id
        while True:
            params: list[tuple[str, str]] = [
                ("startHistoryId", start_history_id),
                ("labelId", label_id),
                ("historyTypes", "messageAdded"),
                ("historyTypes", "labelAdded"),
                ("maxResults", "500"),
            ]
            if page_token:
                params.append(("pageToken", page_token))
            response = self._client.get("/history", params=params)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if response.status_code == 404:
                    raise GmailHistoryCursorExpired(start_history_id) from exc
                raise
            payload = response.json()
            latest_history_id = str(payload.get("historyId") or latest_history_id)
            for history in payload.get("history", []):
                for group in ("messagesAdded", "labelsAdded"):
                    for change in history.get(group, []):
                        message = dict(change.get("message") or {})
                        message_id = str(message.get("id") or "")
                        if message_id and message_id not in seen:
                            seen.add(message_id)
                            messages.append(message)
            page_token = payload.get("nextPageToken")
            if not page_token:
                return messages, latest_history_id

    def get_message(self, message_id: str) -> dict[str, Any]:
        response = self._client.get(f"/messages/{message_id}", params={"format": "full"})
        response.raise_for_status()
        return dict(response.json())


class GmailStatusServicesAdapter:
    source_id = "status_services_mail"

    def __init__(self, client: GmailClient, *, project_fetcher: Fetcher | None = None) -> None:
        self._client = client
        self._project_fetcher = project_fetcher or HttpxFetcher()
        self._message_cache: dict[str, dict[str, Any]] = {}
        self._label_id: str | None = None
        self._successful_message_ids: set[str] = set()
        self._watched_hosts: set[str] = set()
        self._history_id: str | None = None
        self._pending_history_id: str | None = None
        self.requires_complete_cursor_batch = False

    def configure_incremental_discovery(
        self,
        *,
        successful_message_ids: set[str],
        watched_hosts: set[str],
        discovery_cursor: str | None = None,
    ) -> None:
        self._successful_message_ids = set(successful_message_ids)
        self._watched_hosts = {
            host.casefold().rstrip(".") for host in watched_hosts
        }
        self._history_id = discovery_cursor

    def discovery_cursor_after_collection(
        self,
        *,
        considered_items: list[DiscoveredItem],
        fully_considered: bool,
    ) -> str | None:
        del considered_items
        if not fully_considered:
            return self._history_id
        return self._pending_history_id or self._history_id

    def discover(self) -> list[DiscoveredItem]:
        label_id = self._resolve_label_id()
        results: list[DiscoveredItem] = []
        projects: dict[str, set[str]] = {}
        for reference in self._message_references(label_id):
            message_id = str(reference["id"])
            if message_id in self._successful_message_ids:
                continue
            message = self._client.get_message(message_id)
            headers = _headers(message)
            label_ids = set(message.get("labelIds", []))
            if label_id not in label_ids or RECIPIENT_ALIAS.casefold() not in headers.get(
                "to", ""
            ).casefold():
                continue
            self._message_cache[message_id] = message
            body, content_type = _message_body(message.get("payload", {}))
            project_links = extract_statusmatch_project_links(
                body, content_type=content_type
            )
            for link in project_links:
                projects.setdefault(link.host, set()).update(link.labels)
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
                        "document_role": "mail_discovery",
                        "project_statusmatch_hosts": [
                            link.host for link in project_links
                        ],
                    },
                )
            )
        for host, labels in sorted(projects.items()):
            if host in self._watched_hosts:
                continue
            for page_kind, url in statusmatch_project_page_urls(host):
                item = statusmatch_page_item(
                    host=host,
                    page_kind=page_kind,
                    canonical_url=url,
                    refresh=True,
                )
                results.append(
                    item.model_copy(
                        update={
                            "raw_metadata": {
                                **item.raw_metadata,
                                "link_labels": sorted(labels),
                            }
                        }
                    )
                )
        return results

    def _message_references(self, label_id: str) -> list[dict[str, Any]]:
        get_profile_history_id = getattr(
            self._client, "get_profile_history_id", None
        )
        list_history_messages = getattr(
            self._client, "list_history_messages", None
        )
        supports_history = callable(get_profile_history_id) and callable(
            list_history_messages
        )
        self.requires_complete_cursor_batch = supports_history
        self._pending_history_id = None
        if supports_history and self._history_id:
            try:
                references, next_history_id = list_history_messages(
                    start_history_id=self._history_id,
                    label_id=label_id,
                )
            except GmailHistoryCursorExpired:
                pass
            else:
                self._pending_history_id = next_history_id
                return references
        if supports_history:
            # Capture the history ID before the full reconciliation. Events that
            # race with the list are replayed on the next incremental run.
            self._pending_history_id = get_profile_history_id()
        return self._client.list_messages(label_id=label_id, query=QUERY)

    def fetch(self, item: DiscoveredItem) -> RawDocument:
        if item.raw_metadata.get("document_role") == "linked_statusmatch_page":
            return self._fetch_statusmatch_page(item)
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
                "document_role": "mail_discovery",
            },
        )

    def _fetch_statusmatch_page(self, item: DiscoveredItem) -> RawDocument:
        return fetch_statusmatch_page(item, self._project_fetcher)

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
    if bodies["text/html"]:
        return "\n\n".join(bodies["text/html"]), "text/html"
    return "\n\n".join(bodies["text/plain"]), "text/plain"


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
