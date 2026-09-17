from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from journeyplus.ai.provider import AIProviderMetadata
from journeyplus.contracts import Brief, FactSet, OpportunityKind
from journeyplus.models import (
    AnalysisRun,
    BriefRecord,
    DocumentVersion,
    EventEvidence,
    FactSetRecord,
    JobRun,
    StatusEvent,
    StatusMatchChangeSet,
    StatusMatchWatch,
    StatusMatchWatchPage,
)
from journeyplus.sources.base import FetchResponse
from journeyplus.sources.registry import seed_sources
from journeyplus.statusmatch.contracts import StatusMatchProjectExtraction
from journeyplus.statusmatch.audit import audit_statusmatch_projects
from journeyplus.statusmatch.project_workflow import (
    backfill_current_statusmatch_change_sets,
    process_pending_statusmatch_projects,
)
from journeyplus.statusmatch.service import monitor_statusmatch_watches
from journeyplus.statusmatch.watchlist import (
    delete_watch_only,
    ensure_statusmatch_watch,
)


ACTIVE_ACTIVITY = """
<html><body><h1>Apply for a Status Match today</h1>
<p>Example Air members may apply for Example Club Gold.</p>
<form><button>Continue</button></form></body></html>
"""
ACTIVE_FAQ = """
<html><body><h1>Frequently Asked Questions</h1>
<p>Current members of Example Air with Gold status are eligible.</p>
</body></html>
"""
ACTIVE_TERMS = """
<html><body><h1>Example Club Status Match Terms</h1>
<p>Current project-specific terms.</p>
<h2>StatusMatch.Com Terms of Use</h2><p>Common platform terms.</p>
</body></html>
"""


class PageFetcher:
    def __init__(self, responses: dict[str, str | Exception]) -> None:
        self.responses = responses

    def get(self, url: str) -> FetchResponse:
        value = self.responses[url]
        if isinstance(value, Exception):
            raise value
        return FetchResponse(body=value, content_type="text/html", final_url=url)


class ProjectProvider:
    metadata = AIProviderMetadata(
        provider="test",
        model="statusmatch-project",
        region="local",
        config_version="statusmatch-project-test-v1",
    )

    def __init__(self, extractions: list[dict]) -> None:
        self.extractions = list(extractions)
        self.calls: list[dict] = []

    def generate_structured(
        self, *, system_prompt: str, user_prompt: str, output_model
    ):
        request = json.loads(user_prompt)
        self.calls.append(
            {
                "model": output_model.__name__,
                "request": request,
                "system_prompt": system_prompt,
            }
        )
        if output_model is StatusMatchProjectExtraction:
            if not self.extractions:
                raise RuntimeError("No project extraction remains")
            return output_model.model_validate(self.extractions.pop(0))
        raise AssertionError(f"Unexpected output model: {output_model}")


def _responses(host: str = "example.statusmatch.com") -> dict[str, str]:
    return {
        f"https://{host}/": ACTIVE_ACTIVITY,
        f"https://{host}/faq": ACTIVE_FAQ,
        f"https://{host}/terms": ACTIVE_TERMS,
    }


def _extraction(
    host: str = "example.statusmatch.com",
    *,
    eligibility: str = "Example Air Gold 会员",
    narrative_mappings: list[dict] | None = None,
) -> dict:
    return {
        "schema_version": "1",
        "identity": {
            "program": "Example Club",
            "title": "Example Club 开放会籍匹配",
            "summary": f"{host} 当前开放会籍匹配",
            "target_status": "Gold",
        },
        "what_happened": {
            "value": "Example Club 当前开放 Gold 会籍匹配",
            "evidence": [{"source": "HOME", "locator": "application heading"}],
        },
        "eligibility": {
            "value": eligibility,
            "evidence": [{"source": "FAQ", "locator": "eligibility paragraph"}],
        },
        "target_status": {
            "value": "Gold",
            "evidence": [{"source": "HOME", "locator": "offer paragraph"}],
        },
        "action_link": {
            "value": f"https://{host}/",
            "evidence": [{"source": "HOME", "locator": "application form"}],
        },
        "application_routes": [
            {
                "scope": "默认申请路径",
                "eligibility": eligibility,
                "action_link": f"https://{host}/",
                "evidence": [
                    {"source": "HOME", "locator": "application form"},
                    {"source": "FAQ", "locator": "eligibility paragraph"},
                ],
            }
        ],
        "narrative_status_mappings": narrative_mappings or [],
    }


def _seed_active_watch(session, host: str = "example.statusmatch.com"):
    seed_sources(session)
    watch = ensure_statusmatch_watch(session, host)
    monitor_statusmatch_watches(session, PageFetcher(_responses(host)))
    session.refresh(watch)
    return watch


