from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from fastapi.testclient import TestClient
from sqlalchemy import select

from journeyplus.cli import build_parser
from journeyplus.contracts import EvidenceRef, FactField, FactSet, StatusMapping
from journeyplus.models import (
    DocumentVersion,
    FactSetRecord,
    SourceItem,
    StatusEvent,
    StatusMatchWatch,
    StatusMatchWatchPage,
)
from journeyplus.review.api import create_review_app
from journeyplus.sources.registry import seed_sources
from journeyplus.statusmatch.graph import MembershipGraphService
from journeyplus.statusmatch.graph_contracts import (
    GraphCertainty,
    TraversalLimits,
    TreeNodeState,
)


def _mapping_html(
    source_header: str,
    target_program: str,
    rows: list[tuple[str, str]],
) -> str:
    body = "".join(
        f"<tr><td>{program}</td><td>{tier}</td></tr>" for program, tier in rows
    )
    return (
        "<html><body><table>"
        f"<tr><td></td><td>{target_program} Tier</td></tr>"
        f"<tr><td>{source_header}</td><td>GOLD</td></tr>"
        f"{body}</table></body></html>"
    )


def _add_project(
    session,
    *,
    host: str,
    program: str,
    mappings: list[dict],
    faq_html: str | None = None,
    watch_status: str = "ACTIVE",
):
    seed_sources(session)
    now = datetime.now(UTC)
    documents: dict[str, DocumentVersion] = {}
    for kind, body in (
        ("activity", "<html><body><form>Apply</form></body></html>"),
        ("faq", faq_html or "<html><body>FAQ</body></html>"),
        ("terms", "<html><body>Project terms</body></html>"),
    ):
        url = (
            f"https://{host}/"
            if kind == "activity"
            else f"https://{host}/{kind}"
        )
        item = SourceItem(
            source_id="status_services_mail",
            external_id=f"graph-test:{host}:{kind}",
            discovered_url=url,
            canonical_url=url,
            title=f"{program} {kind}",
            observed_at=now,
            raw_metadata={},
        )
        session.add(item)
        session.flush()
        digest = sha256(body.encode()).hexdigest()
        document = DocumentVersion(
            source_item_id=item.id,
            canonical_url=url,
            raw_body=body,
            normalized_body=body,
            content_type="text/html",
            storage_mode="full",
            raw_hash=digest,
            normalized_hash=digest,
            parser_version="graph-test-v1",
            fetched_at=now,
        )
        session.add(document)
        session.flush()
        documents[kind] = document

    event = StatusEvent(
        created_from_key=f"graph-test:{host}",
        program=program,
        target_status=None,
        summary=f"{program} mapping",
        search_text=program,
        status="CONFIRMED",
    )
    session.add(event)
    session.flush()
    evidence = EvidenceRef(
        document_version_id=documents["faq"].id,
        source_url=documents["faq"].canonical_url,
        locator="FAQ mapping table",
    )
    status_mappings = [
        StatusMapping(evidence=[evidence], **mapping) for mapping in mappings
    ]
    facts = FactSet(
        event_id=event.id,
        what_happened=FactField(value=f"{program} mapping", evidence=[evidence]),
        status_mappings=status_mappings,
    )
    fact_record = FactSetRecord(
        event_id=event.id,
        version=1,
        schema_version=facts.schema_version,
        facts=facts.model_dump(mode="json"),
        has_conflicts=any(mapping.conflict for mapping in status_mappings),
    )
    session.add(fact_record)
    session.flush()
    event.current_fact_set_id = fact_record.id

    watch = StatusMatchWatch(
        host=host,
        status=watch_status,
        current_event_id=event.id,
    )
    session.add(watch)
    session.flush()
    for kind in ("activity", "faq", "terms"):
        session.add(
            StatusMatchWatchPage(
                watch_id=watch.id,
                page_kind=kind,
                canonical_url=documents[kind].canonical_url,
                current_document_version_id=documents[kind].id,
            )
        )
    session.flush()
    return watch, event, fact_record


def _find_node(snapshot, program: str, tier: str):
    return next(
        node
        for node in snapshot.nodes
        if node.program == program and node.tier.casefold() == tier.casefold()
    )


