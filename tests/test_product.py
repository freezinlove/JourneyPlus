from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

from fastapi.testclient import TestClient

from journeyplus.contracts import (
    ApplicationRoute,
    Brief,
    BriefPoint,
    EvidenceRef,
    FactField,
    FactSet,
    OpportunityKind,
    RoutePrice,
    RoutePriceAvailability,
    StatusMapping,
)
from journeyplus.models import (
    ArticleAnalysisRecord,
    ArticleBriefRecord,
    ArticleOpportunityRecord,
    BriefRecord,
    DocumentVersion,
    FactSetRecord,
    SourceItem,
    StatusEvent,
)
from journeyplus.membership.contracts import ReachableMembershipTreeNode
from journeyplus.product.api import create_product_app
from journeyplus.product.briefs import _price_summaries, _public_brief_text
from journeyplus.product.opportunities import _opportunity_paths, _route_fee_label
from journeyplus.sources.registry import seed_sources


def _article_opportunity(
    session,
    *,
    slug: str,
    kind: OpportunityKind,
    program: str,
    target_tier: str,
    source_tier: str | None = None,
    with_prices: bool = False,
) -> ArticleOpportunityRecord:
    seed_sources(session)
    now = datetime.now(UTC)
    url = f"https://loyaltylobby.com/{slug}/"
    body = f"{program} offers {target_tier}; {kind.value}; {slug}."
    digest = sha256(body.encode()).hexdigest()
    item = SourceItem(
        source_id="loyaltylobby_feed",
        external_id=slug,
        discovered_url=url,
        canonical_url=url,
        title=f"{program} {target_tier}",
        published_at=now,
        observed_at=now,
        raw_metadata={},
    )
    session.add(item)
    session.flush()
    document = DocumentVersion(
        source_item_id=item.id,
        canonical_url=url,
        raw_body=body,
        normalized_body=body,
        content_type="text/plain",
        storage_mode="test",
        raw_hash=digest,
        normalized_hash=digest,
        parser_version="product-test-v1",
        fetched_at=now,
    )
    session.add(document)
    session.flush()
    analysis = ArticleAnalysisRecord(
        document_version_id=document.id,
        source_item_id=item.id,
        analysis_run_id=uuid4(),
        input_version=str(document.id),
        label="STATUS_OPPORTUNITY",
        confidence=1,
        reason="product fixture",
        status="SUCCEEDED",
        content_signature=digest,
    )
    session.add(analysis)
    session.flush()
    opportunity_id = uuid4()
    evidence = EvidenceRef(
        document_version_id=document.id,
        source_url=url,
        locator=body,
    )
    routes = []
    if with_prices:
        routes = [
            ApplicationRoute(
                scope="online application",
                eligibility="Existing elite status",
                region="All countries except China",
                cost="Gold: USD 149; Platinum: EUR 129",
                prices=[
                    RoutePrice(
                        target_tier="Gold",
                        amount=149,
                        currency="USD",
                        availability=RoutePriceAvailability.AVAILABLE,
                        raw_text="Gold: USD 149",
                        evidence=[evidence],
                    ),
                    RoutePrice(
                        target_tier="Platinum",
                        amount=129,
                        currency="EUR",
                        availability=RoutePriceAvailability.AVAILABLE,
                        raw_text="Platinum: EUR 129",
                        evidence=[evidence],
                    ),
                ],
                action_link="https://example.com/apply",
                evidence=[evidence],
            )
        ]
    mappings = (
        [
            StatusMapping(
                source_program="Source Club",
                source_tiers=[source_tier],
                target_tier=target_tier,
                availability="AVAILABLE",
                evidence=[evidence],
            )
        ]
        if source_tier
        else []
    )
    facts = FactSet(
        event_id=opportunity_id,
        opportunity_kind=kind,
        what_happened=FactField(value=body, evidence=[evidence]),
        target_status=FactField(value=target_tier, evidence=[evidence]),
        application_routes=routes,
        status_mappings=mappings,
    )
    opportunity = ArticleOpportunityRecord(
        id=opportunity_id,
        analysis_id=analysis.id,
        opportunity_index=0,
        program=program,
        target_status=target_tier,
        summary=body,
        lifecycle_status="ACTIVE",
        visibility_until_at=now + timedelta(days=180),
        visibility_policy="DEFAULT_180_DAYS",
        action_links=[],
        facts=facts.model_dump(mode="json"),
        fact_signature=digest,
        status="DRAFT",
    )
    session.add(opportunity)
    session.flush()
    brief = Brief(
        fact_set_id=opportunity.id,
        title=f"{program} {target_tier} 简报",
        title_fact_keys=["what_happened"],
        summary=f"{program} 的当前机会摘要。",
        summary_fact_keys=["what_happened"],
        key_points=[BriefPoint(text="保留原始证据", fact_keys=["what_happened"])],
        source_links=[url],
    )
    brief_record = ArticleBriefRecord(
        opportunity_id=opportunity.id,
        analysis_run_id=uuid4(),
        input_version=f"brief:{opportunity.id}",
        version=1,
        schema_version="1",
        content=brief.model_dump(mode="json"),
        status="DRAFT",
    )
    session.add(brief_record)
    session.flush()
    opportunity.current_brief_id = brief_record.id
    session.flush()
    return opportunity


