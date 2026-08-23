from __future__ import annotations

import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from journeyplus.ai.provider import SequenceAIProvider
from journeyplus.clustering.relationship import (
    SYSTEM_PROMPT as RELATIONSHIP_SYSTEM_PROMPT,
    EventRelationshipAnalyzer,
)
from journeyplus.clustering.retrieval import CandidateRetriever
from journeyplus.contracts import (
    DocumentLabel,
    EventHint,
    RelationshipType,
)
from journeyplus.models import (
    AnalysisRun,
    DocumentVersion,
    EventEvidence,
    EventRevision,
    SourceItem,
    StatusEvent,
)
from journeyplus.sources.registry import seed_sources
from journeyplus.status_topic.analyzer import SYSTEM_PROMPT, StatusRelevanceAnalyzer
from journeyplus.status_topic.pipeline import StatusOpportunityPipeline


def _document(
    db_session,
    *,
    suffix: str,
    body: str,
    duplicate_of=None,
    source_id: str = "ffb_elite_status_feed",
    raw_metadata: dict | None = None,
):
    seed_sources(db_session)
    item = SourceItem(
        source_id=source_id,
        external_id=f"item-{suffix}",
        discovered_url=f"https://example.com/{suffix}",
        canonical_url=f"https://example.com/{suffix}",
        title=f"Item {suffix}",
        observed_at=datetime.now(UTC),
        raw_metadata=raw_metadata or {},
    )
    db_session.add(item)
    db_session.flush()
    document = DocumentVersion(
        source_item_id=item.id,
        canonical_url=item.canonical_url,
        raw_body=body,
        normalized_body=body,
        content_type="text/plain",
        storage_mode="test",
        raw_hash=(suffix[0] * 64)[:64],
        normalized_hash=(suffix[-1] * 64)[:64],
        parser_version="test-v1",
        fetched_at=datetime.now(UTC),
        duplicate_of_id=duplicate_of,
    )
    db_session.add(document)
    db_session.flush()
    return document


def _status_opportunity(
    program="Example Air",
    summary="Match to Gold",
    *,
    application_start: str | None = None,
    application_deadline: str | None = None,
):
    hint = {
        "program": program,
        "summary": summary,
        "target_status": "Gold",
    }
    if application_start is not None:
        hint["application_start"] = application_start
    if application_deadline is not None:
        hint["application_deadline"] = application_deadline
    return {
        "label": "STATUS_OPPORTUNITY",
        "confidence": 0.95,
        "reason": "direct status acquisition path",
        "event_hints": [hint],
    }


def test_first_version_prompt_explicitly_excludes_guide_articles() -> None:
    assert "攻略文档" in SYSTEM_PROMPT
    assert "第一版也标为 NONE" in SYSTEM_PROMPT
    assert "主要报道某个具体会籍活动" in SYSTEM_PROMPT
    assert "精英定级房晚" in SYSTEM_PROMPT
    assert "多个目标等级、价格档、资格映射" in SYSTEM_PROMPT
    assert "authoritative_program" in SYSTEM_PROMPT
    assert "房券、折扣券" in SYSTEM_PROMPT
    assert "Garuda Gold Privilege" in SYSTEM_PROMPT
    assert "Accor Plus 会员只赠餐饮券" in SYSTEM_PROMPT
    assert "缺少时效信息不应单独降为 UNCERTAIN" in SYSTEM_PROMPT
    assert "application_start 和 application_deadline" in SYSTEM_PROMPT
    assert "统一按北京时间规范化" in SYSTEM_PROMPT


def test_prompt_includes_named_travel_platform_tiers_but_not_paid_memberships() -> None:
    assert "旅行预订、旅行顾问或旅行会员平台" in SYSTEM_PROMPT
    assert "直接授予或升级到金卡等明确命名的精英等级" in SYSTEM_PROMPT
    assert "名称中出现会员、会籍、Plus、Pass、Club 或 Card" in SYSTEM_PROMPT
    assert "只是获得会员资格、券、折扣或权益包" in SYSTEM_PROMPT
    assert "个人通过客服邮箱申请成功的单一经历" in SYSTEM_PROMPT
    assert "只能证明个案，不能证明公开或群体公开机会" in SYSTEM_PROMPT


