from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest

from journeyplus.contracts import (
    ApplicationRoute,
    EvidenceRef,
    FactField,
    FactSet,
    RoutePrice,
    RoutePriceAvailability,
)
from journeyplus.facts.statusmatch_prices import (
    apply_statusmatch_fee_policy,
    extract_statusmatch_price_routes,
    filter_redundant_statusmatch_narrative_routes,
    merge_statusmatch_application_routes,
)
from journeyplus.models import DocumentVersion
from journeyplus.statusmatch.fetching import scope_statusmatch_terms_html


def _document(kind: str, body: str) -> DocumentVersion:
    url = (
        "https://example.statusmatch.com/"
        if kind == "activity"
        else f"https://example.statusmatch.com/{kind}"
    )
    digest = sha256(body.encode()).hexdigest()
    return DocumentVersion(
        id=uuid4(),
        source_item_id=uuid4(),
        canonical_url=url,
        raw_body=body,
        normalized_body=body,
        content_type="text/html",
        storage_mode="permitted_snapshot",
        raw_hash=digest,
        normalized_hash=digest,
        parser_version="test-v1",
        fetched_at=datetime.now(UTC),
    )


def _evidence(document: DocumentVersion, locator: str = "current fee") -> EvidenceRef:
    return EvidenceRef(
        document_version_id=document.id,
        source_url=document.canonical_url,
        locator=locator,
    )


def _facts(documents: list[DocumentVersion]) -> FactSet:
    return FactSet(
        event_id=uuid4(),
        what_happened=FactField(
            value="当前开放会籍匹配",
            evidence=[_evidence(documents[0], "current offer")],
        ),
    )


def test_terms_are_scoped_before_storage_and_closure_landing_is_preserved() -> None:
    body = """
    <html><body><h1>Project terms</h1><p>Application fee USD 99.</p>
    <h3><strong>StatusMatch.Com Terms of Use</strong></h3>
    <p>Standard Membership is free and fees may apply.</p></body></html>
    """

    scoped, scope = scope_statusmatch_terms_html(body)

    assert scope == "project_specific"
    assert "Application fee USD 99" in scoped
    assert "StatusMatch.Com Terms of Use" not in scoped
    assert "Standard Membership is free" not in scoped

    strong_body = """
    <html><body><p>Current application fee USD 49.</p><p>
    <strong>StatusMatch.Com Terms of Use </strong><br><br>
    Standard Membership is free.</p></body></html>
    """
    strong_scoped, strong_scope = scope_statusmatch_terms_html(strong_body)
    assert strong_scope == "project_specific"
    assert "Current application fee USD 49" in strong_scoped
    assert "StatusMatch.Com Terms of Use" not in strong_scoped
    assert "Standard Membership is free" not in strong_scoped

    closure, closure_scope = scope_statusmatch_terms_html(
        "<html><body>Register your interest for future status opportunities.</body></html>"
    )
    assert closure_scope == "closure_landing"
    assert "future status opportunities" in closure

    with pytest.raises(ValueError, match="no public-terms boundary"):
        scope_statusmatch_terms_html(
            "<html><body><h1>Current terms</h1><p>Applications are open.</p></body></html>"
        )


