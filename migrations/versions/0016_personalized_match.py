"""add personalized status-match product data

Revision ID: 0016_personalized_match
Revises: 0015_simple_buy_points
Create Date: 2026-08-31
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "0016_personalized_match"
down_revision = "0015_simple_buy_points"
branch_labels = None
depends_on = None


_CARD_OR_PROGRESS = re.compile(
    r"(?:联名信用卡|信用卡赠送|credit\s+card|cobranded?\s+card|"
    r"visa\s+(?:signature|infinite)|mastercard|american\s+express|amex|"
    r"双倍(?:定级积分|精英夜)|定级积分促销|精英夜(?:积分|促销)|"
    r"\bMQD\b|\bstatus\s+credits?\b|\belite\s+night\s+credits?\b|"
    r"\bdouble\s+(?:elite|status))",
    re.IGNORECASE,
)
_CURRENCIES = (
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


def upgrade() -> None:
    op.create_table(
        "status_holdings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("program_key", sa.String(length=300), nullable=False),
        sa.Column("tier_key", sa.String(length=300), nullable=False),
        sa.Column("program_display_name", sa.String(length=300), nullable=False),
        sa.Column("tier_display_name", sa.String(length=300), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("program_key"),
    )

    connection = op.get_bind()
    sources = sa.table(
        "sources",
        sa.column("id", sa.String(length=100)),
        sa.column("automatic_scheduling", sa.Boolean()),
    )
    connection.execute(
        sources.update()
        .where(sources.c.id == "awardwallet_buy_points_page")
        .values(automatic_scheduling=False)
    )
    _upgrade_fact_sets(connection)
    _upgrade_article_opportunities(connection)


def downgrade() -> None:
    connection = op.get_bind()
    _downgrade_fact_sets(connection)
    _downgrade_article_opportunities(connection)
    sources = sa.table(
        "sources",
        sa.column("id", sa.String(length=100)),
        sa.column("automatic_scheduling", sa.Boolean()),
    )
    connection.execute(
        sources.update()
        .where(sources.c.id == "awardwallet_buy_points_page")
        .values(automatic_scheduling=True)
    )
    op.drop_table("status_holdings")


def _upgrade_fact_sets(connection) -> None:
    fact_sets = sa.table(
        "fact_sets",
        sa.column("id", sa.Uuid()),
        sa.column("event_id", sa.Uuid()),
        sa.column("schema_version", sa.String(length=100)),
        sa.column("facts", sa.JSON()),
    )
    events = sa.table(
        "status_events",
        sa.column("id", sa.Uuid()),
        sa.column("summary", sa.Text()),
        sa.column("target_status", sa.String(length=300)),
    )
    watches = sa.table(
        "statusmatch_watches",
        sa.column("current_event_id", sa.Uuid()),
    )
    managed = {
        row.current_event_id
        for row in connection.execute(sa.select(watches.c.current_event_id))
        if row.current_event_id is not None
    }
    for row in connection.execute(
        sa.select(
            fact_sets.c.id,
            fact_sets.c.event_id,
            fact_sets.c.facts,
            events.c.summary,
            events.c.target_status,
        ).join(events, events.c.id == fact_sets.c.event_id)
    ):
        facts = dict(row.facts) if isinstance(row.facts, dict) else {}
        facts["schema_version"] = "5"
        if row.event_id in managed:
            facts["opportunity_kind"] = "STATUS_MATCH"
        else:
            facts.setdefault(
                "opportunity_kind",
                _legacy_kind(facts, row.summary or "", row.target_status),
            )
        _backfill_prices(facts)
        connection.execute(
            fact_sets.update()
            .where(fact_sets.c.id == row.id)
            .values(schema_version="5", facts=facts)
        )


def _upgrade_article_opportunities(connection) -> None:
    opportunities = sa.table(
        "article_opportunities",
        sa.column("id", sa.Uuid()),
        sa.column("summary", sa.Text()),
        sa.column("target_status", sa.String(length=300)),
        sa.column("facts", sa.JSON()),
        sa.column("fact_signature", sa.String(length=64)),
    )
    for row in connection.execute(
        sa.select(
            opportunities.c.id,
            opportunities.c.summary,
            opportunities.c.target_status,
            opportunities.c.facts,
        )
    ):
        facts = dict(row.facts) if isinstance(row.facts, dict) else {}
        facts["schema_version"] = "5"
        facts.setdefault(
            "opportunity_kind",
            _legacy_kind(facts, row.summary or "", row.target_status),
        )
        _backfill_prices(facts)
        connection.execute(
            opportunities.update()
            .where(opportunities.c.id == row.id)
            .values(facts=facts, fact_signature=_signature(facts))
        )


def _downgrade_fact_sets(connection) -> None:
    fact_sets = sa.table(
        "fact_sets",
        sa.column("id", sa.Uuid()),
        sa.column("schema_version", sa.String(length=100)),
        sa.column("facts", sa.JSON()),
    )
    for row in connection.execute(sa.select(fact_sets.c.id, fact_sets.c.facts)):
        facts = dict(row.facts) if isinstance(row.facts, dict) else {}
        facts.pop("opportunity_kind", None)
        if facts.get("schema_version") == "5":
            facts["schema_version"] = "4"
        _remove_prices(facts)
        connection.execute(
            fact_sets.update()
            .where(fact_sets.c.id == row.id)
            .values(schema_version="4", facts=facts)
        )


def _downgrade_article_opportunities(connection) -> None:
    opportunities = sa.table(
        "article_opportunities",
        sa.column("id", sa.Uuid()),
        sa.column("facts", sa.JSON()),
        sa.column("fact_signature", sa.String(length=64)),
    )
    for row in connection.execute(
        sa.select(opportunities.c.id, opportunities.c.facts)
    ):
        facts = dict(row.facts) if isinstance(row.facts, dict) else {}
        facts.pop("opportunity_kind", None)
        if facts.get("schema_version") == "5":
            facts["schema_version"] = "4"
        _remove_prices(facts)
        connection.execute(
            opportunities.update()
            .where(opportunities.c.id == row.id)
            .values(facts=facts, fact_signature=_signature(facts))
        )


def _legacy_kind(facts: dict[str, Any], summary: str, target_status: str | None) -> str:
    def value(name: str) -> str:
        item = facts.get(name)
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
    if _CARD_OR_PROGRESS.search(text):
        return "OTHER"
    if facts.get("status_mappings"):
        return "STATUS_MATCH"
    if (target_status or value("target_status")) and value("challenge_requirements"):
        return "STATUS_MATCH"
    return "OTHER"


def _backfill_prices(facts: dict[str, Any]) -> None:
    common_cost = _field_value(facts.get("cost"))
    common_evidence = _field_evidence(facts.get("cost"))
    for route in facts.get("application_routes") or []:
        if not isinstance(route, dict):
            continue
        route.setdefault("prices", [])
        if route["prices"]:
            continue
        raw_cost = route.get("cost") or common_cost
        evidence = route.get("evidence") or common_evidence
        if isinstance(raw_cost, str) and evidence:
            route["prices"] = _parse_prices(raw_cost, evidence)


def _remove_prices(facts: dict[str, Any]) -> None:
    for route in facts.get("application_routes") or []:
        if isinstance(route, dict):
            route.pop("prices", None)


def _parse_prices(raw_cost: str, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for clause in (
        item.strip(" .")
        for item in re.split(r"[;；\n]+", raw_cost)
        if item.strip(" .")
    ):
        match = re.match(r"^([^:：]{1,120})[:：](.*)$", clause)
        head, tail = (match.group(1), match.group(2)) if match else ("", clause)
        tiers = _tiers(head)
        if _UNAVAILABLE.search(tail):
            result.extend(
                {
                    "target_tier": tier,
                    "amount": None,
                    "currency": None,
                    "availability": "UNAVAILABLE",
                    "raw_text": clause,
                    "evidence": evidence,
                }
                for tier in tiers
            )
            continue
        currency = _currency(tail)
        amount_match = _AMOUNT.search(tail) if currency else None
        if currency and amount_match:
            amount = float(amount_match.group(1).replace(",", ""))
            result.extend(
                {
                    "target_tier": tier,
                    "amount": amount,
                    "currency": currency,
                    "availability": "AVAILABLE",
                    "raw_text": clause,
                    "evidence": evidence,
                }
                for tier in tiers
            )
    return result


def _currency(value: str) -> str | None:
    for pattern, currency in _CURRENCIES:
        if pattern.search(value):
            return currency
    if "$" in value:
        return "USD"
    return None


def _tiers(value: str) -> list[str | None]:
    if not value.strip():
        return [None]
    return [
        item.strip()
        for item in re.split(r"\s*(?:&|/|、|，|,|和|及)\s*", value)
        if item.strip()
    ]


def _field_value(value: Any) -> str | None:
    return value.get("value") if isinstance(value, dict) else None


def _field_evidence(value: Any) -> list[dict[str, Any]]:
    evidence = value.get("evidence") if isinstance(value, dict) else None
    return evidence if isinstance(evidence, list) else []


def _signature(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
