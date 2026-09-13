from __future__ import annotations

import hashlib
import re

from markdownify import markdownify
from selectolax.parser import HTMLParser

from journeyplus.content.extractors import extract_source_html
from journeyplus.content.statusmatch_history import is_statusmatch_project_page, remove_historical_fee_tables
from journeyplus.contracts import NormalizedDocument, RawDocument
from journeyplus.sources.statusmatch_links import normalized_statusmatch_mail_html


PARSER_VERSION = "source-cleaner-v5"
_EXCLUDED_SELECTORS = (
    "script",
    "style",
    "noscript",
    "svg",
    "iframe",
    "form",
    "nav",
    "footer",
    ".advertisement",
    ".cookie",
    ".social-share",
)

_GENERIC_IMAGE_ALTS = {
    "",
    "ad",
    "advertisement",
    "error",
    "image",
    "logo",
    "loading",
    "photo",
    "picture",
}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_space(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def parser_version_for_url(url: str) -> str:
    return PARSER_VERSION + ('-statusmatch-history-v1' if is_statusmatch_project_page(url) else '')


def lightly_clean(raw: RawDocument, *, exclude_historical_fees: bool = True) -> NormalizedDocument:
    input_body = raw.body
    if (
        raw.source_id == "status_services_mail"
        and raw.metadata.get("document_role") == "mail_discovery"
        and (
            "html" in raw.content_type.lower() or "<a" in raw.body.casefold()
        )
    ):
        input_body = normalized_statusmatch_mail_html(raw.body)
    body = extract_source_html(
        source_id=raw.source_id,
        content_strategy=str(raw.metadata.get("content_strategy") or "") or None,
        html=input_body,
        canonical_url=raw.canonical_url,
        title=str(raw.metadata.get("title") or "") or None,
    )
    if "html" in raw.content_type.lower() or "<html" in body.lower():
        tree = HTMLParser(body)
        for selector in _EXCLUDED_SELECTORS:
            for node in tree.css(selector):
                node.decompose()
        _normalize_volatile_links(tree)
        _replace_images(tree)
        _remove_empty_headings(tree)
        root = tree.body or tree.root
        body = markdownify(root.html if root is not None else body, heading_style="ATX")
        body = re.sub(r"<![–-]{2}.*?-->", "", body, flags=re.S)
    normalized = _normalize_space(body)
    if exclude_historical_fees and is_statusmatch_project_page(raw.canonical_url):
        normalized = remove_historical_fee_tables(normalized)
    return NormalizedDocument(
        raw_body=raw.body,
        normalized_body=normalized,
        raw_hash=_digest(raw.body),
        normalized_hash=_digest(normalized),
        parser_version=parser_version_for_url(raw.canonical_url),
    )


def _replace_images(tree: HTMLParser) -> None:
    for image in list(tree.css("img")):
        alt = " ".join(str(image.attributes.get("alt") or "").split())
        figure = _ancestor(image, "figure")
        has_caption = figure is not None and figure.css_first("figcaption") is not None
        replacement = ""
        if not has_caption and _meaningful_image_alt(alt):
            replacement = f"[图片：{alt}]"
        parent = image.parent
        if (
            parent is not None
            and parent.tag == "a"
            and not parent.text(separator=" ", strip=True)
            and len(parent.css("img")) == 1
        ):
            if replacement:
                image.replace_with(replacement)
            else:
                parent.decompose()
        elif replacement:
            image.replace_with(replacement)
        else:
            image.decompose()


def _normalize_volatile_links(tree: HTMLParser) -> None:
    """Remove Cloudflare's per-response email-protection token from page hashes."""
    for anchor in tree.css("a[href]"):
        href = str(anchor.attributes.get("href") or "")
        if re.match(
            r"^(?:https?://[^/]+)?/cdn-cgi/l/email-protection(?:[?#].*)?$",
            href,
            flags=re.IGNORECASE,
        ):
            anchor.attrs["href"] = "/cdn-cgi/l/email-protection"


def _meaningful_image_alt(alt: str) -> bool:
    lowered = alt.casefold().strip()
    if lowered in _GENERIC_IMAGE_ALTS or len(lowered) < 3:
        return False
    if lowered.startswith(("http://", "https://")):
        return False
    return True


def _ancestor(node, tag: str):
    parent = node.parent
    while parent is not None:
        if parent.tag == tag:
            return parent
        parent = parent.parent
    return None


def _remove_empty_headings(tree: HTMLParser) -> None:
    for heading in tree.css("h1, h2, h3, h4, h5, h6"):
        if not heading.text(separator=" ", strip=True):
            heading.decompose()