def test_fee_tables_parse_group_rows_currency_direction_and_skip_history() -> None:
    html = """
    <html><body><h1>Flying Blue Status Match Terms &amp; Conditions</h1>
    <table>
      <tr><th>Country/Region</th><th>Status Tier</th><th>Application Fee</th></tr>
      <tr><td colspan="3">Listed in EUR</td></tr>
      <tr><td colspan="3">Greece</td></tr>
      <tr><td></td><td>Silver</td><td>EUR 89</td></tr>
      <tr><td></td><td>Gold</td><td>EUR 199</td></tr>
      <tr><td></td><td>Platinum</td><td>EUR 349</td></tr>
    </table>
    <table>
      <tr><th>Country/Region</th><th>Status Tier</th><th>Application Fee</th></tr>
      <tr><td colspan="3">Listed in USD</td></tr>
      <tr><td colspan="3">Argentina, Brazil, Chile</td></tr>
      <tr><td></td><td>Silver</td><td>99 USD</td></tr>
      <tr><td></td><td>Gold</td><td>USD 299</td></tr>
      <tr><td></td><td>Platinum</td><td>USD 399<br>Not Available for Brazil</td></tr>
    </table>
    <h3>Recently ended offers</h3>
    <table>
      <tr><th>Country/Region</th><th>Status Tier</th><th>Application Fee</th></tr>
      <tr><td>China</td><td>Silver</td><td>USD 999</td></tr>
    </table>
    </body></html>
    """
    document = _document("terms", html)

    routes = extract_statusmatch_price_routes(
        raw_html=html,
        canonical_url=document.canonical_url,
        document_version_id=document.id,
    )

    assert [route.scope for route in routes] == [
        "Greece",
        "Argentina, Chile",
        "Brazil",
    ]
    assert [price.amount for price in routes[0].prices] == [89, 199, 349]
    assert all(price.currency == "EUR" for price in routes[0].prices)
    assert routes[1].prices[0].amount == 99
    assert routes[1].prices[0].currency == "USD"
    assert routes[1].prices[-1].amount == 399
    assert routes[1].prices[-1].availability == RoutePriceAvailability.AVAILABLE
    assert routes[2].region == "Brazil"
    assert routes[2].prices[-1].amount is None
    assert routes[2].prices[-1].availability == RoutePriceAvailability.UNAVAILABLE
    assert "Not Available for Brazil" in routes[2].prices[-1].raw_text
    assert all(price.amount != 999 for route in routes for price in route.prices)


def test_fee_table_marks_unavailable_target_without_amount() -> None:
    html = """
    <html><body><h2>Hotel Status Match</h2><table>
      <tr><th>Country/Region</th><th>Status Tier</th><th>Application Fee (USD)</th></tr>
      <tr><td>All eligible countries</td><td>Gold</td><td>299 USD</td></tr>
      <tr><td></td><td>Platinum</td><td>Not Available</td></tr>
    </table></body></html>
    """
    document = _document("terms", html)

    routes = extract_statusmatch_price_routes(
        raw_html=html,
        canonical_url=document.canonical_url,
        document_version_id=document.id,
    )

    assert len(routes) == 1
    assert routes[0].prices[0].amount == 299
    assert routes[0].prices[0].currency == "USD"
    assert routes[0].prices[1].amount is None
    assert routes[0].prices[1].availability == RoutePriceAvailability.UNAVAILABLE


def test_fee_table_accepts_program_specific_tier_header() -> None:
    html = """
    <html><body><table>
      <tr><td><strong>Enrich Tier</strong></td><td><strong>Application Fee</strong></td></tr>
      <tr><td>Silver</td><td>USD 89</td></tr>
      <tr><td>Gold</td><td>USD 199</td></tr>
      <tr><td>Platinum</td><td>USD 349</td></tr>
    </table></body></html>
    """
    document = _document("faq", html)

    routes = extract_statusmatch_price_routes(
        raw_html=html,
        canonical_url=document.canonical_url,
        document_version_id=document.id,
    )

    assert len(routes) == 1
    assert [price.amount for price in routes[0].prices] == [89, 199, 349]
    assert [price.target_tier for price in routes[0].prices] == [
        "Silver",
        "Gold",
        "Platinum",
    ]


