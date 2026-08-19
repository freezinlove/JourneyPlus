from __future__ import annotations

import hashlib
import re

from markdownify import markdownify
from selectolax.parser import HTMLParser

from journeyplus.contracts import NormalizedDocument, RawDocument


PARSER_VERSION = "light-cleaner-v1"
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


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_space(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def lightly_clean(raw: RawDocument) -> NormalizedDocument:
    body = raw.body
    if "html" in raw.content_type.lower() or "<html" in body.lower():
        tree = HTMLParser(body)
        for selector in _EXCLUDED_SELECTORS:
            for node in tree.css(selector):
                node.decompose()
        root = tree.body or tree.root
        body = markdownify(root.html if root is not None else body, heading_style="ATX")
    normalized = _normalize_space(body)
    return NormalizedDocument(
        raw_body=raw.body,
        normalized_body=normalized,
        raw_hash=_digest(raw.body),
        normalized_hash=_digest(normalized),
        parser_version=PARSER_VERSION,
    )