def test_relationship_prompt_does_not_split_on_region_or_entry_alone() -> None:
    assert "不得仅因适用国家、人群、目标档位或注册链接不同就拆分" in (
        RELATIONSHIP_SYSTEM_PROMPT
    )
    assert "申请窗口属于不同期次" in RELATIONSHIP_SYSTEM_PROMPT
    assert "deadline_extension" in RELATIONSHIP_SYSTEM_PROMPT
    assert "非重叠的新一期窗口" in RELATIONSHIP_SYSTEM_PROMPT


def test_none_and_invalid_classification_do_not_create_events(db_session) -> None:
    no_document = _document(db_session, suffix="n", body="Buy points with a bonus")
    no_provider = SequenceAIProvider(
        [
            {
                "label": "NONE",
                "confidence": 1,
                "reason": "no direct status result",
                "event_hints": [],
            }
        ]
    )
    no_result = StatusOpportunityPipeline(db_session, no_provider).process(no_document)
    assert no_result.relevance.result.label == DocumentLabel.NONE
    assert no_result.events == []

    invalid_document = _document(db_session, suffix="i", body="Ambiguous benefit")
    invalid_provider = SequenceAIProvider([ValueError("bad json"), ValueError("bad json")])
    invalid_result = StatusOpportunityPipeline(db_session, invalid_provider).process(
        invalid_document
    )
    assert invalid_result.relevance.result.label == DocumentLabel.UNCERTAIN
    assert invalid_result.relevance.run.status == "FAILED"
    assert invalid_result.events == []


def test_email_only_status_match_anecdote_is_deterministically_none(
    db_session,
) -> None:
    document = _document(
        db_session,
        suffix="email-anecdote",
        body=(
            "According to a data point at https://statusmatcher.com/company/example, "
            "I emailed members@example.com with my status card and my account was "
            "upgraded. More travel notes follow."
        ),
    )
    result = StatusRelevanceAnalyzer(
        db_session,
        SequenceAIProvider([_status_opportunity(program="Example Travel Club")]),
    ).analyze(document)

    assert result.result.label == DocumentLabel.NONE
    assert result.result.event_hints == []
    assert result.run.result == result.result.model_dump(mode="json")


def test_official_group_email_application_is_not_downgraded(db_session) -> None:
    document = _document(
        db_session,
        suffix="official-email-offer",
        body=(
            "All eligible members may apply under the published terms at "
            "https://status.example.org/match by emailing match@example.org."
        ),
    )
    result = StatusRelevanceAnalyzer(
        db_session,
        SequenceAIProvider([_status_opportunity(program="Example Travel Club")]),
    ).analyze(document)

    assert result.result.label == DocumentLabel.STATUS_OPPORTUNITY
    assert len(result.result.event_hints) == 1


def test_one_document_can_create_multiple_minimal_events_and_rerun_is_idempotent(
    db_session,
) -> None:
    document = _document(db_session, suffix="m", body="Two independent matches")
    response = _status_opportunity()
    response["event_hints"].append(
        {
            "program": "Example Hotel",
            "summary": "Fast track to Platinum",
            "target_status": "Platinum",
        }
    )
    provider = SequenceAIProvider([response])
    pipeline = StatusOpportunityPipeline(db_session, provider)
    first = pipeline.process(document)
    second = pipeline.process(document)

    assert len(first.events) == len(second.events) == 2
    assert {item.event.id for item in first.events} == {
        item.event.id for item in second.events
    }
    assert len(provider.calls) == 1
    assert db_session.scalar(select(func.count()).select_from(StatusEvent)) == 2
    assert db_session.scalar(select(func.count()).select_from(EventEvidence)) == 2
    assert db_session.scalar(select(func.count()).select_from(EventRevision)) == 2


def test_content_duplicate_reuses_relevance_analysis_without_model_call(db_session) -> None:
    first = _document(db_session, suffix="a", body="Same normalized content")
    first_provider = SequenceAIProvider([_status_opportunity()])
    first_analysis = StatusRelevanceAnalyzer(db_session, first_provider).analyze(first)
    second = _document(
        db_session,
        suffix="b",
        body="Same normalized content",
        duplicate_of=first.id,
    )
    second_provider = SequenceAIProvider([])
    second_analysis = StatusRelevanceAnalyzer(db_session, second_provider).analyze(second)

    assert first_analysis.result == second_analysis.result
    assert second_analysis.reused
    assert second_provider.calls == []
    assert db_session.scalar(select(func.count()).select_from(AnalysisRun)) == 2


