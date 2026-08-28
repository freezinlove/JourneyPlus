from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import select

from journeyplus.article_operations import (
    archive_article_mapping,
    extend_article_mapping,
    restore_article_mapping,
)
from journeyplus.article_pipeline.lifecycle import advance_article_lifecycles
from journeyplus.article_pipeline.visibility import (
    ArticleArchiveReason,
    ArticleVisibilityPolicy,
    calculate_mapping_visibility,
)
from journeyplus.contracts import EvidenceRef, FactField, FactSet, StatusMapping
from journeyplus.membership.contracts import (
    MappingContributionSource,
    UnifiedTreeNodeState,
)
from journeyplus.membership.unified import UnifiedMembershipTreeService
from journeyplus.models import (
    ArticleAnalysisRecord,
    ArticleOpportunityRecord,
    DocumentVersion,
    FactSetRecord,
    ReviewDecision,
    SourceItem,
    StatusEvent,
    StatusMatchArticleRoute,
    StatusMatchWatch,
    StatusMatchWatchPage,
)
from journeyplus.sources.registry import seed_sources


def _add_article_mapping(
    session,
    *,
    external_id: str,
    source_program: str,
    source_tier: str,
    target_program: str,
    target_tier: str,
    published_at: datetime | None,
    first_collected_at: datetime,
    deadline_at: datetime | None = None,
    application_start_at: datetime | None = None,
    conditions: str | None = None,
    conflict: bool = False,
    availability: str = "AVAILABLE",
    routed: bool = False,
):
    seed_sources(session)
    url = f"https://loyaltylobby.com/{external_id}/"
    quote = (
        f"{source_program} {source_tier} maps directly to "
        f"{target_program} {target_tier}."
    )
    item = SourceItem(
        source_id="loyaltylobby_feed",
        external_id=external_id,
        discovered_url=url,
        canonical_url=url,
        title=f"{target_program} status match",
        published_at=published_at,
        observed_at=first_collected_at,
        created_at=first_collected_at,
        raw_metadata={},
    )
    session.add(item)
    session.flush()
    digest = sha256(quote.encode()).hexdigest()
    document = DocumentVersion(
        source_item_id=item.id,
        canonical_url=url,
        raw_body=quote,
        normalized_body=quote,
        content_type="text/plain",
        storage_mode="full",
        raw_hash=digest,
        normalized_hash=digest,
        parser_version="unified-test-v1",
        fetched_at=first_collected_at,
        created_at=first_collected_at,
    )
    session.add(document)
    session.flush()
    analysis = ArticleAnalysisRecord(
        document_version_id=document.id,
        source_item_id=item.id,
        analysis_run_id=uuid4(),
        input_version=str(document.id),
        label="STATUS_OPPORTUNITY",
        confidence=0.99,
        reason="direct mapping",
        status="SUCCEEDED",
        content_signature=digest,
        created_at=first_collected_at,
    )
    session.add(analysis)
    session.flush()
    opportunity_id = uuid4()
    evidence = EvidenceRef(
        document_version_id=document.id,
        source_url=url,
        locator=quote,
    )
    effective_availability = (
        "CONDITIONAL" if conditions is not None and availability == "AVAILABLE" else availability
    )
    mapping = StatusMapping(
        source_program=source_program,
        source_tiers=[] if availability == "UNAVAILABLE" else [source_tier],
        target_tier=target_tier,
        availability=effective_availability,
        conditions=conditions,
        evidence=[evidence],
        conflict=conflict,
        conflict_note="article contains contradictory rows" if conflict else None,
    )
    facts = FactSet(
        event_id=opportunity_id,
        what_happened=FactField(value=quote, evidence=[evidence]),
        status_mappings=[mapping],
    )
    visibility_until_at, visibility_policy = calculate_mapping_visibility(
        application_deadline_at=deadline_at,
        published_at=published_at,
        first_collected_at=first_collected_at,
    )
    opportunity = ArticleOpportunityRecord(
        id=opportunity_id,
        analysis_id=analysis.id,
        opportunity_index=0,
        program=target_program,
        target_status=target_tier,
        summary=quote,
        application_start_at=application_start_at,
        application_deadline_at=deadline_at,
        lifecycle_status="UNKNOWN",
        visibility_until_at=visibility_until_at,
        visibility_policy=visibility_policy,
        action_links=[],
        facts=facts.model_dump(mode="json"),
        fact_signature=digest,
        status="DRAFT",
    )
    session.add(opportunity)
    session.flush()
    if routed:
        session.add(
            StatusMatchArticleRoute(
                document_version_id=document.id,
                project_host="linked.statusmatch.com",
                project_url="https://linked.statusmatch.com/",
            )
        )
        session.flush()
    return opportunity, analysis, item, document