def test_initial_project_uses_one_call_and_saves_brief_without_generic_analysis(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        watch = _seed_active_watch(session)
        watch_id = watch.id

    provider = ProjectProvider([_extraction()])
    summary = process_pending_statusmatch_projects(session_factory, provider)

    assert (summary.selected, summary.succeeded, summary.failed) == (1, 1, 0)
    assert summary.model_calls == 1
    assert [item["model"] for item in provider.calls] == [
        "StatusMatchProjectExtraction",
    ]
    with session_factory() as session:
        watch = session.get(StatusMatchWatch, watch_id)
        assert watch is not None and watch.current_event_id is not None
        event = session.get(StatusEvent, watch.current_event_id)
        assert event is not None
        assert event.program == "Example Club"
        assert session.scalar(
            select(func.count()).select_from(StatusEvent)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(FactSetRecord)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(BriefRecord)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(StatusMatchChangeSet)
        ) == 1
        assert set(session.scalars(select(AnalysisRun.stage))) == {
            "STATUSMATCH_PROJECT_EXTRACTION",
        }
        evidence_ids = set(
            session.scalars(
                select(EventEvidence.document_version_id).where(
                    EventEvidence.event_id == event.id
                )
            )
        )
        page_ids = set(
            session.scalars(
                select(StatusMatchWatchPage.current_document_version_id).where(
                    StatusMatchWatchPage.watch_id == watch.id
                )
            )
        )
        assert evidence_ids == page_ids
        record = session.scalar(select(FactSetRecord))
        assert record is not None
        assert (
            FactSet.model_validate(record.facts).opportunity_kind
            == OpportunityKind.STATUS_MATCH
        )


def test_project_extracts_evidenced_route_prices_without_extra_model_stage(
    session_factory,
) -> None:
    responses = _responses()
    responses["https://example.statusmatch.com/"] = ACTIVE_ACTIVITY.replace(
        "</body>", "<p>Gold route fee is USD 99.</p></body>"
    )
    with session_factory.begin() as session:
        seed_sources(session)
        ensure_statusmatch_watch(session, "example.statusmatch.com")
        monitor_statusmatch_watches(session, PageFetcher(responses))
    extraction = _extraction()
    extraction["application_routes"][0].update(
        {
            "cost": "Gold route fee is USD 99",
            "prices": [
                {
                    "target_tier": "Gold",
                    "amount": 99,
                    "currency": "USD",
                    "availability": "AVAILABLE",
                    "raw_text": "Gold route fee is USD 99",
                    "evidence": [
                        {
                            "source": "HOME",
                            "locator": "Gold route fee is USD 99",
                        }
                    ],
                }
            ],
        }
    )

    summary = process_pending_statusmatch_projects(
        session_factory, ProjectProvider([extraction])
    )

    assert summary.succeeded == 1
    assert summary.model_calls == 1
    with session_factory() as session:
        record = session.scalar(select(FactSetRecord))
        assert record is not None
        facts = FactSet.model_validate(record.facts)
        assert facts.opportunity_kind == OpportunityKind.STATUS_MATCH
        assert facts.application_routes[0].prices[0].currency == "USD"
        assert facts.application_routes[0].prices[0].amount == 99


def test_project_publishes_same_named_regional_routes_without_false_conflict(session_factory):
    with session_factory.begin() as session:
        _seed_active_watch(session)
    extraction = _extraction()
    extraction["application_routes"] = [
        {"scope": "Airline Status Match", "region": region,
         "prices": [{"target_tier": "Gold", "amount": amount,
                     "currency": "USD", "availability": "AVAILABLE"}]}
        for region, amount in [("Americas", 299), ("All other countries", 175)]
    ]
    provider = ProjectProvider([extraction])
    result = process_pending_statusmatch_projects(session_factory, provider)
    assert result.succeeded == 1 and result.failed == 0
    assert result.model_calls == 1
    with session_factory() as session:
        record = session.scalar(select(FactSetRecord))
        assert record is not None and not record.has_conflicts
        facts = FactSet.model_validate(record.facts)
        assert len({route.scope for route in facts.application_routes}) == 2
        assert [(route.region, route.prices[0].amount) for route in facts.application_routes] == [
            ("Americas", 299), ("All other countries", 175),
        ]
        assert session.scalar(select(StatusEvent)).status != "NEEDS_REVIEW"
        assert session.scalar(select(func.count()).select_from(BriefRecord)) == 1
    repeated = process_pending_statusmatch_projects(session_factory, provider)
    assert repeated.selected == 0 and repeated.model_calls == 0


@pytest.mark.parametrize("cost_note", [None, "申请费不退"])
def test_prose_price_without_evidence_reaches_brief_with_optional_cost(
    session_factory, cost_note,
) -> None:
    responses = _responses()
    responses["https://example.statusmatch.com/faq"] += (
        "<p>The application fee for Gold is USD 99 and is non-refundable.</p>"
    )
    with session_factory.begin() as session:
        seed_sources(session)
        ensure_statusmatch_watch(session, "example.statusmatch.com")
        monitor_statusmatch_watches(session, PageFetcher(responses))
    extraction = _extraction()
    extraction["cost"] = {"value": cost_note}
    extraction["application_routes"][0]["prices"] = [{
        "target_tier": "Gold", "amount": 99, "currency": "USD",
        "availability": "AVAILABLE",
    }]

    provider = ProjectProvider([extraction])
    result = process_pending_statusmatch_projects(session_factory, provider)
    assert (result.succeeded, result.failed, result.model_calls) == (1, 0, 1), result.errors
    with session_factory() as session:
        from journeyplus.product.briefs import _price_summaries
        record = session.scalar(select(FactSetRecord))
        facts = FactSet.model_validate(record.facts)
        assert facts.cost.value == cost_note
        assert any("99" in text and "USD" in text for text in _price_summaries(facts))
        brief = session.scalar(select(BriefRecord))
        assert brief.fact_set_id == record.id
        assert "key_points" not in brief.content
        assert brief.content["title"] == extraction["identity"]["title"]


def test_terms_fee_table_is_deterministic_and_uses_no_extra_model_call(
    session_factory,
) -> None:
    responses = _responses()
    responses["https://example.statusmatch.com/terms"] = """
    <html><body><h1>Example Club Status Match Terms</h1>
    <table>
      <tr><th>Country/Region</th><th>Status Tier</th><th>Application Fee</th></tr>
      <tr><td colspan="3">Listed in USD</td></tr>
      <tr><td colspan="3">China</td></tr>
      <tr><td></td><td>Gold</td><td>USD 99</td></tr>
    </table>
    <h3>Recently ended offers</h3>
    <table>
      <tr><th>Country/Region</th><th>Status Tier</th><th>Application Fee</th></tr>
      <tr><td>Ended Region</td><td>Gold</td><td>USD 999</td></tr>
    </table>
    <ul class="list-inline"><li>Current mapping: Example Air Gold to Example Club Gold</li></ul>
    <h2>StatusMatch.Com Terms of Use</h2>
    <p>Standard membership is free and generic fees may apply.</p>
    </body></html>
    """
    with session_factory.begin() as session:
        seed_sources(session)
        ensure_statusmatch_watch(session, "example.statusmatch.com")
        monitor_statusmatch_watches(session, PageFetcher(responses))
    provider = ProjectProvider([_extraction()])

    summary = process_pending_statusmatch_projects(session_factory, provider)

    assert summary.succeeded == 1
    assert summary.model_calls == 1
    request = provider.calls[0]["request"]
    assert request["deterministic_price_routes"]["count"] == 1
    assert "TERMS" in request["documents"]
    terms_ai_body = request["documents"]["TERMS"]["body"]
    assert "StatusMatch.Com Terms of Use" not in terms_ai_body
    assert "Recently ended offers" not in terms_ai_body
    assert "Ended Region" not in terms_ai_body
    assert "USD 999" not in terms_ai_body
    assert "USD 99" not in terms_ai_body
    assert "Current mapping: Example Air Gold to Example Club Gold" in terms_ai_body
    with session_factory() as session:
        record = session.scalar(select(FactSetRecord))
        change_set = session.scalar(select(StatusMatchChangeSet))
        assert record is not None and change_set is not None
        facts = FactSet.model_validate(record.facts)
        assert facts.application_routes[0].scope == "China"
        assert facts.application_routes[0].prices[0].amount == 99
        assert facts.application_routes[0].prices[0].currency == "USD"
        assert change_set.terms_document_version_id is not None
        stored_terms = session.get(
            DocumentVersion, change_set.terms_document_version_id
        )
        assert stored_terms is not None
        assert "USD 999" in (stored_terms.raw_body or "")


def test_terms_only_update_reprocesses_project_snapshot(session_factory) -> None:
    responses = _responses()
    responses["https://example.statusmatch.com/terms"] = ACTIVE_TERMS.replace(
        "Current project-specific terms.",
        "Application fees apply and vary by eligibility.",
    )
    fetcher = PageFetcher(responses)
    with session_factory.begin() as session:
        seed_sources(session)
        ensure_statusmatch_watch(session, "example.statusmatch.com")
        monitor_statusmatch_watches(session, fetcher)
    process_pending_statusmatch_projects(
        session_factory, ProjectProvider([_extraction()])
    )
    fetcher.responses["https://example.statusmatch.com/terms"] = ACTIVE_TERMS.replace(
        "Current project-specific terms.",
        "There is no application fee payable for this status match.",
    )
    with session_factory.begin() as session:
        monitor_statusmatch_watches(session, fetcher)

    summary = process_pending_statusmatch_projects(
        session_factory, ProjectProvider([_extraction()])
    )

    assert summary.succeeded == 1
    assert summary.projects[0].change_kind == "FACTS_CHANGED"
    with session_factory() as session:
        records = list(
            session.scalars(select(FactSetRecord).order_by(FactSetRecord.version))
        )
        assert [record.facts["cost"]["value"] for record in records] == [
            "收费，金额未公布",
            "免费",
        ]
        assert session.scalar(
            select(func.count()).select_from(StatusMatchChangeSet)
        ) == 2


def test_page_update_keeps_event_and_records_structured_changes(
    session_factory,
) -> None:
    fetcher = PageFetcher(_responses())
    with session_factory.begin() as session:
        watch = _seed_active_watch(session)
        watch_id = watch.id
    first = ProjectProvider([_extraction()])
    process_pending_statusmatch_projects(session_factory, first)
    with session_factory() as session:
        watch = session.get(StatusMatchWatch, watch_id)
        assert watch is not None
        event_id = watch.current_event_id

    fetcher.responses["https://example.statusmatch.com/faq"] = (
        "<html><body><h1>FAQ</h1>"
        "<p>Example Air Platinum and Gold members are eligible.</p></body></html>"
    )
    with session_factory.begin() as session:
        monitor_statusmatch_watches(
            session, fetcher, checked_at=datetime(2026, 8, 25, tzinfo=UTC)
        )
    second = ProjectProvider(
        [_extraction(eligibility="Example Air Platinum 和 Gold 会员")]
    )
    summary = process_pending_statusmatch_projects(session_factory, second)

    assert summary.succeeded == 1
    assert summary.projects[0].event_id == str(event_id)
    assert summary.projects[0].change_kind == "FACTS_CHANGED"
    assert any(
        item["path"] == "fields.eligibility"
        for item in summary.projects[0].changes
    )
    with session_factory() as session:
        watch = session.get(StatusMatchWatch, watch_id)
        assert watch is not None and watch.current_event_id == event_id
        assert session.scalar(
            select(func.count()).select_from(StatusEvent)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(FactSetRecord)
        ) == 2
        assert session.scalar(
            select(func.count()).select_from(BriefRecord)
        ) == 2


def test_semantically_identical_page_update_reuses_fact_and_brief(
    session_factory,
) -> None:
    fetcher = PageFetcher(_responses())
    with session_factory.begin() as session:
        _seed_active_watch(session)
    process_pending_statusmatch_projects(
        session_factory, ProjectProvider([_extraction()])
    )

    fetcher.responses["https://example.statusmatch.com/faq"] = (
        ACTIVE_FAQ.replace("</body>", "<p>Page layout refreshed.</p></body>")
    )
    with session_factory.begin() as session:
        monitor_statusmatch_watches(session, fetcher)
    provider = ProjectProvider([_extraction()])
    summary = process_pending_statusmatch_projects(session_factory, provider)

    assert summary.succeeded == 1
    assert summary.projects[0].fact_reused
    assert summary.projects[0].brief_reused
    assert summary.projects[0].change_kind == "SEMANTIC_UNCHANGED"
    assert [item["model"] for item in provider.calls] == [
        "StatusMatchProjectExtraction"
    ]
    with session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(FactSetRecord)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(BriefRecord)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(StatusMatchChangeSet)
        ) == 2