def test_fee_route_merge_combines_equal_evidence_and_marks_real_conflicts() -> None:
    faq = _document("faq", "FAQ")
    terms = _document("terms", "TERMS")

    def route(document: DocumentVersion, amount: int) -> ApplicationRoute:
        evidence = _evidence(document, f"Gold USD {amount}")
        return ApplicationRoute(
            scope="Greece",
            region="Greece",
            prices=[
                RoutePrice(
                    target_tier="Gold",
                    amount=amount,
                    currency="USD",
                    availability="AVAILABLE",
                    raw_text=f"USD {amount}",
                    evidence=[evidence],
                )
            ],
            evidence=[evidence],
        )

    same = merge_statusmatch_application_routes([route(faq, 99)], [route(terms, 99)])
    assert len(same) == 1
    assert len(same[0].prices) == 1
    assert len(same[0].prices[0].evidence) == 2
    assert not same[0].conflict

    conflict = merge_statusmatch_application_routes(
        [route(faq, 99)], [route(terms, 199)]
    )
    assert conflict[0].conflict
    assert len(conflict[0].prices) == 2
    assert "不同当前价格" in (conflict[0].conflict_note or "")


def test_narrative_additional_fee_is_normalized_to_conditional() -> None:
    terms = _document("terms", "TERMS")
    evidence = _evidence(terms, "select-member upgrade")
    route = ApplicationRoute(
        scope="默认申请路线",
        prices=[
            RoutePrice(
                target_tier="Gold",
                amount=199,
                currency="USD",
                availability=RoutePriceAvailability.AVAILABLE,
                raw_text="Select members may upgrade for an additional fee of USD 199",
                evidence=[evidence],
            )
        ],
        evidence=[evidence],
    )

    merged = merge_statusmatch_application_routes([], [route])

    assert merged[0].prices[0].availability == RoutePriceAvailability.CONDITIONAL


def test_fee_table_prices_remove_redundant_narrative_copies() -> None:
    faq = _document("faq", "FAQ")
    terms = _document("terms", "TERMS")
    faq_evidence = _evidence(faq, "fee table")
    terms_evidence = _evidence(terms, "credit card prose")
    deterministic = [
        ApplicationRoute(
            scope="Greece",
            region="Greece",
            prices=[
                RoutePrice(
                    target_tier="Gold",
                    amount=199,
                    currency="EUR",
                    availability="AVAILABLE",
                    raw_text="EUR 199",
                    evidence=[faq_evidence],
                )
            ],
            evidence=[faq_evidence],
        )
    ]
    narrative = [
        deterministic[0].model_copy(
            update={"scope": "希腊", "region": "希腊"}
        ),
        ApplicationRoute(
            scope="信用卡申请",
            prices=[
                RoutePrice(
                    target_tier="Titanium",
                    amount=299,
                    currency="USD",
                    availability="AVAILABLE",
                    raw_text="USD 299",
                    evidence=[terms_evidence],
                )
            ],
            evidence=[terms_evidence],
        ),
    ]

    filtered = filter_redundant_statusmatch_narrative_routes(
        narrative, deterministic
    )

    assert [route.scope for route in filtered] == ["信用卡申请"]


@pytest.mark.parametrize(
    ("page_text", "expected"),
    [
        ("There is no application fee payable for this status match.", "免费"),
        ("Application fees apply and vary by eligibility.", "收费，金额未公布"),
        ("Free account enrolment includes complimentary Wi-Fi.", "免费"),
        ("No price information is published.", "免费"),
    ],
)
def test_fee_policy_uses_application_fee_semantics(page_text: str, expected: str) -> None:
    documents = [
        _document("activity", "Applications are open."),
        _document("faq", page_text),
        _document("terms", "Current project conditions."),
    ]

    result = apply_statusmatch_fee_policy(_facts(documents), documents)

    assert result.cost.value == expected
    if page_text.startswith("Free account"):
        assert "按产品规则" in result.cost.evidence[0].locator


def test_fee_policy_marks_explicit_free_and_paid_conflict() -> None:
    documents = [
        _document("activity", "This status match is free."),
        _document("faq", "Application fees apply and vary by eligibility."),
        _document("terms", "Current project conditions."),
    ]

    result = apply_statusmatch_fee_policy(_facts(documents), documents)

    assert result.cost.conflict
    assert result.cost.value is None
    assert result.cost.alternatives == ["免费", "付费"]