def test_sql_candidate_retrieval_and_relationship_update_are_separate(db_session) -> None:
    existing_document = _document(db_session, suffix="c", body="Initial match")
    existing_event = StatusOpportunityPipeline(
        db_session, SequenceAIProvider([_status_opportunity()])
    ).process(existing_document).events[0].event

    hint = EventHint(
        program="Example Air",
        summary="Deadline extended",
        target_status="Gold",
    )
    candidates = CandidateRetriever(db_session).retrieve(hint)
    assert existing_event.id in {item.id for item in candidates}

    new_document = _document(db_session, suffix="d", body="The deadline was extended")
    provider = SequenceAIProvider(
        [
            {
                "relationship": "UPDATE_OF",
                "confidence": 0.92,
                "reason": "same program and offer, revised deadline",
                "candidate_event_id": str(existing_event.id),
            }
        ]
    )
    relationship = EventRelationshipAnalyzer(db_session, provider).analyze(
        document=new_document,
        hint=hint,
        hint_index=0,
        candidates=candidates,
    )
    assert relationship.result.relationship == RelationshipType.UPDATE_OF
    assert relationship.run is not None
    assert relationship.run.stage == "EVENT_RELATIONSHIP"
    relationship_input = json.loads(provider.calls[0]["user_prompt"])
    assert relationship_input["candidates"][0]["materials"][0]["text"] == (
        "Initial match"
    )


def test_sqlite_candidate_sort_handles_loaded_and_new_event_timestamps(
    db_session,
) -> None:
    first = StatusEvent(
        created_from_key="first",
        program="Example Air",
        target_status="Gold",
        summary="First match",
        search_text="Example Air STATUS_MATCH Gold",
    )
    db_session.add(first)
    db_session.flush()
    first_id = first.id
    db_session.expunge_all()
    assert db_session.get(StatusEvent, first_id).updated_at.tzinfo is None

    second = StatusEvent(
        created_from_key="second",
        program="Example Air",
        target_status="Gold",
        summary="Second match",
        search_text="Example Air STATUS_MATCH Gold",
    )
    db_session.add(second)
    db_session.flush()
    assert second.updated_at.tzinfo is not None

    candidates = CandidateRetriever(db_session).retrieve(
        EventHint(
            program="Example Air",
            summary="Another match",
            target_status="Gold",
        )
    )

    assert {item.id for item in candidates} == {first_id, second.id}


def test_candidate_recall_handles_program_full_names_and_alias_tokens(
    db_session,
) -> None:
    kenya = StatusEvent(
        created_from_key="kenya",
        program="Kenya Airways Asante Rewards",
        target_status="Gold",
        summary="Paid status match",
        search_text="Kenya Airways Asante Rewards paid status match",
    )
    flying_blue = StatusEvent(
        created_from_key="flying-blue",
        program="Air France KLM Flying Blue",
        target_status="Gold",
        summary="Paid status match",
        search_text="Air France KLM Flying Blue paid status match",
    )
    db_session.add_all([kenya, flying_blue])
    db_session.flush()

    kenya_candidates = CandidateRetriever(db_session).retrieve(
        EventHint(
            program="Kenya Airways",
            summary="Paid match to elite status",
            target_status="Gold",
        )
    )
    flying_blue_candidates = CandidateRetriever(db_session).retrieve(
        EventHint(
            program="法航荷航（Flying Blue）",
            summary="付费会籍匹配",
            target_status="Gold",
        )
    )

    assert kenya.id in {item.id for item in kenya_candidates}
    assert flying_blue.id in {item.id for item in flying_blue_candidates}