def test_same_page_snapshot_skips_model_config_upgrade(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        _seed_active_watch(session)
    process_pending_statusmatch_projects(
        session_factory, ProjectProvider([_extraction()])
    )
    upgraded = ProjectProvider(
        [_extraction(eligibility="Example Air Platinum 会员")]
    )
    upgraded.metadata = AIProviderMetadata(
        provider="test",
        model="statusmatch-project",
        region="local",
        config_version="statusmatch-project-test-v2",
    )

    summary = process_pending_statusmatch_projects(session_factory, upgraded)

    assert summary.selected == summary.model_calls == 0
    assert upgraded.calls == []
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(FactSetRecord)) == 1
        assert session.scalar(select(func.count()).select_from(BriefRecord)) == 1
        assert session.scalar(select(func.count()).select_from(StatusMatchChangeSet)) == 1
        assert backfill_current_statusmatch_change_sets(session) == ()


def test_table_and_narrative_mappings_are_combined_without_duplicates(
    session_factory,
) -> None:
    responses = _responses()
    responses["https://example.statusmatch.com/faq"] = """
    <html><body><h1>Frequently Asked Questions</h1>
    <table>
      <tr><th>Existing programme and tier</th><th>Example Club tier</th></tr>
      <tr><td>Example Air Gold</td><td>Gold</td></tr>
    </table>
    <p>Partner Plus Platinum members may also receive Gold.</p>
    </body></html>
    """
    with session_factory.begin() as session:
        seed_sources(session)
        ensure_statusmatch_watch(session, "example.statusmatch.com")
        monitor_statusmatch_watches(session, PageFetcher(responses))
    narrative = {
        "source_program": "Partner Plus",
        "source_tiers": ["Platinum"],
        "target_tier": "Gold",
        "availability": "AVAILABLE",
        "evidence": [{"source": "FAQ", "locator": "Partner Plus paragraph"}],
    }
    provider = ProjectProvider([_extraction(narrative_mappings=[narrative])])
    summary = process_pending_statusmatch_projects(session_factory, provider)

    assert summary.succeeded == 1
    assert summary.projects[0].mapping_count == 2
    with session_factory() as session:
        record = session.scalar(select(FactSetRecord))
        assert record is not None
        mappings = record.facts["status_mappings"]
        assert {item["source_program"] for item in mappings} == {
            "Example Air",
            "Partner Plus",
        }
        assert {
            item["evidence"][0]["source_url"].rstrip("/") for item in mappings
        } == {"https://example.statusmatch.com/faq"}


