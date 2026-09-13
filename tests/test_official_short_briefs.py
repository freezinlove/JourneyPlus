from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from journeyplus.contracts import ApplicationRoute, FactField, FactSet, RoutePrice
from journeyplus.models import AnalysisRun, BriefRecord, FactSetRecord, StatusEvent
from journeyplus.product.api import create_product_app
from journeyplus.product.brief_data import fee_view
from journeyplus.product.holdings import StatusHoldingService
from journeyplus.product.contracts import StatusHoldingInput
from journeyplus.membership.unified import UnifiedMembershipTreeService
from journeyplus.statusmatch.project_workflow import process_pending_statusmatch_projects
from tests.test_agent_workflow_reads import original_factory
from tests.test_statusmatch_project_workflow import ProjectProvider, _extraction, _seed_active_watch


@pytest.mark.parametrize("prices,cost,expected,conditional", [
    ([], None, "FREE", False),
    ([], "免费", "FREE", False),
    ([], "收费，金额未公布", "PAID", False),
    ([(0, "AVAILABLE")], None, "FREE", False),
    ([(99, "AVAILABLE")], None, "PAID", False),
    ([(0, "AVAILABLE"), (99, "AVAILABLE")], None, "MIXED", False),
    ([(0, "AVAILABLE"), (50, "CONDITIONAL")], None, "FREE", True),
    ([(50, "CONDITIONAL")], None, "UNKNOWN", True),
    ([(None, "UNAVAILABLE")], None, "UNKNOWN", False),
    ([(None, "UNKNOWN")], None, "UNKNOWN", False),
    ([(99, "AVAILABLE")], "免费", "PAID", False),
])
def test_fee_badge_uses_scoped_prices_and_defaults_missing_cost_to_free(prices, cost, expected, conditional):
    facts = FactSet(event_id=uuid4(), what_happened=FactField(value="匹配"),
                    cost=FactField(value=cost), application_routes=[ApplicationRoute(
                        scope="申请", eligibility="会员", prices=[RoutePrice(
                            target_tier="Gold", amount=amount, currency="USD" if amount is not None else None,
                            availability=availability,
                        ) for amount, availability in prices],
                    )])
    view = fee_view(facts)
    assert view.status == expected
    assert view.has_conditional_fees == conditional


def test_missing_cost_defaults_free_but_conflict_is_not_labelled_free():
    facts = FactSet(event_id=uuid4(), what_happened=FactField(value="匹配"),
                    application_routes=[ApplicationRoute(scope="免费路线", cost="免费"),
                                        ApplicationRoute(scope="未知路线", eligibility="其他会员")])
    assert fee_view(facts).status == "FREE"
    facts.cost = FactField(conflict=True, alternatives=["免费", "收费"])
    assert fee_view(facts).status == "UNKNOWN"


def test_publication_failure_reuses_model_output_and_never_exposes_half_a_version(original_factory, monkeypatch):
    with original_factory.begin() as session:
        _seed_active_watch(session)
    provider = ProjectProvider([_extraction()])
    from journeyplus.statusmatch import project_workflow as workflow
    real_save = workflow.save_official_brief

    def fail_save(*args, **kwargs):
        raise RuntimeError("simulated brief save failure")

    monkeypatch.setattr(workflow, "save_official_brief", fail_save)
    failed = process_pending_statusmatch_projects(original_factory, provider)
    assert (failed.failed, failed.model_calls) == (1, 1)
    with original_factory() as session:
        assert session.scalar(select(func.count()).select_from(FactSetRecord)) == 0
        assert session.scalar(select(func.count()).select_from(BriefRecord)) == 0
        event = session.scalar(select(StatusEvent))
        assert event.current_fact_set_id is None and event.current_brief_id is None
        run = session.scalar(select(AnalysisRun))
        assert run.status == "FAILED"
        assert run.result["extraction"]["identity"]["title"]
    monkeypatch.setattr(workflow, "save_official_brief", real_save)
    recovered = process_pending_statusmatch_projects(original_factory, provider)
    assert (recovered.succeeded, recovered.model_calls) == (1, 0), recovered.errors
    assert process_pending_statusmatch_projects(original_factory, provider).model_calls == 0


def test_short_brief_api_relations_refresh_without_changing_brief_version(original_factory):
    with original_factory.begin() as session:
        _seed_active_watch(session)
    output = _extraction(narrative_mappings=[{
        "source_program": "Example Air", "source_tiers": ["Gold"], "target_tier": "Gold", "availability": "AVAILABLE",
    }])
    output["application_routes"][0]["prices"] = [{
        "target_tier": "Gold", "amount": 99, "currency": "USD", "availability": "AVAILABLE",
    }]
    provider = ProjectProvider([output])
    result = process_pending_statusmatch_projects(original_factory, provider)
    assert (result.succeeded, result.model_calls) == (1, 1), result.errors
    client = TestClient(create_product_app(original_factory))
    item = client.get("/v1/briefs").json()["items"][0]
    assert item["relationship"]["status"] == "NO_HOLDINGS"
    assert item["fee"]["status"] == "PAID"
    assert item["action_links"] == ["https://example.statusmatch.com/"]
    detail = client.get(f"/v1/match-opportunities/{item['opportunity_id']}").json()
    assert len(detail["facts"]["status_mappings"]) == 1
    assert detail["brief"]["schema_version"] == "statusmatch-brief-1"
    assert set(detail["brief"]) == {"schema_version", "fact_set_id", "title", "summary", "source_links"}
    assert detail["brief_updated_at"] == item["updated_at"]
    with original_factory.begin() as session:
        catalog = UnifiedMembershipTreeService(session).catalog()
        node = next(n for n in catalog.nodes if n.program == "Example Air" and n.tier == "Gold")
        holding = StatusHoldingService(session).upsert(StatusHoldingInput(program_key=node.program_key, tier_key=node.tier_key))
        holding_id = holding.id
    related = client.get("/v1/briefs").json()["items"][0]
    assert related["relationship"]["status"] == "DIRECT"
    assert related["updated_at"] == item["updated_at"]
    with original_factory.begin() as session:
        StatusHoldingService(session).delete(holding_id)
    assert client.get("/v1/briefs").json()["items"][0]["relationship"]["status"] == "NO_HOLDINGS"
    assert len(provider.calls) == 1
