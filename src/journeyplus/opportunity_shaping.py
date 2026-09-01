from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from journeyplus.contracts import (
    ApplicationRoute,
    EvidenceRef,
    FactSet,
    OpportunityKind,
    RoutePrice,
    RoutePriceAvailability,
)


DEFAULT_REGION = "CN"
DEFAULT_REGION_NAME = "中国"


class ChinaRegionAdvisory(StrEnum):
    EXPLICITLY_INCLUDED = "EXPLICITLY_INCLUDED"
    EXPLICITLY_EXCLUDED = "EXPLICITLY_EXCLUDED"
    NOT_EXPLICIT = "NOT_EXPLICIT"


_CARD_MARKERS = re.compile(
    r"(?:联名信用卡|信用卡赠送|credit\s+card|cobranded?\s+card|"
    r"visa\s+(?:signature|infinite)|mastercard|american\s+express|amex)",
    re.IGNORECASE,
)
_PROGRESS_MARKERS = re.compile(
    r"(?:双倍(?:定级积分|精英夜)|定级积分促销|精英夜(?:积分|促销)|"
    r"\bMQD\b|\bstatus\s+credits?\b|\belite\s+night\s+credits?\b|"
    r"\bdouble\s+(?:elite|status))",
    re.IGNORECASE,
)
_CHINA = r"(?:中国大陆|中国内地|中华人民共和国|中国|mainland\s+china|china)"
_CHINA_EXCLUDED = re.compile(
    rf"(?:除(?:了)?|排除|不包括|不含|except(?:ing)?|excluding|not\s+available\s+in)"
    rf".{{0,80}}{_CHINA}|{_CHINA}.{{0,40}}(?:不可用|不适用|excluded)",
    re.IGNORECASE,
)
_CHINA_INCLUDED = re.compile(_CHINA, re.IGNORECASE)
_GLOBAL = re.compile(
    r"(?:全球|全世界|不限(?:地区|国家)|所有国家(?:和地区)?|"
    r"\bglobal(?:ly)?\b|\bworldwide\b|\ball countries\b)",
    re.IGNORECASE,
)

_CURRENCY_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bUSD\b|US\$|美元", re.IGNORECASE), "USD"),
    (re.compile(r"\bEUR\b|€|欧元", re.IGNORECASE), "EUR"),
    (re.compile(r"\bAED\b|迪拉姆", re.IGNORECASE), "AED"),
    (re.compile(r"\bCNY\b|\bRMB\b|人民币", re.IGNORECASE), "CNY"),
    (re.compile(r"\bGBP\b|£|英镑", re.IGNORECASE), "GBP"),
    (re.compile(r"\bAUD\b|澳元", re.IGNORECASE), "AUD"),
    (re.compile(r"\bCAD\b|加元", re.IGNORECASE), "CAD"),
    (re.compile(r"\bJPY\b|日元", re.IGNORECASE), "JPY"),
)
_AMOUNT = re.compile(r"(?<![\d.])([0-9]{1,9}(?:,[0-9]{3})*(?:\.[0-9]{1,4})?)(?![\d.])")
_UNAVAILABLE = re.compile(r"(?:不可用|不可申请|不提供|unavailable|not available)", re.IGNORECASE)


def opportunity_kind_for_facts(
    raw_facts: dict[str, Any],
    *,
    summary: str = "",
    target_status: str | None = None,
    managed_statusmatch: bool = False,
) -> OpportunityKind:
    """Read an explicit kind or conservatively classify a legacy fact payload."""

    if managed_statusmatch:
        return OpportunityKind.STATUS_MATCH
    explicit = raw_facts.get("opportunity_kind")
    if explicit in {item.value for item in OpportunityKind}:
        return OpportunityKind(str(explicit))

    def value(name: str) -> str:
        item = raw_facts.get(name)
        return str(item.get("value") or "") if isinstance(item, dict) else ""

    text = " ".join(
        (
            summary,
            target_status or "",
            value("what_happened"),
            value("eligibility"),
            value("target_status"),
            value("challenge_requirements"),
            value("cost"),
        )
    )
    if _CARD_MARKERS.search(text) or _PROGRESS_MARKERS.search(text):
        return OpportunityKind.OTHER
    if raw_facts.get("status_mappings"):
        return OpportunityKind.STATUS_MATCH
    if (target_status or value("target_status")) and value("challenge_requirements"):
        return OpportunityKind.STATUS_MATCH
    return OpportunityKind.OTHER