@pytest.mark.parametrize("channel", ["table", "narrative"])
def test_table_only_and_narrative_only_mapping_channels(
    session_factory,
    channel: str,
) -> None:
    responses = _responses()
    narrative: list[dict] = []
    expected_program = "Example Air"
    if channel == "table":
        responses["https://example.statusmatch.com/faq"] = """
        <html><body><table>
          <tr><th>Existing programme and tier</th><th>Example Club tier</th></tr>
          <tr><td>Example Air Gold</td><td>Gold</td></tr>
        </table></body></html>
        """
    else:
        expected_program = "Partner Plus"
        responses["https://example.statusmatch.com/faq"] = (
            "<html><body><p>Partner Plus Platinum members receive Gold.</p>"
            "</body></html>"
        )
        narrative = [
            {
                "source_program": "Partner Plus",
                "source_tiers": ["Platinum"],
                "target_tier": "Gold",
                "availability": "AVAILABLE",
                "evidence": [
                    {"source": "FAQ", "locator": "Partner Plus paragraph"}
                ],
            }
        ]
    with session_factory.begin() as session:
        seed_sources(session)
        ensure_statusmatch_watch(session, "example.statusmatch.com")
        monitor_statusmatch_watches(session, PageFetcher(responses))

    summary = process_pending_statusmatch_projects(
        session_factory,
        ProjectProvider([_extraction(narrative_mappings=narrative)]),
    )

    assert summary.succeeded == 1
    assert summary.projects[0].mapping_count == 1
    with session_factory() as session:
        record = session.scalar(select(FactSetRecord))
        assert record is not None
        assert record.facts["status_mappings"][0]["source_program"] == expected_program


