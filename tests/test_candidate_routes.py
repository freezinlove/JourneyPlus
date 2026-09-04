from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

from journeyplus.contracts import (
    ApplicationRoute,
    EvidenceRef,
    FactField,
    FactSet,
    OpportunityKind,
    RoutePrice,
    RoutePriceAvailability,
    StatusMapping,
)
from journeyplus.membership.contracts import AirlineAlliance
from journeyplus.models import (
    ArticleAnalysisRecord,
    ArticleOpportunityRecord,
    DocumentVersion,
    SourceItem,
)
from journeyplus.product.candidate_routes import CandidateRouteService
from journeyplus.product.contracts import (
    CandidateChallengePolicy,
    CandidateConstraints,
    CandidateCostPolicy,
    CandidateRelativeTier,
    CandidateRouteQuery,
    CandidateTarget,
    StatusHoldingInput,
)
from journeyplus.product.holdings import StatusHoldingService
from journeyplus.sources.registry import seed_sources


def _mapping_opportunity(
    session,
    *,
    slug: str,
    source_program: str,
    source_tier: str,
    target_program: str,
    target_tier: str,
    amount: int | None,
    challenge: str | None,
) -> ArticleOpportunityRecord:
    seed_sources(session)
    now = datetime.now(UTC)
    url = f"https://loyaltylobby.com/{slug}/"
    body = f"{source_program} {source_tier} to {target_program} {target_tier}"
    digest = sha256(body.encode()).hexdigest()
    item = SourceItem(
        source_id="loyaltylobby_feed",
        external_id=slug,
        discovered_url=url,
        canonical_url=url,
        title=body,
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
        parser_version="candidate-test-v1",
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
        reason="candidate fixture",
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
    if amount is None:
        route = ApplicationRoute(
            scope="online",
            eligibility="Existing status",
            action_link="https://example.com/apply",
            evidence=[evidence],
        )
    else:
        route = ApplicationRoute(
            scope="online",
            cost="免费" if amount == 0 else f"USD {amount}",
            prices=[
                RoutePrice(
                    amount=amount,
                    currency="USD",
                    availability=RoutePriceAvailability.AVAILABLE,
                    raw_text="免费" if amount == 0 else f"USD {amount}",
                    evidence=[evidence],
                )
            ],
            action_link="https://example.com/apply",
            evidence=[evidence],
        )
    facts = FactSet(
        event_id=opportunity_id,
        opportunity_kind=OpportunityKind.STATUS_MATCH,
        what_happened=FactField(value=body, evidence=[evidence]),
        target_status=FactField(value=target_tier, evidence=[evidence]),
        challenge_requirements=(
            FactField(value=challenge, evidence=[evidence])
            if challenge is not None
            else FactField()
        ),
        application_routes=[route],
        status_mappings=[
            StatusMapping(
                source_program=source_program,
                source_tiers=[source_tier],
                target_tier=target_tier,
                availability="AVAILABLE",
                evidence=[evidence],
            )
        ],
    )
    opportunity = ArticleOpportunityRecord(
        id=opportunity_id,
        analysis_id=analysis.id,
        opportunity_index=0,
        program=target_program,
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
    return opportunity


def test_candidate_query_classifies_matching_nearby_and_unknown(session_factory) -> None:
    with session_factory.begin() as session:
        _mapping_opportunity(
            session,
            slug="free-direct",
            source_program="Source Club",
            source_tier="Gold",
            target_program="Target Club",
            target_tier="Gold",
            amount=0,
            challenge="No status challenge",
        )
        _mapping_opportunity(
            session,
            slug="paid-direct",
            source_program="Source Club",
            source_tier="Gold",
            target_program="Paid Club",
            target_tier="Gold",
            amount=149,
            challenge="No status challenge",
        )
        _mapping_opportunity(
            session,
            slug="unknown-challenge",
            source_program="Source Club",
            source_tier="Gold",
            target_program="Unknown Club",
            target_tier="Gold",
            amount=0,
            challenge=None,
        )
        StatusHoldingService(session).upsert(
            StatusHoldingInput(program_key="source club", tier_key="gold")
        )

    with session_factory.begin() as session:
        free = CandidateRouteService(session).query(
            CandidateRouteQuery(
                target=CandidateTarget(
                    program_key="target club", tier_key="gold"
                ),
                constraints=CandidateConstraints(
                    cost_policy=CandidateCostPolicy.FREE_ONLY,
                    challenge_policy=CandidateChallengePolicy.NO_CHALLENGE,
                ),
            )
        )
        assert len(free.matching_routes) == 1
        assert free.matching_routes[0].steps[0].costs == ["免费"]
        assert free.matching_routes[0].steps[0].evidence_links == [
            "https://loyaltylobby.com/free-direct/"
        ]

        paid = CandidateRouteService(session).query(
            CandidateRouteQuery(
                target=CandidateTarget(program_key="paid club"),
                constraints=CandidateConstraints(
                    cost_policy=CandidateCostPolicy.FREE_ONLY
                ),
            )
        )
        assert not paid.matching_routes
        assert paid.nearby_routes[0].violations == ["cost_policy"]

        unknown = CandidateRouteService(session).query(
            CandidateRouteQuery(
                target=CandidateTarget(program_key="unknown club"),
                constraints=CandidateConstraints(
                    challenge_policy=CandidateChallengePolicy.NO_CHALLENGE
                ),
            )
        )
        assert not unknown.matching_routes
        assert unknown.unknown_routes[0].unknowns == ["challenge_policy"]


def test_candidate_query_builds_multistep_alliance_route(session_factory) -> None:
    with session_factory.begin() as session:
        first = _mapping_opportunity(
            session,
            slug="source-to-bridge",
            source_program="Source Club",
            source_tier="Gold",
            target_program="Bridge Club",
            target_tier="Gold",
            amount=10,
            challenge="No challenge",
        )
        second = _mapping_opportunity(
            session,
            slug="bridge-to-flying-blue",
            source_program="Bridge Club",
            source_tier="Gold",
            target_program="Flying Blue",
            target_tier="Gold",
            amount=20,
            challenge="No challenge",
        )
        StatusHoldingService(session).upsert(
            StatusHoldingInput(program_key="source club", tier_key="gold")
        )

    with session_factory.begin() as session:
        result = CandidateRouteService(session).query(
            CandidateRouteQuery(
                target=CandidateTarget(
                    alliance=AirlineAlliance.SKYTEAM,
                    relative_tier=CandidateRelativeTier.HIGH,
                ),
                constraints=CandidateConstraints(
                    cost_policy=CandidateCostPolicy.MAX_AMOUNT,
                    max_amount=30,
                    max_currency="USD",
                    challenge_policy=CandidateChallengePolicy.NO_CHALLENGE,
                ),
            )
        )
        route = result.matching_routes[0]
        assert route.node_path == [
            "source club::gold",
            "bridge club::gold",
            "flying blue::gold",
        ]
        assert [step.opportunity_id for step in route.steps] == [first.id, second.id]
        assert route.target_alliance == AirlineAlliance.SKYTEAM
        assert "联盟精英等级等价" in route.limitations[0]
        assert result.matching_signature != "0" * 64


def test_candidate_query_without_holdings_is_empty(session_factory) -> None:
    with session_factory.begin() as session:
        result = CandidateRouteService(session).query(
            CandidateRouteQuery(
                target=CandidateTarget(program_key="target club")
            )
        )
    assert result.holdings == []
    assert result.matching_routes == []
    assert result.nearby_routes == []
    assert result.unknown_routes == []
