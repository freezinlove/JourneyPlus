from __future__ import annotations

import re
from urllib.parse import urlsplit

from selectolax.parser import HTMLParser

from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.sources.base import Fetcher
from journeyplus.sources.statusmatch_links import is_project_statusmatch_host


_TERMS_COMMON_HEADING_RE = re.compile(
    r"<(?P<tag>h[1-6]|strong|b)\b[^>]*>\s*"
    r"(?:<[^>]+>\s*)*StatusMatch\.Com\s+Terms\s+of\s+Use\s*"
    r"(?:</[^>]+>\s*)*</(?P=tag)\s*>",
    re.I | re.S,
)
_CLOSURE_TEXT_RE = re.compile(
    r"(?:"
    r"register\s+your\s+interest\s+(?:in|for)\s+(?:a\s+)?future\s+status\s+"
    r"(?:match|opportunit(?:y|ies))"
    r"|waitlist\s+for\s+future\s+opportunit(?:y|ies)"
    r"|awaiting\s+(?:new|future)\s+offers?"
    r"|no\s+(?:active|current)\s+(?:status\s+match\s+)?offers?"
    r"|this\s+(?:status\s+match\s+)?offer\s+(?:has\s+)?(?:ended|expired)"
    r")",
    re.I,
)


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
    from journeyplus.statusmatch.transport import is_challenge
    if is_challenge(response.body):
        raise ValueError("StatusMatch page returned a bot challenge")
    page_kind = str(item.raw_metadata.get("page_kind") or "")
    body = response.body
    terms_scope: str | None = None
    if page_kind == "terms":
        body, terms_scope = scope_statusmatch_terms_html(body)
    return RawDocument(
        source_id=item.source_id,
        external_id=item.external_id,
        canonical_url=item.canonical_url,
        body=body,
        content_type=response.content_type,
        storage_mode="permitted_snapshot",
        metadata={
            "content_strategy": "statusmatch_page",
            "document_role": "linked_statusmatch_page",
            "page_kind": page_kind,
            "project_host": requested_host,
            "managed_statusmatch_snapshot": True,
            "final_url": response.final_url,
            "title": item.title,
            **({"terms_scope": terms_scope} if terms_scope is not None else {}),
        },
    )


def scope_statusmatch_terms_html(body: str) -> tuple[str, str]:
    """Return only project-specific TERMS content before anything is persisted."""
    match = _TERMS_COMMON_HEADING_RE.search(body)
    if match is not None:
        return body[: match.start()], "project_specific"
    tree = HTMLParser(body)
    for selector in ("script", "style", "noscript", "svg", "iframe"):
        for node in tree.css(selector):
            node.decompose()
    root = tree.body or tree.root
    text = " ".join(root.text(separator=" ", strip=True).split()) if root else ""
    if _CLOSURE_TEXT_RE.search(text):
        return body, "closure_landing"
    raise ValueError("Active StatusMatch TERMS page has no public-terms boundary")