def test_invalid_alias_retries_without_persisting_partial_output(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        _seed_active_watch(session)
    invalid = deepcopy(_extraction())
    invalid["what_happened"]["evidence"][0]["source"] = "ARTICLE"
    provider = ProjectProvider([invalid, _extraction()])

    summary = process_pending_statusmatch_projects(session_factory, provider)

    assert summary.succeeded == 1
    assert [item["model"] for item in provider.calls] == [
        "StatusMatchProjectExtraction",
        "StatusMatchProjectExtraction",
    ]
    with session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(FactSetRecord)
        ) == 1


def test_explicit_null_unknowns_are_normalized_and_failed_calls_are_counted(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        _seed_active_watch(session)
    valid_with_nulls = _extraction()
    valid_with_nulls.update(
        {
            "challenge_requirements": None,
            "application_start": None,
            "deadline": None,
            "narrative_status_mappings": None,
        }
    )
    success = process_pending_statusmatch_projects(
        session_factory, ProjectProvider([valid_with_nulls])
    )
    assert success.succeeded == 1
    assert success.model_calls == 1


def test_requalification_requirement_is_mandatory_caveat_with_retry(
    session_factory,
) -> None:
    responses = _responses()
    responses["https://example.statusmatch.com/faq"] = (
        "<html><body><p>Members must requalify on merit to retain benefits "
        "beyond the initial year.</p></body></html>"
    )
    with session_factory.begin() as session:
        seed_sources(session)
        ensure_statusmatch_watch(session, "example.statusmatch.com")
        monitor_statusmatch_watches(session, PageFetcher(responses))
    corrected = _extraction()
    corrected["caveats"] = {
        "value": "首年结束后必须按正常规则重新达标才能保留会籍",
        "evidence": [{"source": "FAQ", "locator": "requalification paragraph"}],
    }
    provider = ProjectProvider([_extraction(), corrected])

    summary = process_pending_statusmatch_projects(session_factory, provider)

    assert summary.succeeded == 1
    assert summary.model_calls == 2
    assert [item["model"] for item in provider.calls] == [
        "StatusMatchProjectExtraction",
        "StatusMatchProjectExtraction",
    ]
    with session_factory() as session:
        record = session.scalar(select(FactSetRecord))
        assert record is not None
        assert "重新达标" in record.facts["caveats"]["value"]


def test_requalify_on_merit_cannot_be_over_specified_as_spend(
    session_factory,
) -> None:
    responses = _responses()
    responses["https://example.statusmatch.com/faq"] = (
        "<html><body><p>Members must requalify on merit to retain benefits "
        "beyond the initial year.</p></body></html>"
    )
    with session_factory.begin() as session:
        seed_sources(session)
        ensure_statusmatch_watch(session, "example.statusmatch.com")
        monitor_statusmatch_watches(session, PageFetcher(responses))
    over_specific = _extraction()
    over_specific["caveats"] = {
        "value": "首年结束后必须通过正常消费重新达标",
        "evidence": [{"source": "FAQ", "locator": "requalification paragraph"}],
    }
    corrected = deepcopy(over_specific)
    corrected["caveats"]["value"] = "首年结束后必须按项目正常规则重新达标"
    provider = ProjectProvider([over_specific, corrected])

    summary = process_pending_statusmatch_projects(session_factory, provider)

    assert summary.succeeded == 1
    assert summary.model_calls == 2
    with session_factory() as session:
        record = session.scalar(select(FactSetRecord))
        assert record is not None
        assert "正常规则" in record.facts["caveats"]["value"]
        assert "消费" not in record.facts["caveats"]["value"]


def test_failed_project_attempts_are_included_in_model_call_summary(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        _seed_active_watch(session)
    invalid = deepcopy(_extraction())
    invalid["what_happened"]["evidence"][0]["source"] = "ARTICLE"
    provider = ProjectProvider([invalid, invalid])

    summary = process_pending_statusmatch_projects(session_factory, provider)

    assert summary.failed == 1
    assert summary.succeeded == 0
    assert summary.model_calls == 2
    with session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(FactSetRecord)
        ) == 0


def test_missing_or_failed_page_is_not_selected(session_factory) -> None:
    with session_factory.begin() as session:
        seed_sources(session)
        ensure_statusmatch_watch(session, "example.statusmatch.com")
    provider = ProjectProvider([])
    missing = process_pending_statusmatch_projects(session_factory, provider)
    assert missing.selected == 0

    responses = _responses()
    responses["https://example.statusmatch.com/faq"] = RuntimeError("HTTP 503")
    with session_factory.begin() as session:
        monitor_statusmatch_watches(session, PageFetcher(responses))
    failed = process_pending_statusmatch_projects(session_factory, provider)
    assert failed.selected == 0
    assert provider.calls == []


def test_closed_project_is_archived_and_never_reprocessed(session_factory) -> None:
    with session_factory.begin() as session:
        watch = _seed_active_watch(session)
        watch_id = watch.id
    process_pending_statusmatch_projects(
        session_factory, ProjectProvider([_extraction()])
    )
    with session_factory() as session:
        watch = session.get(StatusMatchWatch, watch_id)
        assert watch is not None and watch.current_event_id is not None
        event_id = watch.current_event_id

    closed = _responses()
    closed["https://example.statusmatch.com/"] = (
        "<html><body><p>This status match offer has ended.</p></body></html>"
    )
    closed["https://example.statusmatch.com/faq"] = (
        "<html><body><p>This offer has expired and is no longer available.</p>"
        "</body></html>"
    )
    closed["https://example.statusmatch.com/terms"] = (
        "<html><body><p>This offer has expired and is no longer available.</p>"
        "</body></html>"
    )
    with session_factory.begin() as session:
        monitoring = monitor_statusmatch_watches(session, PageFetcher(closed))
    assert monitoring.projects_archived == 1

    provider = ProjectProvider([])
    summary = process_pending_statusmatch_projects(session_factory, provider)
    assert summary.selected == 0
    assert provider.calls == []
    with session_factory() as session:
        assert session.get(StatusMatchWatch, watch_id) is None
        event = session.get(StatusEvent, event_id)
        assert event is not None and event.archived_at is not None
        assert event.lifecycle_status == "EXPIRED"


def test_different_hosts_and_reonboarded_watch_create_distinct_events(
    session_factory,
) -> None:
    hosts = ["one.statusmatch.com", "two.statusmatch.com"]
    with session_factory.begin() as session:
        seed_sources(session)
        for host in hosts:
            ensure_statusmatch_watch(session, host)
        responses = {key: value for host in hosts for key, value in _responses(host).items()}
        monitor_statusmatch_watches(session, PageFetcher(responses))
    provider = ProjectProvider([_extraction(host) for host in hosts])
    first = process_pending_statusmatch_projects(session_factory, provider)
    assert first.succeeded == 2
    assert len({item.event_id for item in first.projects}) == 2

    with session_factory.begin() as session:
        old_watch = session.scalar(
            select(StatusMatchWatch).where(
                StatusMatchWatch.host == "one.statusmatch.com"
            )
        )
        assert old_watch is not None and old_watch.current_event_id is not None
        old_event_id = old_watch.current_event_id
        old_event = session.get(StatusEvent, old_event_id)
        assert old_event is not None
        old_event.archived_at = datetime(2026, 8, 26, tzinfo=UTC)
        delete_watch_only(session, old_watch)
        ensure_statusmatch_watch(session, "one.statusmatch.com")
        monitor_statusmatch_watches(
            session, PageFetcher(_responses("one.statusmatch.com"))
        )
    reonboard = process_pending_statusmatch_projects(
        session_factory,
        ProjectProvider([_extraction("one.statusmatch.com")]),
        hosts=["one.statusmatch.com"],
    )
    assert reonboard.succeeded == 1
    assert reonboard.projects[0].event_id != str(old_event_id)
    with session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(JobRun).where(
                JobRun.job_type == "statusmatch_project_workflow",
                JobRun.status == "SUCCEEDED",
            )
        ) == 3


