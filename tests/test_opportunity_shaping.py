from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from journeyplus.contracts import (
    ApplicationRoute,
    EvidenceRef,
    FactField,
    FactSet,
    OpportunityKind,
    RoutePrice,
    RoutePriceAvailability,
)
from journeyplus.opportunity_shaping import (
    ChinaRegionAdvisory,
    china_region_advisory,
    effective_route_prices,
    opportunity_kind_for_facts,
    parse_route_prices,
    with_legacy_opportunity_kind,
)


def _evidence() -> EvidenceRef:
    return EvidenceRef(
        document_version_id=uuid4(),
        source_url="https://example.com/terms",
        locator="price table",
    )


def test_opportunity_kind_has_exactly_two_values_and_legacy_is_conservative() -> None:
    assert {item.value for item in OpportunityKind} == {"STATUS_MATCH", "OTHER"}
    mapping_payload = {
        "status_mappings": [{"legacy": "presence is sufficient for classification"}],
    }
    card_payload = {
        "what_happened": {"value": "Credit card grants complimentary Gold"},
        "status_mappings": [{"legacy": "must not override the card marker"}],
    }

    assert opportunity_kind_for_facts(mapping_payload) == OpportunityKind.STATUS_MATCH
    assert opportunity_kind_for_facts(card_payload) == OpportunityKind.OTHER
    assert opportunity_kind_for_facts({}) == OpportunityKind.OTHER
    assert (
        opportunity_kind_for_facts(card_payload, managed_statusmatch=True)
        == OpportunityKind.STATUS_MATCH
    )
    assert with_legacy_opportunity_kind(mapping_payload)["opportunity_kind"] == "STATUS_MATCH"


def test_route_price_allows_evidence_and_never_invents_unavailable_amount() -> None:
    evidence = _evidence()
    price = RoutePrice(
        target_tier="Gold",
        amount=Decimal("129.50"),
        currency="USD",
        availability=RoutePriceAvailability.AVAILABLE,
        raw_text="Gold: USD 129.50",
        evidence=[evidence],
    )
    assert price.amount == Decimal("129.50")

    with pytest.raises(ValidationError, match="ISO currency"):
        RoutePrice(
            amount=Decimal("99"),
            raw_text="99",
            evidence=[evidence],
        )
    with pytest.raises(ValidationError, match="cannot expose"):
        RoutePrice(
            amount=Decimal("99"),
            currency="USD",
            availability=RoutePriceAvailability.UNAVAILABLE,
            raw_text="not available",
            evidence=[evidence],
        )


def test_legacy_cost_parser_preserves_tiers_currencies_unavailable_and_raw_text() -> None:
    evidence = _evidence()
    parsed = parse_route_prices(
        "Gold: USD 99; Platinum: EUR 149; Diamond: unavailable",
        evidence=[evidence],
    )

    assert [(item.target_tier, item.currency, item.amount) for item in parsed[:2]] == [
        ("Gold", "USD", Decimal("99")),
        ("Platinum", "EUR", Decimal("149")),
    ]
    assert parsed[2].availability == RoutePriceAvailability.UNAVAILABLE
    assert parsed[2].amount is None
    assert parsed[2].raw_text == "Diamond: unavailable"


def test_common_price_is_inherited_by_route_without_overwriting_raw_cost() -> None:
    evidence = _evidence()
    route = ApplicationRoute(
        scope="China application",
        eligibility="Existing elite status",
        evidence=[evidence],
    )

    prices = effective_route_prices(
        route,
        common_cost="Gold: CNY 699; Platinum: CNY 999",
        common_evidence=[evidence],
    )

    assert [item.amount for item in prices] == [Decimal("699"), Decimal("999")]
    assert route.cost is None
    assert route.prices == []


def test_china_region_is_advisory_only() -> None:
    assert china_region_advisory("Worldwide") == ChinaRegionAdvisory.EXPLICITLY_INCLUDED
    assert (
        china_region_advisory("All countries except China")
        == ChinaRegionAdvisory.EXPLICITLY_EXCLUDED
    )
    assert china_region_advisory("United States") == ChinaRegionAdvisory.NOT_EXPLICIT
    assert china_region_advisory(None) == ChinaRegionAdvisory.NOT_EXPLICIT


def test_legacy_fact_set_remains_readable_after_kind_extension() -> None:
    legacy = FactSet(
        event_id=uuid4(),
        what_happened=FactField(),
    ).model_dump(mode="json")
    legacy.pop("opportunity_kind")
    legacy["schema_version"] = "4"

    facts = FactSet.model_validate(with_legacy_opportunity_kind(legacy))

    assert facts.schema_version == "4"
    assert facts.opportunity_kind == OpportunityKind.OTHER
