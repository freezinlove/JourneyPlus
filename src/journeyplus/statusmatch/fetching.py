from __future__ import annotations

from urllib.parse import urlsplit

from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.sources.base import Fetcher
from journeyplus.sources.statusmatch_links import is_project_statusmatch_host


def fetch_statusmatch_page(
    item: DiscoveredItem,
    fetcher: Fetcher,
) -> RawDocument:
    requested = urlsplit(item.canonical_url)
    requested_host = (requested.hostname or "").casefold().rstrip(".")
    if not is_project_statusmatch_host(requested_host):
        raise PermissionError("Linked page is outside project StatusMatch hosts")
    response = fetcher.get(item.canonical_url)
    final = urlsplit(response.final_url)
    final_host = (final.hostname or "").casefold().rstrip(".")
    if (
        final.scheme.casefold() != "https"
        or final_host != requested_host
        or not is_project_statusmatch_host(final_host)
    ):
        raise PermissionError("StatusMatch page redirected outside its project host")
    if "html" not in response.content_type.casefold():
        raise ValueError("StatusMatch page did not return HTML")
    if len(response.body.encode("utf-8")) > 2_000_000:
        raise ValueError("StatusMatch page exceeded the 2 MB safety limit")
    folded = response.body.casefold()
    if any(
        marker in folded
        for marker in (
            "cf-chl-",
            "verify you are human",
            "checking your browser",
            "<title>just a moment",
        )
    ):
        raise ValueError("StatusMatch page returned a bot challenge")
    return RawDocument(
        source_id=item.source_id,
        external_id=item.external_id,
        canonical_url=item.canonical_url,
        body=response.body,
        content_type=response.content_type,
        storage_mode="permitted_snapshot",
        metadata={
            "content_strategy": "statusmatch_page",
            "document_role": "linked_statusmatch_page",
            "page_kind": item.raw_metadata.get("page_kind"),
            "project_host": requested_host,
            "managed_statusmatch_snapshot": True,
            "final_url": response.final_url,
            "title": item.title,
        },
    )