def with_legacy_opportunity_kind(
    raw_facts: dict[str, Any],
    *,
    summary: str = "",
    target_status: str | None = None,
    managed_statusmatch: bool = False,
) -> dict[str, Any]:
    payload = dict(raw_facts)
    payload.setdefault(
        "opportunity_kind",
        opportunity_kind_for_facts(
            raw_facts,
            summary=summary,
            target_status=target_status,
            managed_statusmatch=managed_statusmatch,
        ).value,
    )
    return payload


def china_region_advisory(region: str | None) -> ChinaRegionAdvisory:
    if not region:
        return ChinaRegionAdvisory.NOT_EXPLICIT
    normalized = " ".join(region.split())
    if _CHINA_EXCLUDED.search(normalized):
        return ChinaRegionAdvisory.EXPLICITLY_EXCLUDED
    if _CHINA_INCLUDED.search(normalized) or _GLOBAL.search(normalized):
        return ChinaRegionAdvisory.EXPLICITLY_INCLUDED
    return ChinaRegionAdvisory.NOT_EXPLICIT


def effective_route_prices(
    route: ApplicationRoute,
    *,
    common_cost: str | None = None,
    common_evidence: list[EvidenceRef] | None = None,
) -> list[RoutePrice]:
    if route.prices:
        return list(route.prices)
    if route.cost:
        parsed = parse_route_prices(route.cost, evidence=route.evidence)
        if parsed:
            return parsed
    if common_cost:
        return parse_route_prices(
            common_cost,
            evidence=common_evidence or route.evidence,
        )
    return []


def parse_route_prices(
    raw_cost: str,
    *,
    evidence: list[EvidenceRef],
) -> list[RoutePrice]:
    """Conservatively parse simple tier-price clauses; raw text remains authoritative."""

    clauses = [
        item.strip(" .")
        for item in re.split(r"[;；\n]+", raw_cost)
        if item.strip(" .")
    ]
    parsed: list[RoutePrice] = []
    for clause in clauses:
        scoped = re.match(r"^([^:：]{1,120})([:：])(.*)$", clause)
        head, separator, tail = scoped.groups() if scoped else ("", "", clause)
        target_tiers = _target_tiers(head) if separator else [None]
        unavailable = _UNAVAILABLE.search(tail) is not None
        currency = _currency(tail)
        amount = _amount(tail) if currency is not None and not unavailable else None
        if unavailable:
            for tier in target_tiers:
                parsed.append(
                    RoutePrice(
                        target_tier=tier,
                        amount=None,
                        currency=None,
                        availability=RoutePriceAvailability.UNAVAILABLE,
                        raw_text=clause,
                        evidence=evidence,
                    )
                )
        elif amount is not None and currency is not None:
            for tier in target_tiers:
                parsed.append(
                    RoutePrice(
                        target_tier=tier,
                        amount=amount,
                        currency=currency,
                        availability=RoutePriceAvailability.AVAILABLE,
                        raw_text=clause,
                        evidence=evidence,
                    )
                )
    return parsed


def enriched_fact_set_routes(fact_set: FactSet) -> list[tuple[ApplicationRoute, list[RoutePrice]]]:
    common_cost = fact_set.cost.value
    common_evidence = fact_set.cost.evidence
    return [
        (
            route,
            effective_route_prices(
                route,
                common_cost=common_cost,
                common_evidence=common_evidence,
            ),
        )
        for route in fact_set.application_routes
    ]


def _currency(value: str) -> str | None:
    for pattern, currency in _CURRENCY_ALIASES:
        if pattern.search(value):
            return currency
    if "$" in value:
        return "USD"
    return None


def _amount(value: str) -> Decimal | None:
    match = _AMOUNT.search(value)
    if match is None:
        return None
    try:
        return Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def _target_tiers(value: str) -> list[str | None]:
    normalized = value.strip(" .")
    if not normalized:
        return [None]
    parts = [
        item.strip()
        for item in re.split(r"\s*(?:&|/|、|，|,|和|及)\s*", normalized)
        if item.strip()
    ]
    return parts or [normalized]
