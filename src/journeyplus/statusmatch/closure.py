from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from selectolax.parser import HTMLParser

from journeyplus.models import DocumentVersion, SourceItem


@dataclass(frozen=True, slots=True)
class ClosureAssessment:
    closed: bool
    reason: str | None = None
    evidence_page_kind: str | None = None


_WAITLIST_PATH_RE = re.compile(r"/(?:[^/]+/)*waitlist(?:\.php)?/?$", re.I)
_WAITLIST_TEXT_RE = re.compile(
    r"(?:"
    r"waitlist\s+for\s+future\s+opportunit(?:y|ies)"
    r"|register\s+your\s+interest\s+in\s+a\s+future\s+status\s+match"
    r"|awaiting\s+(?:new|future)\s+offers?"
    r"|no\s+(?:active|current)\s+(?:status\s+match\s+)?offers?"
    r")",
    re.I,
)
_WHOLE_ENDED_RE = re.compile(
    r"(?:"
    r"this\s+offer\s+(?:has\s+)?(?:ended|expired)\s+and\s+is\s+no\s+longer\s+available"
    r"|the\s+status\s+match\s+offer\s+has\s+ended\s+and\s+(?:is\s+)?no\s+longer\s+available"
    r"|this\s+status\s+match\s+(?:offer\s+)?(?:has\s+)?(?:ended|expired)"
    r"|applications?\s+(?:for\s+this\s+offer\s+)?(?:are|is)\s+(?:now\s+)?closed"
    r"|the\s+offer\s+is\s+no\s+longer\s+available"
    r")",
    re.I,
)
_ACTIVE_ACTION_RE = re.compile(
    r"(?:"
    r"\bapply(?:\s+(?:now|today))?\b"
    r"|\bcontinue\b"
    r"|\bget\s+started\b"
    r"|\bstart\s+(?:your\s+)?(?:application|status\s+match)\b"
    r"|\bsubmit\s+(?:your\s+)?application\b"
    r")",
    re.I,
)
_WAITLIST_ACTION_RE = re.compile(
    r"(?:waitlist|register\s+(?:your\s+)?interest|future\s+opportunit)", re.I
)


def assess_statusmatch_closure(
    *,
    activity: DocumentVersion,
    activity_item: SourceItem,
    faq: DocumentVersion,
    faq_item: SourceItem,
) -> ClosureAssessment:
    activity_text = _visible_text(activity)
    faq_text = _visible_text(faq)
    active_flow = _has_active_application_flow(activity)
    final_url = str(
        (activity_item.raw_metadata or {}).get("final_url")
        or activity.canonical_url
    )
    final_path = urlsplit(final_url).path

    if (
        _WAITLIST_PATH_RE.search(final_path)
        and _WAITLIST_TEXT_RE.search(activity_text)
        and not active_flow
    ):
        return ClosureAssessment(
            True,
            "STATUSMATCH_WAITLIST_LANDING",
            "activity",
        )
    if not active_flow and _WAITLIST_TEXT_RE.search(activity_text):
        return ClosureAssessment(
            True,
            "STATUSMATCH_AWAITING_FUTURE_OFFER",
            "activity",
        )
    if not active_flow and _WHOLE_ENDED_RE.search(activity_text):
        return ClosureAssessment(
            True,
            "STATUSMATCH_WHOLE_OFFER_ENDED",
            "activity",
        )
    if not active_flow and _WHOLE_ENDED_RE.search(faq_text):
        return ClosureAssessment(
            True,
            "STATUSMATCH_WHOLE_OFFER_ENDED",
            "faq",
        )
    return ClosureAssessment(False)


def _visible_text(document: DocumentVersion) -> str:
    if document.raw_body and (
        "html" in document.content_type.casefold()
        or "<html" in document.raw_body.casefold()
    ):
        tree = HTMLParser(document.raw_body)
        for selector in ("script", "style", "noscript", "svg", "iframe"):
            for node in tree.css(selector):
                node.decompose()
        root = tree.body or tree.root
        if root is not None:
            return " ".join(root.text(separator=" ", strip=True).split())
    return " ".join(document.normalized_body.split())


def _has_active_application_flow(document: DocumentVersion) -> bool:
    if not document.raw_body:
        return False
    tree = HTMLParser(document.raw_body)
    controls: list[str] = []
    for node in tree.css("button, input, a[href]"):
        value = " ".join(
            part
            for part in (
                node.text(separator=" ", strip=True),
                str(node.attributes.get("value") or ""),
                str(node.attributes.get("aria-label") or ""),
                str(node.attributes.get("title") or ""),
            )
            if part
        )
        value = " ".join(value.split())
        if value:
            controls.append(value)
    active_controls = [
        value
        for value in controls
        if _ACTIVE_ACTION_RE.search(value) and not _WAITLIST_ACTION_RE.search(value)
    ]
    if active_controls:
        return True
    for form in tree.css("form"):
        text = " ".join(form.text(separator=" ", strip=True).split())
        if _WAITLIST_ACTION_RE.search(text):
            continue
        if form.css_first("input[type=submit], button") is not None and (
            form.css_first("input[type=email], input[type=text], select") is not None
        ):
            return True
    return False