def test_selected_host_audit_reports_complete_project_without_reprocessing(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        _seed_active_watch(session)
    process_pending_statusmatch_projects(
        session_factory, ProjectProvider([_extraction()])
    )

    provider = ProjectProvider([])
    report = audit_statusmatch_projects(
        session_factory,
        provider,
        hosts=["example.statusmatch.com"],
        refresh=False,
    )

    assert report["processing"]["selected"] == 0
    assert provider.calls == []
    assert report["assertions"] == {
        "classification_or_relationship_runs": 0,
        "dedicated_project_runs": 0,
        "brief_runs": 0,
        "one_live_event_per_watch": True,
    }
    project = report["projects"][0]
    assert len(project["pages"]) == 3
    assert project["event"]["program"] == "Example Club"
    assert project["fact_set"]["version"] == 1
    assert project["change_set"]["kind"] == "INITIAL_SNAPSHOT"
    assert project["brief"]["content"]["title"] == "Example Club 开放会籍匹配"
    assert project["historical_dedicated_project_runs"] == 1
    assert project["historical_brief_runs"] == 0


@pytest.mark.parametrize("bad_first_ref", [False, True])
def test_table_supplements_publish_in_place_with_existing_model_stages(
    session_factory, bad_first_ref,
):
    responses = _responses()
    responses["https://example.statusmatch.com/faq"] += """
    <table><tr><th>Airline</th><th>Gold</th></tr>
      <tr><td>Example Air</td><td>Diamond</td></tr>
      <tr><td>Second Air</td><td>Platinum</td></tr></table>
    <p>Matching requires local residence. Gold costs USD 99 in Region A and Region B.
    Platinum costs USD 399 but is currently unavailable in Region A.
    Co-branded card holders have a separate application route for Gold at USD 99.</p>
    """
    responses["https://example.statusmatch.com/terms"] = """
    <html><body><h1>Example Club Status Match Terms</h1>
    <table><tr><th>Country/Region</th><th>Status Tier</th><th>Application Fee</th></tr>
      <tr><td>Region A, Region B</td><td>Gold</td><td>USD 99</td></tr>
      <tr><td>Region A, Region B</td><td>Platinum</td><td>USD 399</td></tr></table>
    <h2>StatusMatch.Com Terms of Use</h2><p>Common platform terms.</p></body></html>
    """
    with session_factory.begin() as session:
        seed_sources(session)
        ensure_statusmatch_watch(session, "example.statusmatch.com")
        monitor_statusmatch_watches(session, PageFetcher(responses))
    extraction = _extraction()
    extraction.update(application_routes=[{
            "scope": "联名卡申请", "eligibility": "联名卡持有人", "prices": [{
                "target_tier": "Gold", "amount": 99, "currency": "USD", "availability": "AVAILABLE",
            }],
        }], narrative_status_mappings=[],
        mapping_updates=[{"ref": "m1", "availability": "CONDITIONAL", "conditions": "本地居民限定"}],
        route_updates=[
            {"ref": "r1", "scope": "地区甲", "region": "Region A",
             "price_updates": [{"ref": "p2", "availability": "UNAVAILABLE"}]},
            {"ref": "r1", "scope": "地区乙", "region": "Region B"},
        ])
    extractions = [extraction]
    if bad_first_ref:
        invalid = deepcopy(extraction)
        invalid["route_updates"][0]["ref"] = "r99"
        extractions.insert(0, invalid)
    provider = ProjectProvider(extractions)

    result = process_pending_statusmatch_projects(session_factory, provider)

    assert (result.succeeded, result.failed) == (1, 0), result.errors
    assert result.model_calls == 1 + int(bad_first_ref)
    request = provider.calls[0]["request"]
    drafts = request["deterministic_status_mappings"]
    assert drafts["count"] == 2
    assert dict(zip(drafts["columns"], drafts["rows"][0]))["source_tiers"] == ["Diamond"]
    assert "Second Air" not in request["documents"]["FAQ"]["body"]
    assert "USD 399" not in request["documents"]["TERMS"]["body"]
    with session_factory() as session:
        record = session.scalar(select(FactSetRecord))
        facts = FactSet.model_validate(record.facts)
        assert len(facts.application_routes) == 2
        assert facts.application_routes[0].scope == "Region A, Region B"
        assert facts.application_routes[0].prices[0].amount == 99
        assert facts.application_routes[0].prices[1].availability == "AVAILABLE"
        assert facts.application_routes[0].prices[1].amount == 399
        assert facts.application_routes[1].eligibility == "联名卡持有人"
        assert facts.application_routes[1].prices[0].amount == 99
        assert len(facts.status_mappings) == 2
        assert facts.status_mappings[0].conditions is None
        assert not facts.status_mappings[0].conflict
        assert facts.status_mappings[1].source_tiers == ["Platinum"]
        assert session.scalar(select(BriefRecord)).fact_set_id == record.id
        assert "route_updates" not in record.facts
        assert session.scalar(select(func.count()).select_from(FactSetRecord)) == 1
    assert process_pending_statusmatch_projects(session_factory, provider).model_calls == 0


def test_old_job_key_and_code_versions_do_not_repeat_source_snapshot(session_factory, monkeypatch):
    from journeyplus.statusmatch import project_workflow as workflow
    with session_factory.begin() as session:
        _seed_active_watch(session)
    process_pending_statusmatch_projects(session_factory, ProjectProvider([_extraction()]))
    with session_factory.begin() as session:
        job = session.scalar(select(JobRun).where(JobRun.job_type == 'statusmatch_project_workflow'))
        job.idempotency_key = job.idempotency_key.rsplit(':', 1)[0] + ':old-key-format'
        before = session.scalar(select(BriefRecord)).created_at
    monkeypatch.setattr(workflow, 'PROJECT_PROMPT_VERSION', 'future-prompt')
    monkeypatch.setattr(workflow, 'PROJECT_SCHEMA_VERSION', 'future-schema')
    monkeypatch.setattr(workflow, 'FACT_SCHEMA_VERSION', 'future-facts')
    provider = ProjectProvider([])
    result = process_pending_statusmatch_projects(session_factory, provider)
    assert result.selected == result.model_calls == 0
    assert provider.calls == []
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(BriefRecord)) == 1
        assert session.scalar(select(BriefRecord)).created_at == before


