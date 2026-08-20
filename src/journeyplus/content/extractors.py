from __future__ import annotations

import re
from html import escape
from urllib.parse import urljoin

from selectolax.parser import HTMLParser, Node

from journeyplus.content.urls import canonicalize_url


class ContentExtractionError(ValueError):
    pass


_ARTICLE_SELECTORS = {
    "ffb_elite_status_feed": ".entry-content",
    "awardwallet_elite_status_feed": "article",
}

_ARTICLE_TITLE_SELECTORS = {
    "ffb_elite_status_feed": "h1.entry-title",
    "awardwallet_elite_status_feed": "h1.page-learn__hero-title",
}

_SOURCE_EXCLUDED_SELECTORS = {
    "ffb_elite_status_feed": (
        ".sfsi_Sicons",
        ".sharedaddy",
        ".addtoany_share_save_container",
        "#jp-relatedposts",
    ),
    "awardwallet_elite_status_feed": (
        "#preDisclosure",
        "#notAvailableOfferOnSite",
        "#ftoc",
        ".adwrap",
        ".adwrap-pre",
        ".compare-cards-wrap",
        "p.remark",
    ),
}

_FEED_SOURCE_IDS = {
    "loyaltylobby_feed",
    "frequentmiler_elite_status_feed",
    "verylvke_feed",
}


def extract_source_html(
    *,
    source_id: str,
    content_strategy: str | None,
    html: str,
    canonical_url: str,
    title: str | None = None,
) -> str:
    if content_strategy == "fetch_article":
        return _extract_article(
            source_id=source_id,
            html=html,
            canonical_url=canonical_url,
            fallback_title=title,
        )
    if source_id in _FEED_SOURCE_IDS and content_strategy in {
        "feed_body_only",
        "feed_body_only_multi_hint",
    }:
        return _extract_feed_body(
            source_id=source_id,
            html=html,
            canonical_url=canonical_url,
            title=title,
        )
    return html


def html_links(html: str, base_url: str) -> list[tuple[str, str]]:
    tree = HTMLParser(html)
    links: list[tuple[str, str]] = []
    for node in tree.css("a[href]"):
        label = _normalized_text(node)
        raw_href = str(node.attributes.get("href") or "").strip()
        if not raw_href:
            continue
        href = urljoin(base_url, raw_href)
        links.append((label, href))
    return links


def _extract_article(
    *, source_id: str, html: str, canonical_url: str, fallback_title: str | None
) -> str:
    selector = _ARTICLE_SELECTORS.get(source_id)
    if selector is None:
        raise ContentExtractionError(
            f"No article extraction rule configured for {source_id}"
        )
    tree = HTMLParser(html)
    article = tree.css_first(selector)
    if article is None:
        raise ContentExtractionError(
            f"Expected article selector {selector!r} for {source_id}"
        )
    for excluded in _SOURCE_EXCLUDED_SELECTORS.get(source_id, ()):
        for node in article.css(excluded):
            node.decompose()
    if source_id == "ffb_elite_status_feed":
        for paragraph in article.css("p"):
            text = _normalized_text(paragraph).casefold()
            if text.startswith(("image via ", "images via ", "image courtesy of ")):
                paragraph.decompose()
        _annotate_image_only_groups(article)
    _make_links_absolute(article, canonical_url)
    title_selector = _ARTICLE_TITLE_SELECTORS.get(source_id)
    title_node = tree.css_first(title_selector) if title_selector else None
    resolved_title = _normalized_text(title_node) if title_node is not None else ""
    return _with_title(resolved_title or fallback_title, article.html)


def _extract_feed_body(
    *, source_id: str, html: str, canonical_url: str, title: str | None
) -> str:
    tree = HTMLParser(html)
    root = tree.body or tree.root
    if root is None:
        raise ContentExtractionError(f"Feed body for {source_id} has no HTML root")
    for selector in (".sharethis-inline-share-buttons", ".sharedaddy"):
        for node in root.css(selector):
            node.decompose()
    if source_id in {"frequentmiler_elite_status_feed", "verylvke_feed"}:
        for paragraph in root.css("p"):
            text = _normalized_text(paragraph).casefold()
            if text.startswith("the post ") and (
                " appeared first on " in text or " first appeared on " in text
            ):
                paragraph.decompose()
    if source_id == "loyaltylobby_feed":
        for paragraph in root.css("p"):
            anchors = paragraph.css("a[href]")
            if _normalized_text(paragraph).casefold() != "source" or len(anchors) != 1:
                continue
            target = canonicalize_url(
                urljoin(canonical_url, anchors[0].attributes["href"]),
                extra_drop={"omhide"},
            )
            if target == canonicalize_url(canonical_url, extra_drop={"omhide"}):
                paragraph.decompose()
    if source_id == "frequentmiler_elite_status_feed":
        for selector in (
            ".FMtipL",
            ".FMtipR",
            ".BOfyv",
            ".BOban",
            ".BOcta",
            ".BOline small",
        ):
            for node in root.css(selector):
                node.decompose()
    _make_links_absolute(root, canonical_url)
    body_html = root.html
    if source_id == "frequentmiler_elite_status_feed":
        body_html = re.sub(r"<![–-]{2}.*?-->", "", body_html, flags=re.S)
    return _with_title(title, body_html)


def _with_title(title: str | None, body_html: str) -> str:
    normalized = " ".join((title or "").split())
    if not normalized:
        return body_html
    return f"<article><h1>{escape(normalized)}</h1>{body_html}</article>"


def _normalized_text(node: Node | None) -> str:
    if node is None:
        return ""
    return " ".join(node.text(separator=" ", strip=True).split())


def _make_links_absolute(node: Node, base_url: str) -> None:
    for link in node.css("a[href]"):
        href = str(link.attributes.get("href") or "").strip()
        if href:
            link.attrs["href"] = urljoin(base_url, href)


def _annotate_image_only_groups(article: Node) -> None:
    for paragraph in article.css("p"):
        images = paragraph.css("img")
        if len(images) < 2 or _normalized_text(paragraph):
            continue
        previous = paragraph.prev
        while previous is not None and previous.tag == "-text":
            previous = previous.prev
        context = _normalized_text(previous) if previous is not None else ""
        label = context or "正文图片组"
        images[0].attrs["alt"] = f"{label}（图片文字未提取）"