def test_graph_preserves_exact_conditional_and_unavailable_mapping_facts(
    db_session,
) -> None:
    _add_project(
        db_session,
        host="beta.statusmatch.com",
        program="Beta Club",
        mappings=[
            {
                "source_program": "Alpha Club",
                "source_tiers": ["Gold"],
                "target_tier": "Beta Club Gold",
                "availability": "AVAILABLE",
            },
            {
                "source_program": "Alpha Club",
                "source_tiers": ["Gold"],
                "target_tier": "Beta Club Gold",
                "availability": "CONDITIONAL",
                "conditions": "Only residents of Exampleland",
            },
            {
                "source_program": "Alpha Club",
                "source_tiers": [],
                "target_tier": "Beta Club Platinum",
                "availability": "UNAVAILABLE",
            },
        ],
    )

    service = MembershipGraphService(db_session)
    snapshot = service.build()
    audit = service.audit()

    # Official-only topology regression snapshot: exact and conditional claims
    # continue to aggregate onto the same direct edge.
    assert [
        (
            item.source_node_id,
            item.target_node_id,
            tuple(str(value) for value in item.certainties),
            item.conditional,
        )
        for item in snapshot.edges
    ] == [
        ("alpha club::gold", "beta club::gold", ("EXACT",), True),
    ]
    assert len(snapshot.edges) == 1
    edge = snapshot.edges[0]
    assert len(edge.claims) == 2
    assert edge.conditional is True
    assert all(claim.evidence[0].locator == "FAQ mapping table" for claim in edge.claims)
    assert snapshot.unavailable_mapping_count == 1
    assert audit.fidelity.expected_claim_count == 2
    assert audit.fidelity.represented_claim_count == 2
    assert audit.fidelity.missing_claim_ids == []
    assert audit.fidelity.invented_claim_ids == []
    assert audit.fidelity.duplicate_claim_ids == []
    assert audit.fidelity.material_mismatch_claim_ids == []
    assert audit.fidelity.direction_mismatch_claim_ids == []
    assert audit.fidelity.missing_evidence_claim_ids == []
    assert not any(node.tier == "Platinum" for node in snapshot.nodes)


def test_aliases_connect_target_to_later_source_and_ambiguity_is_reported(
    db_session,
) -> None:
    _add_project(
        db_session,
        host="flying.statusmatch.com",
        program="Flying Blue",
        mappings=[
            {
                "source_program": "Alpha Air",
                "source_tiers": ["Gold"],
                "target_tier": "Flying Blue Gold",
                "availability": "AVAILABLE",
            },
            {
                "source_program": "Alpha Air",
                "source_tiers": ["Platinum"],
                "target_tier": "Flying Blue Platinum",
                "availability": "AVAILABLE",
            },
        ],
    )
    _add_project(
        db_session,
        host="nomad.statusmatch.com",
        program="Air Astana Nomad Club",
        mappings=[
            {
                "source_program": "Air France Flying Blue",
                "source_tiers": ["Gold"],
                "target_tier": "Nomad Club Gold",
                "availability": "AVAILABLE",
            },
            {
                "source_program": "Air France Flying Blue",
                "source_tiers": ["Silver"],
                "target_tier": "Nomad Club Silver",
                "availability": "AVAILABLE",
            },
        ],
    )
    _add_project(
        db_session,
        host="shared-one.statusmatch.com",
        program="One Rewards",
        mappings=[
            {
                "source_program": "Seed One",
                "source_tiers": ["Gold"],
                "target_tier": "Shared Club Gold",
                "availability": "AVAILABLE",
            },
            {
                "source_program": "Seed One",
                "source_tiers": ["Silver"],
                "target_tier": "Shared Club Silver",
                "availability": "AVAILABLE",
            },
        ],
    )
    _add_project(
        db_session,
        host="shared-two.statusmatch.com",
        program="Two Rewards",
        mappings=[
            {
                "source_program": "Shared Club",
                "source_tiers": ["Gold"],
                "target_tier": "Shared Club Gold",
                "availability": "AVAILABLE",
            },
            {
                "source_program": "Shared Club",
                "source_tiers": ["Silver"],
                "target_tier": "Shared Club Silver",
                "availability": "AVAILABLE",
            },
        ],
    )

    service = MembershipGraphService(db_session)
    tree = service.tree("Air France Flying Blue", "Gold")
    audit = service.audit()

    assert tree.root.node.id == "flying blue::gold"
    assert any(
        edge.child.node.id == "air astana nomad club::gold"
        for edge in tree.root.children
    )
    assert any(
        ambiguity.raw_program == "Shared Club"
        and set(ambiguity.candidate_program_keys) == {"one rewards", "two rewards"}
        for ambiguity in audit.topology.alias_ambiguities
    )