def _add_official_mapping(
    session,
    *,
    host: str,
    source_program: str,
    source_tier: str,
    target_program: str,
    target_tier: str,
):
    seed_sources(session)
    now = datetime(2026, 8, 25, tzinfo=UTC)
    faq_url = f"https://{host}/faq"
    item = SourceItem(
        source_id="status_services_mail",
        external_id=f"unified:{host}:faq",
        discovered_url=faq_url,
        canonical_url=faq_url,
        title=f"{target_program} FAQ",
        observed_at=now,
        raw_metadata={},
    )
    session.add(item)
    session.flush()
    body = (
        "<table><tr><td>Source Membership</td><td>Target Tier</td></tr>"
        f"<tr><td>{source_program}</td><td>{target_tier}</td></tr></table>"
    )
    digest = sha256(body.encode()).hexdigest()
    document = DocumentVersion(
        source_item_id=item.id,
        canonical_url=faq_url,
        raw_body=body,
        normalized_body=body,
        content_type="text/html",
        storage_mode="full",
        raw_hash=digest,
        normalized_hash=digest,
        parser_version="unified-test-v1",
        fetched_at=now,
    )
    session.add(document)
    session.flush()
    event = StatusEvent(
        created_from_key=f"unified:{host}",
        program=target_program,
        summary=f"{target_program} mapping",
        search_text=target_program,
        status="CONFIRMED",
    )
    session.add(event)
    session.flush()
    evidence = EvidenceRef(
        document_version_id=document.id,
        source_url=faq_url,
        locator="official mapping",
    )
    facts = FactSet(
        event_id=event.id,
        what_happened=FactField(value="official mapping", evidence=[evidence]),
        status_mappings=[
            StatusMapping(
                source_program=source_program,
                source_tiers=[source_tier],
                target_tier=f"{target_program} {target_tier}",
                availability="AVAILABLE",
                evidence=[evidence],
            )
        ],
    )
    record = FactSetRecord(
        event_id=event.id,
        version=1,
        schema_version=facts.schema_version,
        facts=facts.model_dump(mode="json"),
        has_conflicts=False,
    )
    session.add(record)
    session.flush()
    event.current_fact_set_id = record.id
    watch = StatusMatchWatch(
        host=host,
        status="ACTIVE",
        current_event_id=event.id,
    )
    session.add(watch)
    session.flush()
    session.add(
        StatusMatchWatchPage(
            watch_id=watch.id,
            page_kind="faq",
            canonical_url=faq_url,
            current_document_version_id=document.id,
        )
    )
    session.flush()
    return watch, event, record