def test_candidate_recall_uses_action_links_without_persisting_a_new_field(
    db_session,
) -> None:
    existing_document = _document(
        db_session,
        suffix="l",
        body=(
            "马来西亚航空付费匹配："
            "[申请](https://enrich.statusmatch.com/)"
        ),
    )
    event = StatusEvent(
        created_from_key="malaysia-zh",
        program="马来西亚航空",
        target_status="银卡/金卡/白金卡",
        summary="付费会籍匹配",
        search_text="马来西亚航空 付费会籍匹配",
    )
    db_session.add(event)
    db_session.flush()
    db_session.add(
        EventEvidence(
            event_id=event.id,
            document_version_id=existing_document.id,
            hint_index=0,
            source_url=existing_document.canonical_url,
            locator="马来西亚航空付费匹配",
        )
    )
    new_document = _document(
        db_session,
        suffix="o",
        body=(
            "Malaysia Airlines Enrich paid status match "
            "https://enrich.statusmatch.com/?fpr=test"
        ),
    )
    db_session.flush()

    candidates = CandidateRetriever(db_session).retrieve(
        EventHint(
            program="Malaysia Airlines Enrich",
            summary="Paid status match",
            target_status="Silver, Gold or Platinum",
        ),
        document=new_document,
    )

    assert event.id in {item.id for item in candidates}


def test_ffb_authoritative_program_allows_cross_language_project_subdomain(
    db_session,
) -> None:
    existing_document = _document(
        db_session,
        suffix="malaysia-zh",
        body="[马来西亚航空](https://enrich.statusmatch.com/)",
    )
    event = StatusEvent(
        created_from_key="malaysia-cross-language",
        program="马来西亚航空",
        target_status="银卡/金卡/白金卡",
        summary="付费会籍匹配",
        search_text="马来西亚航空 付费会籍匹配",
    )
    db_session.add(event)
    db_session.flush()
    db_session.add(
        EventEvidence(
            event_id=event.id,
            document_version_id=existing_document.id,
            hint_index=0,
            source_url=existing_document.canonical_url,
            locator="马来西亚航空 Enrich付费匹配",
        )
    )
    document = _document(
        db_session,
        suffix="malaysia-ffb",
        body=(
            "Malaysia Airlines Enrich paid status match "
            "https://enrich.statusmatch.com/?fpr=test"
        ),
        source_id="ffb_status_match_catalog",
        raw_metadata={"program": "Malaysia Airlines Enrich"},
    )
    db_session.flush()

    candidates = CandidateRetriever(db_session).retrieve(
        hint := EventHint(
            program="Malaysia Airlines Enrich",
            summary="Paid status match",
            target_status="Silver, Gold or Platinum",
        ),
        document=document,
    )

    assert event.id in {item.id for item in candidates}
    provider = SequenceAIProvider([])
    relationship = EventRelationshipAnalyzer(db_session, provider).analyze(
        document=document,
        hint=hint,
        hint_index=0,
        candidates=candidates,
    )
    assert relationship.result.relationship == RelationshipType.SAME_EVENT
    assert relationship.result.candidate_event_id == event.id
    assert provider.calls == []


def test_same_project_statusmatch_subdomain_is_deterministic_same_event(
    db_session,
) -> None:
    existing_document = _document(
        db_session,
        suffix="flying-blue-generic",
        body=(
            "Air France KLM Flying Blue paid status match "
            "https://flyingblue.statusmatch.com/?fpr=generic"
        ),
    )
    event = StatusEvent(
        created_from_key="flying-blue-generic",
        program="Air France KLM Flying Blue",
        target_status="Silver, Gold or Platinum",
        summary="Paid status match",
        search_text="Air France KLM Flying Blue paid status match",
    )
    db_session.add(event)
    db_session.flush()
    db_session.add(
        EventEvidence(
            event_id=event.id,
            document_version_id=existing_document.id,
            hint_index=0,
            source_url=existing_document.canonical_url,
            locator="Flying Blue paid status match",
        )
    )
    document = _document(
        db_session,
        suffix="flying-blue-ba",
        body=(
            "Air France KLM Flying Blue match for British Airways members "
            "https://flyingblue.statusmatch.com/ba/?fpr=uk"
        ),
    )
    db_session.flush()
    hint = EventHint(
        program="Air France KLM Flying Blue",
        summary="British Airways member paid status match",
        target_status="Silver, Gold or Platinum",
    )
    candidates = CandidateRetriever(db_session).retrieve(hint, document=document)
    provider = SequenceAIProvider([])

    relationship = EventRelationshipAnalyzer(db_session, provider).analyze(
        document=document,
        hint=hint,
        hint_index=0,
        candidates=candidates,
    )

    assert relationship.result.relationship == RelationshipType.SAME_EVENT
    assert relationship.result.candidate_event_id == event.id
    assert relationship.run is None
    assert provider.calls == []