def test_category_wildcard_and_uncertain_rules_are_explicit(db_session) -> None:
    airline_html = _mapping_html(
        "Airline",
        "Other Club",
        [("Alpha Air", "Gold")],
    )
    _add_project(
        db_session,
        host="other.statusmatch.com",
        program="Example Air Rewards",
        mappings=[
            {
                "source_program": "Alpha Air",
                "source_tiers": ["Gold"],
                "target_tier": "Example Air Rewards Gold",
                "availability": "AVAILABLE",
            },
            {
                "source_program": "Alpha Air",
                "source_tiers": ["Elite status"],
                "target_tier": "Example Air Rewards Silver",
                "availability": "AVAILABLE",
            },
        ],
        faq_html=airline_html,
    )
    _add_project(
        db_session,
        host="avolta.statusmatch.com",
        program="Club Avolta",
        mappings=[
            {
                "source_program": "All major airlines",
                "source_tiers": ["All membership levels"],
                "target_tier": "Club Avolta Gold status",
                "availability": "AVAILABLE",
            }
        ],
        faq_html=_mapping_html(
            "Airline",
            "Club Avolta",
            [("All major airlines", "All membership levels")],
        ),
    )
    _add_project(
        db_session,
        host="hotel.statusmatch.com",
        program="Hotel Target",
        mappings=[
            {
                "source_program": "Example Hotel",
                "source_tiers": ["Gold"],
                "target_tier": "Hotel Target Gold",
                "availability": "AVAILABLE",
            }
        ],
        faq_html=_mapping_html(
            "Hotels",
            "Hotel Target",
            [("Example Hotel", "Gold")],
        ),
    )

    service = MembershipGraphService(db_session)
    snapshot = service.build()
    airline = service.tree("Alpha Air", "Gold")
    hotel = service.tree("Example Hotel", "Gold")
    target_only_airline = service.tree("Example Air Rewards", "Gold")

    # Official-only topology regression snapshot: wildcard and uncertain
    # mappings remain explicit rules instead of invented concrete edges.
    rule_snapshot = [
        (
            item.source_program_key,
            str(item.source_category),
            item.source_tier_key,
            item.target_node_id,
            str(item.certainty),
        )
        for item in snapshot.rules
    ]
    assert sorted(rule_snapshot, key=repr) == sorted([
        (None, "AIRLINE", None, "club avolta::gold", "WILDCARD"),
        ("alpha air", "UNKNOWN", None, "example air rewards::silver", "UNCERTAIN"),
    ], key=repr)
    airline_targets = {
        edge.child.node.id: edge for edge in airline.root.children
    }
    assert airline_targets["club avolta::gold"].certainties == [
        GraphCertainty.WILDCARD
    ]
    assert airline_targets["club avolta::gold"].derived_from_rule is True
    assert airline_targets["example air rewards::silver"].certainties == [
        GraphCertainty.UNCERTAIN
    ]
    assert airline_targets["example air rewards::silver"].derived_from_rule is True
    assert "club avolta::gold" not in {
        edge.child.node.id for edge in hotel.root.children
    }
    assert "club avolta::gold" in {
        edge.child.node.id for edge in target_only_airline.root.children
    }