def test_no_deadline_uses_exact_180_days_and_archives_at_boundary(db_session) -> None:
    published = datetime(2026, 8, 24, 10, tzinfo=UTC)
    opportunity, analysis, item, _document = _add_article_mapping(
        db_session,
        external_id="no-deadline",
        source_program="Source Club",
        source_tier="Gold",
        target_program="Target Club",
        target_tier="Platinum",
        published_at=published,
        first_collected_at=published + timedelta(hours=3),
    )

    assert opportunity.visibility_policy == ArticleVisibilityPolicy.DEFAULT_180_DAYS
    assert opportunity.visibility_until_at == published + timedelta(days=180)
    assert FactSet.model_validate(opportunity.facts).deadline.value is None
    before = UnifiedMembershipTreeService(db_session).tree(
        "Source Club", "Gold", now=opportunity.visibility_until_at - timedelta(seconds=1)
    )
    at_boundary = UnifiedMembershipTreeService(db_session).tree(
        "Source Club", "Gold", now=opportunity.visibility_until_at
    )
    assert len(before.root.children) == 1
    assert at_boundary.root.state == UnifiedTreeNodeState.LEAF

    summary = advance_article_lifecycles(
        db_session, now=opportunity.visibility_until_at
    )
    assert summary.mapping_archived == 1
    assert opportunity.archive_reason == ArticleArchiveReason.STALE_180D
    assert analysis.status == "SUCCEEDED" and item.id == analysis.source_item_id


def test_explicit_deadline_wins_and_missing_publish_time_uses_first_collection(
    db_session,
) -> None:
    collected = datetime(2026, 8, 25, 3, tzinfo=UTC)
    explicit = collected + timedelta(days=240)
    explicit_opportunity, *_ = _add_article_mapping(
        db_session,
        external_id="explicit-deadline",
        source_program="Source Club",
        source_tier="Gold",
        target_program="Explicit Club",
        target_tier="Platinum",
        published_at=collected,
        first_collected_at=collected,
        deadline_at=explicit,
    )
    fallback_opportunity, *_ = _add_article_mapping(
        db_session,
        external_id="missing-published-at",
        source_program="Source Club",
        source_tier="Diamond",
        target_program="Fallback Club",
        target_tier="Gold",
        published_at=None,
        first_collected_at=collected,
    )

    assert explicit_opportunity.visibility_until_at == explicit
    assert (
        explicit_opportunity.visibility_policy
        == ArticleVisibilityPolicy.EXPLICIT_DEADLINE
    )
    assert fallback_opportunity.visibility_until_at == collected + timedelta(days=180)
    assert (
        fallback_opportunity.visibility_policy
        == ArticleVisibilityPolicy.DEFAULT_180_DAYS
    )
    summary = advance_article_lifecycles(db_session, now=explicit)
    assert summary.mapping_archived == 2
    assert explicit_opportunity.archive_reason == ArticleArchiveReason.DEADLINE_EXPIRED


def test_same_edge_survives_until_last_contributor_expires(db_session) -> None:
    base = datetime(2026, 8, 24, tzinfo=UTC)
    first, *_ = _add_article_mapping(
        db_session,
        external_id="first-contributor",
        source_program="Source Club",
        source_tier="Gold",
        target_program="Target Club",
        target_tier="Platinum",
        published_at=base,
        first_collected_at=base,
        deadline_at=base + timedelta(days=5),
    )
    second, *_ = _add_article_mapping(
        db_session,
        external_id="second-contributor",
        source_program="Source Club",
        source_tier="Gold",
        target_program="Target Club",
        target_tier="Platinum",
        published_at=base,
        first_collected_at=base,
        deadline_at=base + timedelta(days=10),
    )
    service = UnifiedMembershipTreeService(db_session)

    initial = service.audit(now=base + timedelta(days=1))
    archive_article_mapping(
        db_session,
        opportunity_id=first.id,
        reason="temporarily withdraw only the first report",
        now=base + timedelta(days=1),
    )
    manually_archived = service.audit(now=base + timedelta(days=2))
    restore_article_mapping(
        db_session,
        opportunity_id=first.id,
        reason="the first report was reconfirmed",
        now=base + timedelta(days=2),
    )
    restored = service.audit(now=base + timedelta(days=2))
    middle = service.audit(now=base + timedelta(days=6))
    final = service.tree("Source Club", "Gold", now=base + timedelta(days=10))

    assert len(initial.edges) == 1
    assert len(initial.edges[0].contributions) == 2
    assert [
        item.provenance.opportunity_id
        for item in manually_archived.edges[0].contributions
    ] == [second.id]
    assert len(restored.edges[0].contributions) == 2
    assert len(middle.edges) == 1
    assert [
        item.provenance.opportunity_id for item in middle.edges[0].contributions
    ] == [second.id]
    assert final.root.state == UnifiedTreeNodeState.LEAF
    assert first.facts and second.facts