def test_project_subdomain_affinity_does_not_leak_between_document_events(
    db_session,
) -> None:
    mixed_document = _document(
        db_session,
        suffix="malaysia-garuda-mixed",
        body=(
            "Malaysia Airlines Enrich https://enrich.statusmatch.com/ and "
            "Garuda Gold Privilege https://www.garuda-indonesia.com/goldprivilege"
        ),
    )
    enrich = StatusEvent(
        created_from_key="enrich-mixed",
        program="马来西亚航空 Enrich",
        target_status="银卡/金卡/白金卡",
        summary="付费会籍匹配",
        search_text="马来西亚航空 Enrich 付费会籍匹配",
    )
    garuda = StatusEvent(
        created_from_key="garuda-mixed",
        program="Garuda Indonesia GarudaMiles Gold Privilege",
        target_status="Gold",
        summary="付费金卡",
        search_text="Garuda Indonesia GarudaMiles Gold Privilege",
    )
    db_session.add_all([enrich, garuda])
    db_session.flush()
    db_session.add_all(
        [
            EventEvidence(
                event_id=enrich.id,
                document_version_id=mixed_document.id,
                hint_index=0,
                source_url=mixed_document.canonical_url,
                locator="Malaysia Airlines Enrich",
            ),
            EventEvidence(
                event_id=garuda.id,
                document_version_id=mixed_document.id,
                hint_index=1,
                source_url=mixed_document.canonical_url,
                locator="Garuda Gold Privilege",
            ),
        ]
    )
    document = _document(
        db_session,
        suffix="enrich-ffb",
        body=(
            "Malaysia Airlines Enrich paid status match "
            "https://enrich.statusmatch.com/?fpr=catalog"
        ),
        source_id="ffb_status_match_catalog",
        raw_metadata={"program": "Malaysia Airlines Enrich"},
    )
    db_session.flush()

    candidates = CandidateRetriever(db_session).retrieve(
        EventHint(
            program="Malaysia Airlines Enrich",
            summary="Paid status match",
            target_status="Silver, Gold or Platinum",
        ),
        document=document,
    )

    assert enrich.id in {item.id for item in candidates}
    assert garuda.id not in {item.id for item in candidates}

    provider = SequenceAIProvider(
        [
            {
                "relationship": "DIFFERENT_EVENT",
                "confidence": 0.99,
                "reason": "Garuda Gold Privilege is a separate program and mechanism",
                "candidate_event_id": None,
            }
        ]
    )
    relationship = EventRelationshipAnalyzer(db_session, provider).analyze(
        document=mixed_document,
        hint=EventHint(
            program="Garuda Indonesia GarudaMiles Gold Privilege",
            summary="Paid Gold membership",
            target_status="Gold",
        ),
        hint_index=1,
        candidates=[enrich],
    )
    assert relationship.result.relationship == RelationshipType.DIFFERENT_EVENT
    assert len(provider.calls) == 1


def test_ffb_catalog_program_overrides_conflicting_body_brand(db_session) -> None:
    document = _document(
        db_session,
        suffix="k",
        body=(
            "KM Malta Airlines KM Rewards\n\n"
            "KM Rewards paid status match; copied sentence says Kenya Airways."
        ),
        source_id="ffb_status_match_catalog",
        raw_metadata={"program": "KM Malta Airlines KM Rewards"},
    )
    result = StatusRelevanceAnalyzer(
        db_session,
        SequenceAIProvider([_status_opportunity(program="Kenya Airways")]),
    ).analyze(document)

    assert result.result.event_hints[0].program == "KM Malta Airlines KM Rewards"


