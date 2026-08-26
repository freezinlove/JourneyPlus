from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit

from selectolax.parser import HTMLParser, Node

from journeyplus.buy_points.contracts import (
    BuyPointsCategory,
    BuyPointsDiagnostic,
    BuyPointsEvidence,
    BuyPointsOfferKind,
    ParsedBuyPointsOffer,
    ParsedBuyPointsPage,
)
from journeyplus.content.urls import canonicalize_url


AWARDWALLET_BUY_POINTS_URL = (
    "https://awardwallet.com/news/current-promotions-buy-points-miles/"
)
BUY_POINTS_PARSER_VERSION = "awardwallet-buy-points-v1"

SECTION_IDS: tuple[tuple[str, BuyPointsCategory], ...] = (
    ("Buy_Miles_Promotions_From_Airlines", BuyPointsCategory.AIRLINE),
    ("Buy_Points_Promotions_From_Hotels", BuyPointsCategory.HOTEL),
    ("Buy_Points_Promotions_From_Other_Transportation", BuyPointsCategory.OTHER),
)

_SPACE_RE = re.compile(r"\s+")
_COUNT_RE = re.compile(r"^\s*(\d+)\s+Current\b", re.IGNORECASE)
_PERCENT_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)\s*%")
_RATE_RE = re.compile(
    r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:¢|cents?)(?:\s*/?\s*(?:point|mile))?",
    re.IGNORECASE,
)


class BuyPointsParseError(ValueError):
    """The page cannot be trusted as a complete buy-points inventory."""


def parse_awardwallet_buy_points(
    raw_html: str,
    *,
    page_url: str = AWARDWALLET_BUY_POINTS_URL,
) -> ParsedBuyPointsPage:
    if not raw_html.strip():
        raise BuyPointsParseError("AwardWallet page HTML is empty")

    tree = HTMLParser(raw_html)
    page_title = _required_text(
        tree.css_first("h1"), "page title", max_length=1000
    )
    advertised_count = _advertised_count(page_title)
    page_modified_at = _page_modified_at(tree)
    diagnostics: list[BuyPointsDiagnostic] = []
    offers: list[ParsedBuyPointsOffer] = []
    section_counts: dict[BuyPointsCategory, int] = {}

    for section_id, category in SECTION_IDS:
        heading_anchor = tree.css_first(f"#{section_id}")
        if heading_anchor is None:
            raise BuyPointsParseError(f"Required section is missing: {section_id}")
        table = _next_purchase_table(heading_anchor)
        if table is None:
            raise BuyPointsParseError(
                f"Required promotion table is missing after section: {section_id}"
            )
        rows = [
            row
            for row in table.css(".pt-row")
            if row.css_first(".pt-head") is None
        ]
        section_counts[category] = len(rows)
        for row_index, row in enumerate(rows, start=1):
            offers.append(
                _parse_main_row(
                    row,
                    section_id=section_id,
                    category=category,
                    row_index=row_index,
                    page_url=page_url,
                )
            )

    duplicate_keys = _duplicates(item.offer_key for item in offers)
    if duplicate_keys:
        raise BuyPointsParseError(
            "Duplicate stable offer identity: " + ", ".join(duplicate_keys)
        )

    top_table = tree.css_first("#tablepress-1310")
    if top_table is None:
        diagnostics.append(
            BuyPointsDiagnostic(
                code="TOP_TABLE_ABSENT",
                message=(
                    "Optional top-offers table was absent; the complete main inventory "
                    "was parsed without top-pick enrichment."
                ),
            )
        )
    else:
        offers = _enrich_top_offers(top_table, offers, page_url=page_url)

    parsed_count = len(offers)
    if advertised_count is not None and advertised_count != parsed_count:
        raise BuyPointsParseError(
            f"Advertised offer count {advertised_count} does not match parsed count "
            f"{parsed_count}"
        )
    if parsed_count == 0 and advertised_count != 0:
        raise BuyPointsParseError(
            "Zero parsed offers require an explicit zero-count title signal"
        )

    signatures = sorted(item.material_signature for item in offers)
    offers_signature = _sha256_json(signatures)
    return ParsedBuyPointsPage(
        page_title=page_title,
        page_modified_at=page_modified_at,
        advertised_offer_count=advertised_count,
        section_counts=section_counts,
        parsed_offer_count=parsed_count,
        offers_signature=offers_signature,
        diagnostics=diagnostics,
        offers=offers,
    )