def test_tree_is_multihop_finite_and_marks_cycles_and_cross_references(
    db_session,
) -> None:
    _add_project(
        db_session,
        host="a.statusmatch.com",
        program="A Club",
        mappings=[
            {
                "source_program": "B Club",
                "source_tiers": ["Gold"],
                "target_tier": "A Club Gold",
                "availability": "AVAILABLE",
            }
        ],
    )
    _add_project(
        db_session,
        host="b.statusmatch.com",
        program="B Club",
        mappings=[
            {
                "source_program": "A Club",
                "source_tiers": ["Gold"],
                "target_tier": "B Club Gold",
                "availability": "AVAILABLE",
            }
        ],
    )
    _add_project(
        db_session,
        host="c.statusmatch.com",
        program="C Club",
        mappings=[
            {
                "source_program": "A Club",
                "source_tiers": ["Gold"],
                "target_tier": "C Club Gold",
                "availability": "AVAILABLE",
            },
            {
                "source_program": "B Club",
                "source_tiers": ["Gold"],
                "target_tier": "C Club Gold",
                "availability": "AVAILABLE",
            },
        ],
    )

    service = MembershipGraphService(db_session)
    snapshot = service.build()
    tree = service.tree(
        "A Club",
        "Gold",
        limits=TraversalLimits(max_depth=5, max_nodes=20, max_branches=10),
    )

    # Official-only topology regression snapshot: multi-hop traversal does not
    # persist a transitive A -> C edge, and the A <-> B cycle remains intact.
    assert sorted(
        (item.source_node_id, item.target_node_id) for item in snapshot.edges
    ) == [
        ("a club::gold", "b club::gold"),
        ("a club::gold", "c club::gold"),
        ("b club::gold", "a club::gold"),
        ("b club::gold", "c club::gold"),
    ]
    assert [edge.child.node.id for edge in tree.root.children] == [
        "b club::gold",
        "c club::gold",
    ]
    b_branch = tree.root.children[0].child
    assert b_branch.children[0].child.state == TreeNodeState.CYCLE
    assert b_branch.children[1].child.node.id == "c club::gold"
    assert tree.root.children[1].child.state == TreeNodeState.CROSS_REFERENCE
    assert tree.cycle_count == 1
    assert tree.cross_reference_count == 1
    assert tree.occurrence_count == 5


def test_tree_limits_are_explicit_and_order_is_stable(db_session) -> None:
    mappings = [
        {
            "source_program": "Root Club",
            "source_tiers": ["Gold"],
            "target_tier": f"Target Club {tier}",
            "availability": "AVAILABLE",
        }
        for tier in ("Silver", "Gold", "Platinum")
    ]
    _add_project(
        db_session,
        host="target.statusmatch.com",
        program="Target Club",
        mappings=mappings,
    )
    service = MembershipGraphService(db_session)

    first = service.tree(
        "Root Club",
        "Gold",
        limits=TraversalLimits(max_depth=1, max_nodes=10, max_branches=2),
    )
    second = service.tree(
        "Root Club",
        "Gold",
        limits=TraversalLimits(max_depth=1, max_nodes=10, max_branches=2),
    )
    node_limited = service.tree(
        "Root Club",
        "Gold",
        limits=TraversalLimits(max_depth=2, max_nodes=2, max_branches=10),
    )

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.root.state == TreeNodeState.BRANCH_LIMIT
    assert first.root.omitted_count == 1
    assert node_limited.root.state == TreeNodeState.NODE_LIMIT
    assert node_limited.root.omitted_count == 2


def test_graph_uses_only_current_active_facts_and_exposes_api_and_cli(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        _add_project(
            session,
            host="active.statusmatch.com",
            program="Active Club",
            mappings=[
                {
                    "source_program": "Source Club",
                    "source_tiers": ["Gold"],
                    "target_tier": "Active Club Gold",
                    "availability": "AVAILABLE",
                }
            ],
        )
        _add_project(
            session,
            host="archived.statusmatch.com",
            program="Archived Club",
            mappings=[
                {
                    "source_program": "Source Club",
                    "source_tiers": ["Gold"],
                    "target_tier": "Archived Club Gold",
                    "availability": "AVAILABLE",
                }
            ],
            watch_status="ARCHIVED",
        )

    client = TestClient(create_review_app(session_factory))
    tree_response = client.get(
        "/internal/statusmatch/graph/tree",
        params={"program": "Source Club", "tier": "Gold"},
    )
    audit_response = client.get("/internal/statusmatch/graph/audit")

    assert tree_response.status_code == 200
    assert [
        edge["child"]["node"]["id"]
        for edge in tree_response.json()["root"]["children"]
    ] == ["active club::gold"]
    assert audit_response.status_code == 200
    assert len(audit_response.json()["watch_ids"]) == 1
    assert audit_response.json()["fidelity"]["missing_claim_ids"] == []
    parsed = build_parser().parse_args(
        [
            "statusmatch-graph",
            "Source Club",
            "Gold",
            "--max-depth",
            "3",
        ]
    )
    assert parsed.command == "statusmatch-graph"
    assert parsed.max_depth == 3
    assert build_parser().parse_args(
        ["statusmatch-graph-audit"]
    ).command == "statusmatch-graph-audit"