@pytest.mark.parametrize('kind', ['activity', 'faq', 'terms'])
def test_each_source_page_change_processes_once_then_skips(session_factory, kind):
    with session_factory.begin() as session:
        _seed_active_watch(session)
    process_pending_statusmatch_projects(session_factory, ProjectProvider([_extraction()]))
    responses = _responses()
    url = 'https://example.statusmatch.com' + ('/' if kind == 'activity' else '/' + kind)
    responses[url] = responses[url].replace('<body>', '<body><p>New project condition.</p>')
    with session_factory.begin() as session:
        monitor_statusmatch_watches(session, PageFetcher(responses))
    provider = ProjectProvider([_extraction()])
    result = process_pending_statusmatch_projects(session_factory, provider)
    assert result.succeeded == result.model_calls == 1
    repeated = process_pending_statusmatch_projects(session_factory, provider)
    assert repeated.selected == repeated.model_calls == 0


def test_return_to_previous_content_uses_latest_success_not_any_old_success(session_factory):
    with session_factory.begin() as session:
        _seed_active_watch(session)
    first = process_pending_statusmatch_projects(session_factory, ProjectProvider([_extraction()]))
    responses = _responses()
    responses['https://example.statusmatch.com/faq'] = ACTIVE_FAQ.replace('</body>', '<p>Changed condition.</p></body>')
    with session_factory.begin() as session:
        monitor_statusmatch_watches(session, PageFetcher(responses))
    assert process_pending_statusmatch_projects(session_factory, ProjectProvider([_extraction()])).succeeded == 1
    with session_factory.begin() as session:
        monitor_statusmatch_watches(session, PageFetcher(_responses()))
    returned = process_pending_statusmatch_projects(session_factory, ProjectProvider([_extraction()]))
    assert returned.succeeded == returned.model_calls == 1
    assert returned.projects[0].faq_document_version_id == first.projects[0].faq_document_version_id
    assert process_pending_statusmatch_projects(session_factory, ProjectProvider([])).selected == 0


def test_failed_processing_remains_retryable(session_factory):
    with session_factory.begin() as session:
        _seed_active_watch(session)
    assert process_pending_statusmatch_projects(session_factory, ProjectProvider([])).failed == 1
    result = process_pending_statusmatch_projects(session_factory, ProjectProvider([_extraction()]))
    assert result.succeeded == result.model_calls == 1
    assert process_pending_statusmatch_projects(session_factory, ProjectProvider([])).selected == 0