def _parse_main_row(
    row: Node,
    *,
    section_id: str,
    category: BuyPointsCategory,
    row_index: int,
    page_url: str,
) -> ParsedBuyPointsOffer:
    context = f"{section_id} row {row_index}"
    program_node = row.css_first(".pt-program")
    offer_node = row.css_first(".pt-comment")
    deadline_node = row.css_first(".pt-date")
    posting_node = row.css_first(".pt-avg")
    action_node = row.css_first(".pt-how")
    program_name = _required_text(program_node, f"{context} program", max_length=500)
    offer_text = _required_text(offer_node, f"{context} offer", max_length=2000)
    if deadline_node is None or posting_node is None or action_node is None:
        raise BuyPointsParseError(f"{context} is missing a required column")

    deadline_raw = _optional_text(deadline_node, max_length=200)
    deadline_date = _parse_optional_date(deadline_raw, context=f"{context} deadline")
    posting_time_raw = _optional_text(posting_node, max_length=200)
    detail_href_raw = _first_href(offer_node)
    action_href_raw = _first_href(action_node)
    detail_url = _absolute_url(detail_href_raw, page_url=page_url)
    action_url = _absolute_url(action_href_raw, page_url=page_url)
    if action_url is None:
        raise BuyPointsParseError(f"{context} has no purchase URL")
    offer_kind, max_percent = _parse_offer_terms(offer_text, context=context)
    offer_key = _offer_key(
        category=category,
        program_name=program_name,
        detail_url=detail_url,
        action_url=action_url,
    )
    evidence = BuyPointsEvidence(
        section_id=section_id,
        program_text=program_name,
        offer_text=offer_text,
        deadline_text=deadline_raw,
        posting_time_text=posting_time_raw,
        detail_href_raw=detail_href_raw,
        action_href_raw=action_href_raw,
    )
    material = {
        "offer_key": offer_key,
        "category": category.value,
        "program_name": program_name,
        "offer_text": offer_text,
        "offer_kind": offer_kind.value,
        "max_percent": str(max_percent),
        "purchase_rate_raw": None,
        "purchase_rate_cents": None,
        "deadline_raw": deadline_raw,
        "deadline_date": deadline_date.isoformat() if deadline_date else None,
        "posting_time_raw": posting_time_raw,
        "detail_url": detail_url,
        "action_url": action_url,
        "top_pick": False,
    }
    return ParsedBuyPointsOffer(
        **material,
        material_signature=_sha256_json(material),
        evidence=evidence,
    )


def _enrich_top_offers(
    table: Node,
    offers: list[ParsedBuyPointsOffer],
    *,
    page_url: str,
) -> list[ParsedBuyPointsOffer]:
    enriched = list(offers)
    for row_index, row in enumerate(table.css("tbody tr"), start=1):
        cells = row.css("td")
        if len(cells) < 5:
            raise BuyPointsParseError(
                f"Top offers row {row_index} does not contain five columns"
            )
        program_text = _required_text(
            cells[0], f"top offers row {row_index} program", max_length=500
        )
        promotion_text = _required_text(
            cells[1], f"top offers row {row_index} promotion", max_length=1000
        )
        _parse_offer_terms(promotion_text, context=f"top offers row {row_index}")
        purchase_rate_raw = _required_text(
            cells[2], f"top offers row {row_index} purchase rate", max_length=200
        )
        purchase_rate_cents = _parse_purchase_rate(
            purchase_rate_raw, context=f"top offers row {row_index} purchase rate"
        )
        top_deadline = _optional_text(cells[3], max_length=200)
        _parse_optional_date(
            top_deadline, context=f"top offers row {row_index} deadline"
        )
        action_href_raw = _first_href(cells[4])
        action_url = _absolute_url(action_href_raw, page_url=page_url)

        candidates: list[int] = []
        if action_url is not None:
            action_identity = _url_identity(action_url)
            candidates = [
                index
                for index, offer in enumerate(enriched)
                if offer.action_url is not None
                and _url_identity(str(offer.action_url)) == action_identity
            ]
        if not candidates:
            normalized_program = _normalize_program(program_text)
            candidates = [
                index
                for index, offer in enumerate(enriched)
                if _normalize_program(offer.program_name) == normalized_program
            ]
        if len(candidates) != 1:
            reason = "unmatched" if not candidates else "ambiguous"
            raise BuyPointsParseError(
                f"Top offers row {row_index} is {reason}: {program_text}"
            )

        index = candidates[0]
        existing = enriched[index]
        if existing.top_pick:
            raise BuyPointsParseError(
                f"Top offers row {row_index} duplicates main offer {existing.offer_key}"
            )
        evidence = existing.evidence.model_copy(
            update={
                "top_program_text": program_text,
                "purchase_rate_text": purchase_rate_raw,
            }
        )
        material = _offer_material(existing)
        material.update(
            {
                "purchase_rate_raw": purchase_rate_raw,
                "purchase_rate_cents": str(purchase_rate_cents),
                "top_pick": True,
            }
        )
        enriched[index] = existing.model_copy(
            update={
                "purchase_rate_raw": purchase_rate_raw,
                "purchase_rate_cents": purchase_rate_cents,
                "top_pick": True,
                "material_signature": _sha256_json(material),
                "evidence": evidence,
            }
        )
    return enriched