def test_product_api_pages_holdings_matches_briefs_and_prices(session_factory) -> None:
    with session_factory.begin() as session:
        gold = _article_opportunity(
            session,
            slug="gold-match",
            kind=OpportunityKind.STATUS_MATCH,
            program="Target Club",
            target_tier="Gold",
            source_tier="Gold",
            with_prices=True,
        )
        _article_opportunity(
            session,
            slug="platinum-match",
            kind=OpportunityKind.STATUS_MATCH,
            program="Second Club",
            target_tier="Platinum",
            source_tier="Platinum",
        )
        other = _article_opportunity(
            session,
            slug="credit-card-offer",
            kind=OpportunityKind.OTHER,
            program="Card Rewards",
            target_tier="Bonus",
        )
        standalone = _article_opportunity(
            session,
            slug="standalone-challenge",
            kind=OpportunityKind.STATUS_MATCH,
            program="Challenge Club",
            target_tier="Gold",
        )

    client = TestClient(create_product_app(session_factory))
    for path, marker in (
        ("/holdings", "我的会籍"),
        ("/matches", "个性化匹配图"),
        ("/briefs", "机会简报"),
        (f"/opportunities/{gold.id}", "机会详情"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert marker in response.text
        assert "/assets/app.css" in response.text

    app_script = client.get("/assets/app.js")
    app_styles = client.get("/assets/app.css")
    assert app_script.status_code == 200
    assert "renderMembershipGraph" in app_script.text
    assert 'class="membership-graph"' in app_script.text
    assert "graphEdgeLabel" not in app_script.text
    assert "有条件匹配" not in app_script.text
    assert "可继续匹配" not in app_script.text
    assert "航空会籍" not in app_script.text
    assert "酒店会籍" in app_script.text
    assert "有后续路径" not in app_script.text
    assert "本图终点" not in app_script.text
    assert "距起点" not in app_script.text
    assert "graph-arrow" not in app_script.text
    assert "marker-end" not in app_script.text
    assert app_styles.status_code == 200
    assert ".membership-node" in app_styles.text
    assert ".graph-link" in app_styles.text
    assert ".graph-edge-label" not in app_styles.text
    assert "border-left: 4px solid #4f9c78" not in app_styles.text
    assert ".node-state" not in app_styles.text
    assert ".membership-node__footer" not in app_styles.text

    catalog = client.get("/v1/membership-catalog", params={"q": "Source Club"})
    assert catalog.status_code == 200
    nodes = catalog.json()["nodes"]
    assert {item["tier_key"] for item in nodes} == {"gold", "platinum"}

    created = client.post(
        "/v1/status-holdings",
        json={
            "program_key": "source club",
            "tier_key": "gold",
            "valid_until": "2027-12-31",
        },
    )
    assert created.status_code == 201
    holding_id = created.json()["id"]

    matches = client.get("/v1/personalized-matches")
    assert matches.status_code == 200
    payload = matches.json()
    assert payload["holdings"][0]["valid_until"] == "2027-12-31"
    opportunity_by_id = {
        item["opportunity_id"]: item for item in payload["opportunities"]
    }
    assert set(opportunity_by_id) == {str(gold.id), str(standalone.id)}
    assert opportunity_by_id[str(gold.id)]["path"] == [
        "source club::gold",
        "target club::gold",
    ]
    assert opportunity_by_id[str(standalone.id)]["path"] is None
    assert payload["edge_fees"] == [
        {
            "source_node_id": "source club::gold",
            "target_node_id": "target club::gold",
            "labels": ["USD 149"],
        }
    ]

    replaced = client.post(
        "/v1/status-holdings",
        json={
            "program_key": "source club",
            "tier_key": "platinum",
            "valid_until": None,
        },
    )
    assert replaced.status_code == 201
    assert replaced.json()["id"] == holding_id
    assert len(client.get("/v1/status-holdings").json()) == 1
    assert client.get("/v1/status-holdings").json()[0]["tier_key"] == "platinum"

    restored = client.patch(
        f"/v1/status-holdings/{holding_id}",
        json={
            "program_key": "source club",
            "tier_key": "gold",
            "valid_until": date(2028, 1, 31).isoformat(),
        },
    )
    assert restored.status_code == 200
    assert restored.json()["valid_until"] == "2028-01-31"

    briefs = client.get("/v1/briefs")
    assert briefs.status_code == 200
    brief_payload = briefs.json()["items"]
    assert len(brief_payload) == 4
    assert {item["opportunity_kind"] for item in brief_payload} == {
        "STATUS_MATCH",
        "OTHER",
    }
    assert any(item["opportunity_id"] == str(other.id) for item in brief_payload)
    gold_brief = next(
        item for item in brief_payload if item["opportunity_id"] == str(gold.id)
    )
    assert gold_brief["price_summaries"] == [
        "online application · Gold: USD 149",
        "online application · Platinum: EUR 129",
    ]
    assert gold_brief["china_advisories"] == ["EXPLICITLY_EXCLUDED"]
    reachable = client.get("/v1/briefs", params={"reachable_only": "true"}).json()
    assert [item["opportunity_id"] for item in reachable["items"]] == [str(gold.id)]

    detail = client.get(f"/v1/match-opportunities/{gold.id}")
    assert detail.status_code == 200
    route = detail.json()["routes"][0]
    assert detail.json()["path"] == ["source club::gold", "target club::gold"]
    assert route["china_advisory"] == "EXPLICITLY_EXCLUDED"
    assert [(item["currency"], item["amount"]) for item in route["prices"]] == [
        ("USD", "149"),
        ("EUR", "129"),
    ]
    assert route["cost"] == "Gold: USD 149; Platinum: EUR 129"
    assert detail.json()["source_links"] == ["https://loyaltylobby.com/gold-match/"]

    removed = client.delete(f"/v1/status-holdings/{holding_id}")
    assert removed.status_code == 204
    assert client.get("/v1/status-holdings").json() == []
    without_holdings = client.get("/v1/personalized-matches").json()
    assert [item["opportunity_id"] for item in without_holdings["opportunities"]] == [
        str(standalone.id)
    ]
    assert without_holdings["opportunities"][0]["path"] is None


def test_unknown_paid_fee_and_free_fee_share_brief_and_tree_wording() -> None:
    evidence = EvidenceRef(
        document_version_id=uuid4(),
        source_url="https://example.statusmatch.com/terms",
        locator="application fee statement",
    )
    unknown = FactSet(
        event_id=uuid4(),
        opportunity_kind=OpportunityKind.STATUS_MATCH,
        what_happened=FactField(value="Current status match", evidence=[evidence]),
        cost=FactField(value="收费，金额未公布", evidence=[evidence]),
    )
    free = unknown.model_copy(
        update={"cost": FactField(value="免费", evidence=[evidence])}
    )

    assert _price_summaries(unknown) == ["默认申请路线: 收费，金额未公布"]
    assert _price_summaries(free) == ["默认申请路线: 免费"]
    assert (
        _route_fee_label([], target_tier_key="gold", raw_cost=unknown.cost.value)
        == "金额未公布"
    )
    assert (
        _route_fee_label([], target_tier_key="gold", raw_cost=free.cost.value)
        == "免费"
    )


def test_conditional_upgrade_fee_is_not_summed_with_base_fee() -> None:
    evidence = EvidenceRef(
        document_version_id=uuid4(),
        source_url="https://airastana.statusmatch.com/terms",
        locator="application and upgrade fees",
    )
    prices = [
        RoutePrice(
            amount=49,
            currency="USD",
            availability=RoutePriceAvailability.AVAILABLE,
            raw_text="Application fee USD 49",
            evidence=[evidence],
        ),
        RoutePrice(
            target_tier="Gold",
            amount=199,
            currency="USD",
            availability=RoutePriceAvailability.CONDITIONAL,
            raw_text="Select members may upgrade for an additional fee of USD 199",
            evidence=[evidence],
        ),
    ]
    facts = FactSet(
        event_id=uuid4(),
        opportunity_kind=OpportunityKind.STATUS_MATCH,
        what_happened=FactField(value="Current status match", evidence=[evidence]),
        application_routes=[
            ApplicationRoute(
                scope="默认申请路线",
                prices=prices,
                evidence=[evidence],
            )
        ],
    )

    assert (
        _route_fee_label(prices, target_tier_key="gold", raw_cost=None)
        == "USD 49；条件另付 USD 199"
    )
    assert _price_summaries(facts) == [
        "默认申请路线: USD 49",
        "默认申请路线 · Gold: 条件另付 USD 199",
    ]
    assert _public_brief_text(
        "活动（what_happened）按申请路径（application_routes）的region收费。"
    ) == "活动（活动内容）按申请路径（申请路径）的适用地区收费。"


def test_archived_official_event_is_hidden_from_current_briefs(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        event = StatusEvent(
            created_from_key="archived-statusmatch-product-test",
            program="Archived Club",
            target_status="Gold",
            summary="Archived status match",
            search_text="Archived Club Gold",
            lifecycle_status="EXPIRED",
            archived_at=datetime.now(UTC),
        )
        session.add(event)
        session.flush()
        evidence = EvidenceRef(
            document_version_id=uuid4(),
            source_url="https://archived.statusmatch.com/",
            locator="archived offer",
        )
        facts = FactSet(
            event_id=event.id,
            opportunity_kind=OpportunityKind.STATUS_MATCH,
            what_happened=FactField(
                value="Archived status match", evidence=[evidence]
            ),
        )
        fact_record = FactSetRecord(
            event_id=event.id,
            version=1,
            schema_version="5",
            facts=facts.model_dump(mode="json"),
            has_conflicts=False,
        )
        session.add(fact_record)
        session.flush()
        brief = Brief(
            fact_set_id=fact_record.id,
            title="Archived Club 简报",
            title_fact_keys=["what_happened"],
            summary="该项目已经结束。",
            summary_fact_keys=["what_happened"],
            source_links=["https://archived.statusmatch.com/"],
        )
        brief_record = BriefRecord(
            fact_set_id=fact_record.id,
            version=1,
            schema_version="1",
            content=brief.model_dump(mode="json"),
        )
        session.add(brief_record)
        session.flush()
        event.current_fact_set_id = fact_record.id
        event.current_brief_id = brief_record.id

    response = TestClient(create_product_app(session_factory)).get("/v1/briefs")

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_holding_rejects_free_text_not_present_in_catalog(session_factory) -> None:
    client = TestClient(create_product_app(session_factory))

    response = client.post(
        "/v1/status-holdings",
        json={"program_key": "invented", "tier_key": "diamond"},
    )

    assert response.status_code == 422
    assert "Unknown membership node" in response.json()["detail"]


def test_opportunity_paths_choose_nearest_arrival_and_ignore_cycles() -> None:
    nearest_opportunity_id = uuid4()
    cycle_opportunity_id = uuid4()

    def node(node_id: str, state: str, children: list[dict] | None = None) -> dict:
        program, tier = node_id.split("::")
        return {
            "node": {
                "id": node_id,
                "program_key": program,
                "tier_key": tier,
                "program": program,
                "tier": tier,
            },
            "state": state,
            "children": children or [],
        }

    def edge(
        source: str,
        target: str,
        child: dict,
        opportunity_id,
    ) -> dict:
        return {
            "source_node_id": source,
            "target_node_id": target,
            "opportunity_ids": [opportunity_id],
            "certainties": ["EXACT"],
            "child": child,
        }

    cycle_to_root = edge(
        "target::gold",
        "source::gold",
        node("source::gold", "CYCLE"),
        cycle_opportunity_id,
    )
    long_target = node("target::gold", "EXPANDED", [cycle_to_root])
    via_node = node(
        "via::gold",
        "EXPANDED",
        [
            edge(
                "via::gold",
                "target::gold",
                long_target,
                nearest_opportunity_id,
            )
        ],
    )
    root = ReachableMembershipTreeNode.model_validate(
        node(
            "source::gold",
            "EXPANDED",
            [
                edge("source::gold", "via::gold", via_node, uuid4()),
                edge(
                    "source::gold",
                    "target::gold",
                    node("target::gold", "CROSS_REFERENCE"),
                    nearest_opportunity_id,
                ),
            ],
        )
    )

    paths = _opportunity_paths([root])

    assert paths[nearest_opportunity_id] == ["source::gold", "target::gold"]
    assert cycle_opportunity_id not in paths