def test_official_and_article_edges_dedupe_and_form_mixed_multihop(db_session) -> None:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    _add_official_mapping(
        db_session,
        host="b-club.statusmatch.com",
        source_program="A Club",
        source_tier="Gold",
        target_program="B Club",
        target_tier="Gold",
    )
    _add_article_mapping(
        db_session,
        external_id="duplicate-a-b",
        source_program="A Club",
        source_tier="Gold",
        target_program="B Club",
        target_tier="Gold",
        published_at=now,
        first_collected_at=now,
    )
    _add_article_mapping(
        db_session,
        external_id="b-c",
        source_program="B Club",
        source_tier="Gold",
        target_program="C Club",
        target_tier="Platinum",
        published_at=now,
        first_collected_at=now,
    )
    _add_article_mapping(
        db_session,
        external_id="c-a-cycle",
        source_program="C Club",
        source_tier="Platinum",
        target_program="A Club",
        target_tier="Gold",
        published_at=now,
        first_collected_at=now,
    )
    service = UnifiedMembershipTreeService(db_session)

    tree = service.tree("A Club", "Gold", now=now + timedelta(days=1))
    audit = service.audit(now=now + timedelta(days=1))
    repeated_tree = service.tree("A Club", "Gold", now=now + timedelta(days=1))
    repeated_audit = service.audit(now=now + timedelta(days=1))

    assert tree.model_dump(mode="json") == repeated_tree.model_dump(mode="json")
    assert audit.model_dump(mode="json") == repeated_audit.model_dump(mode="json")
    assert len(tree.root.children) == 1
    b_node = tree.root.children[0].child
    assert b_node.node.id == "b club::gold"
    assert b_node.children[0].child.node.id == "c club::platinum"
    assert b_node.children[0].child.children[0].child.state == UnifiedTreeNodeState.CYCLE
    a_to_b = next(
        edge
        for edge in audit.edges
        if edge.source_node_id == "a club::gold"
        and edge.target_node_id == "b club::gold"
    )
    assert {item.source for item in a_to_b.contributions} == {
        MappingContributionSource.STATUSMATCH_OFFICIAL,
        MappingContributionSource.ORDINARY_ARTICLE,
    }
    user_payload = tree.model_dump(mode="json")
    assert "contributions" not in str(user_payload)
    assert "provenance" not in str(user_payload)


def test_article_then_official_edges_form_mixed_multihop_without_transitive_edge(
    db_session,
) -> None:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    _add_article_mapping(
        db_session,
        external_id="article-a-b",
        source_program="A Club",
        source_tier="Gold",
        target_program="B Club",
        target_tier="Gold",
        published_at=now,
        first_collected_at=now,
    )
    _add_official_mapping(
        db_session,
        host="c-club.statusmatch.com",
        source_program="B Club",
        source_tier="Gold",
        target_program="C Club",
        target_tier="Platinum",
    )
    service = UnifiedMembershipTreeService(db_session)

    tree = service.tree("A Club", "Gold", now=now + timedelta(days=1))
    audit = service.audit(now=now + timedelta(days=1))

    assert tree.root.children[0].child.node.id == "b club::gold"
    assert (
        tree.root.children[0].child.children[0].child.node.id
        == "c club::platinum"
    )
    assert not any(
        edge.source_node_id == "a club::gold"
        and edge.target_node_id == "c club::platinum"
        for edge in audit.edges
    )