def _offer_material(offer: ParsedBuyPointsOffer) -> dict[str, object]:
    return {
        "offer_key": offer.offer_key,
        "category": offer.category.value,
        "program_name": offer.program_name,
        "offer_text": offer.offer_text,
        "offer_kind": offer.offer_kind.value,
        "max_percent": str(offer.max_percent),
        "purchase_rate_raw": offer.purchase_rate_raw,
        "purchase_rate_cents": (
            str(offer.purchase_rate_cents) if offer.purchase_rate_cents else None
        ),
        "deadline_raw": offer.deadline_raw,
        "deadline_date": offer.deadline_date.isoformat() if offer.deadline_date else None,
        "posting_time_raw": offer.posting_time_raw,
        "detail_url": str(offer.detail_url) if offer.detail_url else None,
        "action_url": str(offer.action_url) if offer.action_url else None,
        "top_pick": offer.top_pick,
    }


def _parse_offer_terms(
    text: str, *, context: str
) -> tuple[BuyPointsOfferKind, Decimal]:
    lowered = text.casefold()
    kinds = {
        BuyPointsOfferKind.BONUS if "bonus" in lowered else None,
        BuyPointsOfferKind.DISCOUNT if "discount" in lowered else None,
    } - {None}
    percentages = [_decimal(match.group(1), context=context) for match in _PERCENT_RE.finditer(text)]
    if len(kinds) != 1 or not percentages:
        raise BuyPointsParseError(
            f"{context} must contain one bonus/discount kind and a percentage: {text}"
        )
    return next(iter(kinds)), max(percentages)


def _parse_purchase_rate(text: str, *, context: str) -> Decimal:
    matches = list(_RATE_RE.finditer(text))
    if len(matches) != 1:
        raise BuyPointsParseError(f"{context} is not a supported cents rate: {text}")
    value = _decimal(matches[0].group(1), context=context)
    if value <= 0:
        raise BuyPointsParseError(f"{context} must be positive: {text}")
    return value


def _parse_optional_date(value: str | None, *, context: str) -> date | None:
    if value is None:
        return None
    for pattern in ("%m/%d/%y", "%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    raise BuyPointsParseError(f"{context} is not a supported date: {value}")


def _page_modified_at(tree: HTMLParser) -> datetime | None:
    node = tree.css_first('meta[property="article:modified_time"]')
    if node is None:
        return None
    value = (node.attributes.get("content") or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BuyPointsParseError(
            f"article:modified_time is not ISO 8601: {value}"
        ) from exc


def _advertised_count(title: str) -> int | None:
    match = _COUNT_RE.search(title)
    return int(match.group(1)) if match else None


def _next_purchase_table(anchor: Node) -> Node | None:
    current = anchor.parent if anchor.parent is not None else anchor
    while current is not None:
        current = current.next
        if current is None:
            return None
        classes = (current.attributes.get("class") or "").split()
        if "purchase-times" in classes and "purchase-times--date" in classes:
            return current
        nested = current.css_first(".purchase-times.purchase-times--date")
        if nested is not None:
            return nested
        if current.tag in {"h1", "h2"}:
            return None
    return None


def _required_text(node: Node | None, context: str, *, max_length: int) -> str:
    value = _optional_text(node, max_length=max_length)
    if value is None:
        raise BuyPointsParseError(f"Required {context} is empty")
    return value


def _optional_text(node: Node | None, *, max_length: int) -> str | None:
    if node is None:
        return None
    value = _SPACE_RE.sub(" ", node.text(separator=" ", strip=True)).strip()
    if not value:
        return None
    if len(value) > max_length:
        raise BuyPointsParseError(f"Field exceeds {max_length} characters")
    return value


def _first_href(node: Node | None) -> str | None:
    link = node.css_first("a[href]") if node is not None else None
    if link is None:
        return None
    value = (link.attributes.get("href") or "").strip()
    return value or None


def _absolute_url(href: str | None, *, page_url: str) -> str | None:
    if href is None:
        return None
    value = canonicalize_url(urljoin(page_url, href))
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise BuyPointsParseError(f"Unsupported URL: {href}")
    return value


def _offer_key(
    *,
    category: BuyPointsCategory,
    program_name: str,
    detail_url: str | None,
    action_url: str | None,
) -> str:
    if detail_url:
        return f"detail:{_url_identity(detail_url)}"
    if action_url:
        return f"action:{_url_identity(action_url)}"
    normalized = _normalize_program(program_name)
    digest = hashlib.sha256(normalized.encode()).hexdigest()[:24]
    return f"program:{category.value.casefold()}:{digest}"


def _url_identity(url: str) -> str:
    parsed = urlsplit(canonicalize_url(url))
    path = parsed.path.rstrip("/") or "/"
    return f"{(parsed.hostname or '').casefold()}{path}"


def _normalize_program(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _decimal(value: str, *, context: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise BuyPointsParseError(f"{context} contains an invalid number: {value}") from exc


def _duplicates(values: Iterable[str]) -> list[str]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return sorted(key for key, count in counts.items() if count > 1)


def _sha256_json(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()