def test_ffb_catalog_authoritative_program_rejects_conflicting_candidates(
    db_session,
) -> None:
    kenya_document = _document(
        db_session,
        suffix="kenya-conflict",
        body=(
            "Kenya Airways Asante Rewards paid status match "
            "https://kenya-airways.statusmatch.com/?fpr=kenya"
        ),
    )
    kenya = StatusEvent(
        created_from_key="kenya-conflict",
        program="Kenya Airways Asante Rewards",
        target_status="Silver, Gold or Platinum",
        summary="Paid status match",
        search_text="Kenya Airways Asante Rewards paid status match",
    )
    db_session.add(kenya)
    db_session.flush()
    db_session.add(
        EventEvidence(
            event_id=kenya.id,
            document_version_id=kenya_document.id,
            hint_index=0,
            source_url=kenya_document.canonical_url,
            locator="Kenya Airways paid status match",
        )
    )
    document = _document(
        db_session,
        suffix="q",
        body=(
            "KM Malta Airlines KM Rewards\n\n"
            "KM Rewards paid status match at https://kmrewards.statusmatch.com/; "
            "copied sentence says Kenya Airways."
        ),
        source_id="ffb_status_match_catalog",
        raw_metadata={"program": "KM Malta Airlines KM Rewards"},
    )

    candidates = CandidateRetriever(db_session).retrieve(
        EventHint(
            program="KM Malta Airlines KM Rewards",
            summary=(
                "Copied details claim Kenya Airways Asante Rewards Silver, Gold "
                "or Platinum"
            ),
            target_status="Silver, Gold or Platinum",
        ),
        document=document,
    )

    assert kenya.id not in {item.id for item in candidates}


def test_relationship_aggregation_handles_update_and_uncertain_without_duplicates(
    db_session,
) -> None:
    original_document = _document(db_session, suffix="f", body="Initial direct match")
    original_event = StatusOpportunityPipeline(
        db_session, SequenceAIProvider([_status_opportunity()])
    ).process(original_document).events[0].event

    update_document = _document(db_session, suffix="g", body="Match deadline extended")
    update_provider = SequenceAIProvider(
        [
            _status_opportunity(summary="Match deadline extended"),
            {
                "relationship": "UPDATE_OF",
                "confidence": 0.95,
                "reason": "same offer with a revised deadline",
                "candidate_event_id": str(original_event.id),
            },
        ]
    )
    update_pipeline = StatusOpportunityPipeline(db_session, update_provider)
    updated = update_pipeline.process(update_document)
    rerun = update_pipeline.process(update_document)
    assert updated.events[0].event.id == rerun.events[0].event.id == original_event.id
    assert "Match deadline extended" in original_event.search_text
    assert db_session.scalar(
        select(func.count()).select_from(EventRevision).where(
            EventRevision.event_id == original_event.id,
            EventRevision.relationship == "UPDATE_OF",
        )
    ) == 1

    uncertain_document = _document(db_session, suffix="h", body="Possibly a new match")
    uncertain_provider = SequenceAIProvider(
        [
            _status_opportunity(summary="Possibly a separate match"),
            {
                "relationship": "UNCERTAIN",
                "confidence": 0.4,
                "reason": "not enough terms to merge safely",
                "candidate_event_id": str(original_event.id),
            },
        ]
    )
    uncertain = StatusOpportunityPipeline(db_session, uncertain_provider).process(
        uncertain_document
    )
    assert uncertain.events[0].event.id != original_event.id
    assert uncertain.events[0].event.status == "NEEDS_REVIEW"
    assert uncertain.events[0].needs_review


def test_missing_window_can_still_join_same_event_and_refresh_current_summary(
    db_session,
) -> None:
    original = _document(db_session, suffix="window-original", body="Original terms")
    event = StatusOpportunityPipeline(
        db_session,
        SequenceAIProvider(
            [
                _status_opportunity(
                    summary="Original short summary",
                    application_deadline="2026-12-31",
                )
            ]
        ),
    ).process(original).events[0].event
    follow_up = _document(
        db_session,
        suffix="window-undated",
        body="A fuller report of the same status match without a date",
    )
    provider = SequenceAIProvider(
        [
            _status_opportunity(
                summary="Fuller current summary without a repeated date"
            ),
            {
                "relationship": "SAME_EVENT",
                "confidence": 0.94,
                "reason": "same rules and program; the follow-up omits the date",
                "candidate_event_id": str(event.id),
            },
        ]
    )

    result = StatusOpportunityPipeline(db_session, provider).process(follow_up)

    assert result.events[0].event.id == event.id
    assert event.summary == "Fuller current summary without a repeated date"
    assert "Original short summary" in event.search_text
    assert "Fuller current summary" in event.search_text