def test_routed_statusmatch_article_never_contributes_ordinary_edge(db_session) -> None:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    opportunity, *_ = _add_article_mapping(
        db_session,
        external_id="linked-supplement",
        source_program="Source Club",
        source_tier="Gold",
        target_program="Linked Club",
        target_tier="Platinum",
        published_at=now,
        first_collected_at=now,
        routed=True,
    )

    service = UnifiedMembershipTreeService(db_session)
    tree = service.tree("Source Club", "Gold", now=now + timedelta(days=1))
    audit = service.audit(now=now + timedelta(days=1))

    assert tree.root.state == UnifiedTreeNodeState.LEAF
    assert audit.excluded_counts["ROUTED_STATUSMATCH_SUPPLEMENT"] == 1
    assert opportunity.id is not None


def test_manual_archive_restore_and_extend_are_audited(db_session) -> None:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    opportunity, *_ = _add_article_mapping(
        db_session,
        external_id="manual-ops",
        source_program="Source Club",
        source_tier="Gold",
        target_program="Target Club",
        target_tier="Platinum",
        published_at=now,
        first_collected_at=now,
    )

    archive_article_mapping(
        db_session,
        opportunity_id=opportunity.id,
        reason="activity was reported unavailable",
        now=now + timedelta(days=1),
    )
    assert opportunity.archive_reason == ArticleArchiveReason.MANUAL
    restore_article_mapping(
        db_session,
        opportunity_id=opportunity.id,
        reason="report was corrected",
        now=now + timedelta(days=2),
    )
    new_until = now + timedelta(days=365)
    extend_article_mapping(
        db_session,
        opportunity_id=opportunity.id,
        visibility_until_at=new_until,
        reason="manual verification found the offer still active",
        now=now + timedelta(days=3),
    )

    assert opportunity.visibility_until_at == new_until
    assert opportunity.visibility_policy == ArticleVisibilityPolicy.MANUAL_OVERRIDE
    assert opportunity.archived_at is None
    decisions = list(
        db_session.scalars(
            select(ReviewDecision).where(
                ReviewDecision.entity_id == opportunity.id
            )
        )
    )
    assert [item.action for item in decisions] == [
        "ARCHIVE_ARTICLE_MAPPING",
        "RESTORE_ARTICLE_MAPPING",
        "EXTEND_ARTICLE_MAPPING",
    ]
    assert all(item.payload["before"] != item.payload["after"] for item in decisions)

    archive_article_mapping(
        db_session,
        opportunity_id=opportunity.id,
        reason="archive again",
        now=new_until + timedelta(days=1),
    )
    with pytest.raises(ValueError, match="future visibility time"):
        restore_article_mapping(
            db_session,
            opportunity_id=opportunity.id,
            reason="invalid expired restore",
            now=new_until + timedelta(days=2),
        )


def test_conditional_is_visible_while_conflict_and_unavailable_are_excluded(
    db_session,
) -> None:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    _add_article_mapping(
        db_session,
        external_id="conditional",
        source_program="Source Club",
        source_tier="Gold",
        target_program="Conditional Club",
        target_tier="Platinum",
        published_at=now,
        first_collected_at=now,
        conditions="complete a 10-night challenge",
    )
    _add_article_mapping(
        db_session,
        external_id="conditional-second-report",
        source_program="Source Club",
        source_tier="Gold",
        target_program="Conditional Club",
        target_tier="Platinum",
        published_at=now + timedelta(days=1),
        first_collected_at=now + timedelta(days=1),
        conditions="resident of Exampleland",
    )
    _add_article_mapping(
        db_session,
        external_id="conflicting",
        source_program="Source Club",
        source_tier="Gold",
        target_program="Conflict Club",
        target_tier="Diamond",
        published_at=now,
        first_collected_at=now,
        conflict=True,
    )
    _add_article_mapping(
        db_session,
        external_id="unavailable",
        source_program="Source Club",
        source_tier="Gold",
        target_program="Unavailable Club",
        target_tier="Silver",
        published_at=now,
        first_collected_at=now,
        availability="UNAVAILABLE",
    )

    service = UnifiedMembershipTreeService(db_session)
    tree = service.tree("Source Club", "Gold", now=now + timedelta(days=2))
    audit = service.audit(now=now + timedelta(days=2))

    assert [edge.child.node.id for edge in tree.root.children] == [
        "conditional club::platinum"
    ]
    assert tree.root.children[0].conditional is True
    assert tree.root.children[0].conditions == [
        "complete a 10-night challenge",
        "resident of Exampleland",
    ]
    conditional_edge = next(
        edge
        for edge in audit.edges
        if edge.target_node_id == "conditional club::platinum"
    )
    assert len(conditional_edge.contributions) == 2
    visibility_windows = sorted(
        item.visible_until_at for item in conditional_edge.contributions
    )
    assert visibility_windows[1] - visibility_windows[0] == timedelta(days=1)
    assert audit.excluded_counts["CONFLICTING"] == 1
    assert audit.excluded_counts["UNAVAILABLE"] == 1