def test_non_overlapping_new_period_is_split_even_if_model_requests_same_event(
    db_session,
) -> None:
    beijing = ZoneInfo("Asia/Shanghai")
    event = StatusEvent(
        created_from_key="old-period",
        program="Example Air",
        target_status="Gold",
        summary="2026 status match",
        search_text="Example Air 2026 status match",
        application_start_at=datetime(2026, 1, 1, tzinfo=beijing),
        application_deadline_at=datetime(2026, 2, 28, 23, 59, 59, tzinfo=beijing),
        lifecycle_status="EXPIRED",
    )
    db_session.add(event)
    db_session.flush()
    document = _document(
        db_session,
        suffix="new-period",
        body="The independently reopened 2027 status match",
    )
    provider = SequenceAIProvider(
        [
            _status_opportunity(
                summary="2027 status match",
                application_start="2027-01-01",
                application_deadline="2027-02-28",
            ),
            {
                "relationship": "SAME_EVENT",
                "confidence": 0.8,
                "reason": "same brand",
                "candidate_event_id": str(event.id),
            },
        ]
    )

    result = StatusOpportunityPipeline(db_session, provider).process(document)

    assert result.events[0].event.id != event.id
    revision = db_session.scalar(
        select(EventRevision).where(
            EventRevision.event_id == result.events[0].event.id
        )
    )
    assert revision is not None and revision.relationship == "DIFFERENT_EVENT"
    assert event.application_deadline_at is not None


def test_explicit_new_year_wording_bypasses_project_subdomain_auto_merge(
    db_session,
) -> None:
    beijing = ZoneInfo("Asia/Shanghai")
    existing_document = _document(
        db_session,
        suffix="gha-2025",
        body=(
            "GHA DISCOVERY status match 2025 "
            "https://gha.statusmatch.com/"
        ),
    )
    event = StatusEvent(
        created_from_key="gha-2025",
        program="GHA DISCOVERY",
        target_status="Platinum",
        summary="2025 status match",
        search_text="GHA DISCOVERY 2025 status match Platinum",
        application_deadline_at=datetime(
            2025, 11, 30, 23, 59, 59, tzinfo=beijing
        ),
        lifecycle_status="EXPIRED",
    )
    db_session.add(event)
    db_session.flush()
    db_session.add(
        EventEvidence(
            event_id=event.id,
            document_version_id=existing_document.id,
            hint_index=0,
            source_url=existing_document.canonical_url,
            locator="GHA DISCOVERY status match 2025",
        )
    )
    document = _document(
        db_session,
        suffix="gha-2026",
        body=(
            "The GHA DISCOVERY Status Match has returned for the first time in "
            "2026. Apply by April 6, 2026 at https://gha.statusmatch.com/."
        ),
    )
    hint = EventHint(
        program="GHA DISCOVERY",
        summary="2026 status match",
        target_status="Platinum",
        application_deadline="April 6, 2026",
    )
    provider = SequenceAIProvider(
        [
            {
                "relationship": "DIFFERENT_EVENT",
                "confidence": 0.99,
                "reason": "the article explicitly identifies a new 2026 period",
                "candidate_event_id": None,
            }
        ]
    )

    relationship = EventRelationshipAnalyzer(db_session, provider).analyze(
        document=document,
        hint=hint,
        hint_index=0,
        candidates=[event],
    )

    assert relationship.result.relationship == RelationshipType.DIFFERENT_EVENT
    assert relationship.run is not None
    assert len(provider.calls) == 1