def test_latest_successful_document_version_replaces_old_mapping_without_resetting_window(
    db_session,
) -> None:
    published = datetime(2026, 8, 24, 10, tzinfo=UTC)
    first, _analysis, item, _document = _add_article_mapping(
        db_session,
        external_id="versioned-mapping",
        source_program="Old Source",
        source_tier="Gold",
        target_program="Target Club",
        target_tier="Platinum",
        published_at=published,
        first_collected_at=published + timedelta(hours=1),
    )
    new_quote = "New Source Diamond maps directly to Target Club Platinum."
    digest = sha256(new_quote.encode()).hexdigest()
    new_document = DocumentVersion(
        source_item_id=item.id,
        canonical_url=item.canonical_url,
        raw_body=new_quote,
        normalized_body=new_quote,
        content_type="text/plain",
        storage_mode="full",
        raw_hash=digest,
        normalized_hash=digest,
        parser_version="unified-test-v2",
        fetched_at=published + timedelta(days=2),
        created_at=published + timedelta(days=2),
    )
    db_session.add(new_document)
    db_session.flush()
    new_analysis = ArticleAnalysisRecord(
        document_version_id=new_document.id,
        source_item_id=item.id,
        analysis_run_id=uuid4(),
        input_version=str(new_document.id),
        label="STATUS_OPPORTUNITY",
        confidence=0.99,
        reason="updated direct mapping",
        status="SUCCEEDED",
        content_signature=digest,
        created_at=published + timedelta(days=2),
    )
    db_session.add(new_analysis)
    db_session.flush()
    opportunity_id = uuid4()
    evidence = EvidenceRef(
        document_version_id=new_document.id,
        source_url=item.canonical_url,
        locator=new_quote,
    )
    facts = FactSet(
        event_id=opportunity_id,
        what_happened=FactField(value=new_quote, evidence=[evidence]),
        status_mappings=[
            StatusMapping(
                source_program="New Source",
                source_tiers=["Diamond"],
                target_tier="Platinum",
                availability="AVAILABLE",
                evidence=[evidence],
            )
        ],
    )
    new_until, new_policy = calculate_mapping_visibility(
        application_deadline_at=None,
        published_at=item.published_at,
        first_collected_at=item.created_at,
    )
    db_session.add(
        ArticleOpportunityRecord(
            id=opportunity_id,
            analysis_id=new_analysis.id,
            opportunity_index=0,
            program="Target Club",
            target_status="Platinum",
            summary=new_quote,
            lifecycle_status="UNKNOWN",
            visibility_until_at=new_until,
            visibility_policy=new_policy,
            action_links=[],
            facts=facts.model_dump(mode="json"),
            fact_signature=digest,
            status="DRAFT",
        )
    )
    db_session.flush()
    service = UnifiedMembershipTreeService(db_session)

    old_tree = service.tree("Old Source", "Gold", now=published + timedelta(days=3))
    new_tree = service.tree(
        "New Source", "Diamond", now=published + timedelta(days=3)
    )

    assert old_tree.root.state == UnifiedTreeNodeState.LEAF
    assert len(new_tree.root.children) == 1
    assert new_until == first.visibility_until_at
    assert new_until == published + timedelta(days=180)