def test_explicit_later_deadline_keeps_update_and_structured_extension_signal(
    db_session,
) -> None:
    beijing = ZoneInfo("Asia/Shanghai")
    event = StatusEvent(
        created_from_key="extension-period",
        program="Example Air",
        target_status="Gold",
        summary="Match through September",
        search_text="Example Air match September",
        application_start_at=datetime(2026, 8, 1, tzinfo=beijing),
        application_deadline_at=datetime(2026, 9, 30, 23, 59, 59, tzinfo=beijing),
    )
    db_session.add(event)
    db_session.flush()
    document = _document(
        db_session,
        suffix="deadline-extension",
        body="The same offer is explicitly extended through October 31.",
    )
    provider = SequenceAIProvider(
        [
            _status_opportunity(
                summary="Deadline extended through October",
                application_deadline="2026-10-31",
            ),
            {
                "relationship": "UPDATE_OF",
                "confidence": 0.99,
                "reason": "the source explicitly extends the same deadline",
                "candidate_event_id": str(event.id),
                "deadline_extension": True,
            },
        ]
    )

    result = StatusOpportunityPipeline(db_session, provider).process(document)

    assert result.events[0].event.id == event.id
    assert event.summary == "Deadline extended through October"
    revision = db_session.scalar(
        select(EventRevision).where(
            EventRevision.event_id == event.id,
            EventRevision.document_version_id == document.id,
        )
    )
    assert revision is not None
    assert revision.snapshot["relationship"]["deadline_extension"] is True
    relationship_payload = json.loads(provider.calls[1]["user_prompt"])
    assert relationship_payload["candidates"][0][
        "application_deadline_at"
    ].endswith("+08:00")


def test_two_digit_year_deadline_extension_is_accepted(db_session) -> None:
    beijing = ZoneInfo("Asia/Shanghai")
    event = StatusEvent(
        created_from_key="real-short-date-extension",
        program="United MileagePlus",
        target_status="Premier",
        summary="Register by June 30",
        search_text="United MileagePlus status match",
        application_deadline_at=datetime(
            2025, 6, 30, 23, 59, 59, 999999, tzinfo=beijing
        ),
    )
    db_session.add(event)
    db_session.flush()
    document = _document(
        db_session,
        suffix="united-extension-short-date",
        body="OFFER EXTENDED: Register by Dec 31, 25.",
    )
    hint = EventHint(
        program="United MileagePlus",
        summary="Registration deadline extended",
        target_status="Premier",
        application_deadline="Dec 31, 25",
    )
    provider = SequenceAIProvider(
        [
            {
                "relationship": "UPDATE_OF",
                "confidence": 0.99,
                "reason": "same offer with an explicitly extended deadline",
                "candidate_event_id": str(event.id),
                "deadline_extension": True,
            }
        ]
    )

    relationship = EventRelationshipAnalyzer(db_session, provider).analyze(
        document=document,
        hint=hint,
        hint_index=0,
        candidates=[event],
    )

    assert relationship.result.relationship == RelationshipType.UPDATE_OF
    assert relationship.result.deadline_extension is True
    assert relationship.run is not None and relationship.run.status == "SUCCEEDED"


def test_same_brand_overlapping_different_mechanism_remains_separate(
    db_session,
) -> None:
    beijing = ZoneInfo("Asia/Shanghai")
    event = StatusEvent(
        created_from_key="corporate-match",
        program="Example Hotel",
        target_status="Gold",
        summary="Corporate status match",
        search_text="Example Hotel corporate status match",
        application_start_at=datetime(2026, 9, 1, tzinfo=beijing),
        application_deadline_at=datetime(2026, 12, 31, 23, 59, 59, tzinfo=beijing),
    )
    db_session.add(event)
    db_session.flush()
    document = _document(
        db_session,
        suffix="public-fast-track",
        body="A public stay-based fast track during the same dates",
    )
    provider = SequenceAIProvider(
        [
            _status_opportunity(
                program="Example Hotel",
                summary="Public stay-based fast track",
                application_start="2026-10-01",
                application_deadline="2026-11-30",
            ),
            {
                "relationship": "DIFFERENT_EVENT",
                "confidence": 0.98,
                "reason": "overlapping dates but a distinct audience and mechanism",
                "candidate_event_id": None,
            },
        ]
    )

    result = StatusOpportunityPipeline(db_session, provider).process(document)

    assert result.events[0].event.id != event.id


def test_relevance_can_rerun_with_new_prompt_without_relationship_contract(db_session) -> None:
    document = _document(db_session, suffix="e", body="Direct match")
    provider = SequenceAIProvider(
        [_status_opportunity(), _status_opportunity()]
    )
    first = StatusRelevanceAnalyzer(
        db_session, provider, prompt_version="status-v1"
    ).analyze(document)
    second = StatusRelevanceAnalyzer(
        db_session, provider, prompt_version="status-v2"
    ).analyze(document)
    assert first.run.id != second.run.id
    assert first.run.stage == second.run.stage == "STATUS_RELEVANCE"
