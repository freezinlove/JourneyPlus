from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from journeyplus.ai.provider import AIProviderMetadata, SequenceAIProvider
from journeyplus.automation.service import run_daily_cycle
from journeyplus.contracts import Brief, DiscoveredItem, RawDocument
from journeyplus.facts.service import FactConsolidator
from journeyplus.models import (
    BriefRecord,
    DocumentVersion,
    EventEvidence,
    FactSetRecord,
    SourceAutomationState,
    SourceItem,
    StatusEvent,
    StatusMatchWatch,
    StatusMatchWatchPage,
)
from journeyplus.sources.base import FetchResponse
from journeyplus.sources.collection import collect_manual
from journeyplus.sources.gmail import (
    GmailHistoryCursorExpired,
    GmailStatusServicesAdapter,
    RECIPIENT_ALIAS,
)
from journeyplus.sources.registry import seed_sources
from journeyplus.statusmatch.service import monitor_statusmatch_watches
from journeyplus.statusmatch.contracts import StatusMatchProjectExtraction
from journeyplus.statusmatch.watchlist import (
    delete_watch_only,
    ensure_statusmatch_watch,
)


ACTIVE_ACTIVITY = """
<html><body><h1>Apply for a Status Match today</h1>
<form><input type="text" name="member"><button>Continue</button></form>
</body></html>
"""
ACTIVE_FAQ = "<html><body><h1>Frequently Asked Questions</h1><p>The match is open.</p></body></html>"


class PageFetcher:
    def __init__(self, responses):
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str) -> FetchResponse:
        self.calls.append(url)
        configured = self.responses[url]
        if isinstance(configured, Exception):
            raise configured
        if isinstance(configured, tuple):
            body, final_url = configured
        else:
            body, final_url = configured, url
        return FetchResponse(body=body, content_type="text/html", final_url=final_url)


class DailyWorkflowProvider:
    metadata = AIProviderMetadata(
        provider="test",
        model="daily-statusmatch",
        region="local",
        config_version="daily-statusmatch-v1",
    )

    def generate_structured(
        self, *, system_prompt: str, user_prompt: str, output_model
    ):
        request = json.loads(user_prompt)
        if output_model is StatusMatchProjectExtraction:
            host = request["project_host"]
            return output_model.model_validate(
                {
                    "identity": {
                        "program": "Example Club",
                        "summary": "Example Club status match",
                    },
                    "what_happened": {
                        "value": "Example Club is accepting status-match applications",
                        "evidence": [
                            {"source": "HOME", "locator": "application heading"}
                        ],
                    },
                    "action_link": {
                        "value": f"https://{host}/",
                        "evidence": [
                            {"source": "HOME", "locator": "application form"}
                        ],
                    },
                }
            )
        if output_model is Brief:
            return output_model.model_validate(
                {
                    "fact_set_id": request["fact_set_id"],
                    "title": "Example Club 开放会籍匹配",
                    "title_fact_keys": ["what_happened"],
                    "summary": "Example Club 正在接受会籍匹配申请。",
                    "summary_fact_keys": ["what_happened"],
                    "key_points": [],
                    "caveats": [],
                    "source_links": request["allowed_source_links"],
                }
            )
        return output_model.model_validate(
            {
                "label": "NONE",
                "confidence": 1,
                "reason": "ordinary non-status article",
                "event_hints": [],
            }
        )


def _seed_watch(db_session, host="example.statusmatch.com"):
    seed_sources(db_session)
    return ensure_statusmatch_watch(db_session, host)


def _active_responses(host="example.statusmatch.com"):
    return {
        f"https://{host}/": ACTIVE_ACTIVITY,
        f"https://{host}/faq": ACTIVE_FAQ,
    }


def test_monitor_persists_only_changed_page_versions(db_session) -> None:
    watch = _seed_watch(db_session)
    fetcher = PageFetcher(_active_responses())

    first = monitor_statusmatch_watches(db_session, fetcher)
    unchanged = monitor_statusmatch_watches(db_session, fetcher)
    fetcher.responses["https://example.statusmatch.com/faq"] = (
        "<html><body><h1>FAQ</h1><p>Updated eligibility.</p></body></html>"
    )
    changed = monitor_statusmatch_watches(db_session, fetcher)

    assert first.pages_changed == 2
    assert unchanged.pages_changed == 0
    assert changed.pages_changed == 1
    assert db_session.scalar(select(func.count()).select_from(DocumentVersion)) == 3
    db_session.refresh(watch)
    assert watch.status == "ACTIVE"
    pages = list(
        db_session.scalars(
            select(StatusMatchWatchPage).where(
                StatusMatchWatchPage.watch_id == watch.id
            )
        )
    )
    assert len(pages) == 2
    assert all(page.last_checked_at is not None for page in pages)


def test_monitor_fetch_failure_keeps_watch_and_never_closes(db_session) -> None:
    watch = _seed_watch(db_session)
    responses = _active_responses()
    responses["https://example.statusmatch.com/"] = RuntimeError("HTTP 503")

    result = monitor_statusmatch_watches(db_session, PageFetcher(responses))

    assert result.projects_archived == 0
    assert len(result.errors) == 1
    assert db_session.get(StatusMatchWatch, watch.id) is not None
    page = db_session.scalar(
        select(StatusMatchWatchPage).where(
            StatusMatchWatchPage.watch_id == watch.id,
            StatusMatchWatchPage.page_kind == "activity",
        )
    )
    assert page is not None and "HTTP 503" in (page.last_error or "")
    db_session.refresh(watch)
    assert "HTTP 503" in (watch.last_error or "")


@pytest.mark.parametrize(
    "invalid_activity",
    [
        (ACTIVE_ACTIVITY, "https://example.com/closed"),
        "<html><head><title>Just a moment...</title></head><body>Checking your browser</body></html>",
    ],
)
def test_cross_host_redirect_or_challenge_never_archives(
    db_session,
    invalid_activity,
) -> None:
    watch = _seed_watch(db_session)
    responses = _active_responses()
    responses["https://example.statusmatch.com/"] = invalid_activity

    result = monitor_statusmatch_watches(db_session, PageFetcher(responses))

    assert result.projects_archived == 0
    assert len(result.errors) == 1
    assert db_session.get(StatusMatchWatch, watch.id) is not None


def test_waitlist_closes_watch_but_preserves_documents(db_session) -> None:
    _seed_watch(db_session)
    fetcher = PageFetcher(
        {
            "https://example.statusmatch.com/": (
                """
                <html><body><h1>Waitlist for future opportunities</h1>
                <p>Register your interest in a future Status Match opportunity.</p>
                <form><input type="email"><button>Register for Waitlist</button></form>
                </body></html>
                """,
                "https://example.statusmatch.com/waitlist.php",
            ),
            "https://example.statusmatch.com/faq": (
                "<html><body>This offer has expired and is no longer available.</body></html>"
            ),
        }
    )

    result = monitor_statusmatch_watches(db_session, fetcher)

    assert result.projects_archived == 1
    assert db_session.scalar(select(func.count()).select_from(StatusMatchWatch)) == 0
    assert db_session.scalar(select(func.count()).select_from(DocumentVersion)) == 2
    items = list(db_session.scalars(select(SourceItem)))
    assert len(items) == 2
    assert all(item.raw_metadata["skip_semantic_processing"] for item in items)


def test_partial_ended_faq_does_not_close_active_project(db_session) -> None:
    for index, faq in enumerate(
        (
            (
                "The Australia Complimentary Gold Status Match offer has ended. "
                "However, you may apply for a Gold Status Match for a fee."
            ),
            "Royal Club Gold Status is no longer available for any hotel match applicants.",
            "Please await confirmation before continuing your application.",
        )
    ):
        host = f"boundary-{index}.statusmatch.com"
        ensure_statusmatch_watch(db_session, host)
        result = monitor_statusmatch_watches(
            db_session,
            PageFetcher(
                {
                    f"https://{host}/": ACTIVE_ACTIVITY,
                    f"https://{host}/faq": f"<html><body>{faq}</body></html>",
                }
            ),
        )
        assert result.projects_archived == 0
        assert db_session.scalar(
            select(StatusMatchWatch).where(StatusMatchWatch.host == host)
        ) is not None


def test_closure_archives_event_and_preserves_semantic_history(db_session) -> None:
    watch = _seed_watch(db_session)
    monitor_statusmatch_watches(db_session, PageFetcher(_active_responses()))
    pages = list(
        db_session.scalars(
            select(StatusMatchWatchPage).where(
                StatusMatchWatchPage.watch_id == watch.id
            )
        )
    )
    event = StatusEvent(
        created_from_key="statusmatch-history-event",
        program="Example Air",
        target_status="Gold",
        summary="Example match",
        search_text="Example Air Gold match",
    )
    db_session.add(event)
    db_session.flush()
    watch.current_event_id = event.id
    for index, page in enumerate(pages):
        db_session.add(
            EventEvidence(
                event_id=event.id,
                document_version_id=page.current_document_version_id,
                hint_index=index,
                source_url=page.canonical_url,
                locator="current project page",
            )
        )
    fact = FactSetRecord(
        event_id=event.id,
        version=1,
        schema_version="4",
        facts={"historical": True},
        has_conflicts=False,
    )
    db_session.add(fact)
    db_session.flush()
    brief = BriefRecord(
        fact_set_id=fact.id,
        version=1,
        schema_version="1",
        content={"historical": True},
    )
    db_session.add(brief)
    db_session.flush()
    event.current_fact_set_id = fact.id
    event.current_brief_id = brief.id

    closed = {
        "https://example.statusmatch.com/": (
            "<html><body><h1>Awaiting new offers</h1></body></html>"
        ),
        "https://example.statusmatch.com/faq": (
            "<html><body>This offer has expired and is no longer available.</body></html>"
        ),
    }
    result = monitor_statusmatch_watches(db_session, PageFetcher(closed))

    db_session.refresh(event)
    assert result.projects_archived == 1
    assert event.archived_at is not None
    assert event.archive_reason == "STATUSMATCH_AWAITING_FUTURE_OFFER"
    assert event.closure_document_version_id is not None
    assert db_session.get(FactSetRecord, fact.id) is not None
    assert db_session.get(BriefRecord, brief.id) is not None
    assert db_session.scalar(select(func.count()).select_from(EventEvidence)) == 2
    assert db_session.scalar(select(func.count()).select_from(DocumentVersion)) == 4


class CountingGmailClient:
    def __init__(self):
        self.message_ids = ["message-1"]
        self.get_calls: list[str] = []

    def list_labels(self):
        return [{"id": "Label_123", "name": "statusmatch"}]

    def list_messages(self, *, label_id: str, query: str):
        return [{"id": value} for value in self.message_ids]

    def get_message(self, message_id: str):
        self.get_calls.append(message_id)
        html = base64.urlsafe_b64encode(
            (
                '<html><body><a href="https://example.statusmatch.com/">'
                "Apply</a></body></html>"
            ).encode()
        ).decode().rstrip("=")
        return {
            "id": message_id,
            "threadId": f"thread-{message_id}",
            "labelIds": ["Label_123"],
            "payload": {
                "mimeType": "text/html",
                "headers": [
                    {"name": "To", "value": RECIPIENT_ALIAS},
                    {"name": "From", "value": "StatusMatch <news@example.net>"},
                    {"name": "Subject", "value": "Status match"},
                    {"name": "Message-ID", "value": f"<{message_id}@example.net>"},
                ],
                "body": {"data": html},
            },
        }


class HistoryGmailClient(CountingGmailClient):
    def __init__(self):
        super().__init__()
        self.profile_history_id = "100"
        self.history: dict[str, tuple[list[str], str] | Exception] = {}
        self.list_calls = 0
        self.history_calls: list[tuple[str, str]] = []

    def list_messages(self, *, label_id: str, query: str):
        self.list_calls += 1
        return super().list_messages(label_id=label_id, query=query)

    def get_profile_history_id(self) -> str:
        return self.profile_history_id

    def list_history_messages(self, *, start_history_id: str, label_id: str):
        self.history_calls.append((start_history_id, label_id))
        configured = self.history[start_history_id]
        if isinstance(configured, Exception):
            raise configured
        message_ids, next_history_id = configured
        return [{"id": value} for value in message_ids], next_history_id


def test_gmail_reads_only_unseen_messages_and_ignores_watched_hosts(db_session) -> None:
    seed_sources(db_session)
    gmail = CountingGmailClient()
    page_fetcher = PageFetcher(_active_responses())
    adapter = GmailStatusServicesAdapter(gmail, project_fetcher=page_fetcher)

    first = collect_manual(db_session, adapter, idempotency_key="gmail:first")
    second = collect_manual(db_session, adapter, idempotency_key="gmail:second")
    gmail.message_ids.append("message-2")
    third = collect_manual(db_session, adapter, idempotency_key="gmail:third")

    assert first.new_versions == 3
    assert second.discovered == 0
    assert third.new_versions == 1
    assert gmail.get_calls == ["message-1", "message-2"]
    assert page_fetcher.calls == [
        "https://example.statusmatch.com/",
        "https://example.statusmatch.com/faq",
    ]


def test_gmail_uses_history_cursor_after_initial_full_reconciliation(
    db_session,
) -> None:
    seed_sources(db_session)
    gmail = HistoryGmailClient()
    page_fetcher = PageFetcher(_active_responses())
    adapter = GmailStatusServicesAdapter(gmail, project_fetcher=page_fetcher)

    first = collect_manual(db_session, adapter, idempotency_key="gmail:history:first")
    state = db_session.get(SourceAutomationState, "status_services_mail")

    assert first.new_versions == 3
    assert state is not None
    assert state.discovery_cursor == "100"
    assert gmail.list_calls == 1
    assert gmail.history_calls == []

    gmail.message_ids.append("message-2")
    gmail.history["100"] = (["message-2"], "110")
    second = collect_manual(
        db_session, adapter, idempotency_key="gmail:history:second"
    )

    assert second.discovered == 1
    assert second.new_versions == 1
    assert state.discovery_cursor == "110"
    assert gmail.list_calls == 1
    assert gmail.history_calls == [("100", "Label_123")]
    assert gmail.get_calls == ["message-1", "message-2"]


def test_gmail_expired_history_cursor_falls_back_to_full_id_reconciliation(
    db_session,
) -> None:
    seed_sources(db_session)
    gmail = HistoryGmailClient()
    gmail.profile_history_id = "210"
    gmail.history["stale"] = GmailHistoryCursorExpired("stale")
    state = SourceAutomationState(
        source_id="status_services_mail", discovery_cursor="stale"
    )
    db_session.add(state)
    db_session.flush()

    summary = collect_manual(
        db_session,
        GmailStatusServicesAdapter(
            gmail, project_fetcher=PageFetcher(_active_responses())
        ),
        idempotency_key="gmail:history:fallback",
    )

    assert summary.new_versions == 3
    assert gmail.history_calls == [("stale", "Label_123")]
    assert gmail.list_calls == 1
    assert state.discovery_cursor == "210"


def test_gmail_does_not_advance_history_cursor_when_discovery_fails(
    db_session,
    monkeypatch,
) -> None:
    seed_sources(db_session)
    gmail = HistoryGmailClient()
    gmail.history["100"] = (["broken-message"], "110")
    state = SourceAutomationState(
        source_id="status_services_mail", discovery_cursor="100"
    )
    db_session.add(state)
    db_session.flush()

    def fail_message_fetch(_message_id: str):
        raise RuntimeError("temporary Gmail read failure")

    monkeypatch.setattr(gmail, "get_message", fail_message_fetch)

    with pytest.raises(RuntimeError, match="temporary Gmail read failure"):
        collect_manual(
            db_session,
            GmailStatusServicesAdapter(
                gmail, project_fetcher=PageFetcher(_active_responses())
            ),
            idempotency_key="gmail:history:failed",
        )

    assert state.discovery_cursor == "100"


def test_removed_watch_requires_a_genuinely_new_message_to_reonboard(db_session) -> None:
    seed_sources(db_session)
    gmail = CountingGmailClient()
    page_fetcher = PageFetcher(_active_responses())
    adapter = GmailStatusServicesAdapter(gmail, project_fetcher=page_fetcher)
    collect_manual(db_session, adapter, idempotency_key="gmail:initial")
    watch = db_session.scalar(select(StatusMatchWatch))
    assert watch is not None
    delete_watch_only(db_session, watch)

    old_only = collect_manual(db_session, adapter, idempotency_key="gmail:old-only")
    assert old_only.discovered == 0
    assert db_session.scalar(select(func.count()).select_from(StatusMatchWatch)) == 0

    gmail.message_ids.append("message-2")
    reonboarded = collect_manual(db_session, adapter, idempotency_key="gmail:new")

    assert reonboarded.discovered == 3
    assert gmail.get_calls == ["message-1", "message-2"]
    assert page_fetcher.calls == [
        "https://example.statusmatch.com/",
        "https://example.statusmatch.com/faq",
        "https://example.statusmatch.com/",
        "https://example.statusmatch.com/faq",
    ]
    assert db_session.scalar(select(func.count()).select_from(StatusMatchWatch)) == 1


def test_mail_parser_upgrade_replays_local_snapshot_without_gmail_download(
    db_session,
) -> None:
    seed_sources(db_session)
    gmail = CountingGmailClient()
    adapter = GmailStatusServicesAdapter(
        gmail, project_fetcher=PageFetcher(_active_responses())
    )
    collect_manual(db_session, adapter, idempotency_key="gmail:parser:first")
    mail_item = db_session.scalar(
        select(SourceItem).where(SourceItem.external_id == "message-1")
    )
    assert mail_item is not None
    current_mail = db_session.scalar(
        select(DocumentVersion)
        .where(DocumentVersion.source_item_id == mail_item.id)
        .order_by(DocumentVersion.created_at.desc())
        .limit(1)
    )
    assert current_mail is not None
    current_mail.parser_version = "outdated-parser"
    db_session.flush()

    replay = collect_manual(
        db_session, adapter, idempotency_key="gmail:parser:second"
    )

    assert replay.discovered == 0
    assert replay.new_versions == 1
    assert gmail.get_calls == ["message-1"]
    assert db_session.scalar(
        select(func.count()).select_from(DocumentVersion).where(
            DocumentVersion.source_item_id == mail_item.id
        )
    ) == 2


def _evidence(document: DocumentVersion, locator: str):
    return {
        "document_version_id": str(document.id),
        "source_url": document.canonical_url,
        "locator": locator,
    }


def _snapshot_fact(event: StatusEvent, document: DocumentVersion, deadline: str):
    evidence = [_evidence(document, f"deadline {deadline}")]
    return {
        "schema_version": "4",
        "event_id": str(event.id),
        "what_happened": {"value": "Example status match", "evidence": evidence},
        "target_status": {"value": "Gold", "evidence": evidence},
        "deadline": {"value": deadline, "evidence": evidence},
    }


def _snapshot_event(db_session):
    watch = _seed_watch(db_session)
    monitor_statusmatch_watches(db_session, PageFetcher(_active_responses()))
    event = StatusEvent(
        created_from_key=f"snapshot-{uuid4()}",
        program="Example Air",
        target_status="Gold",
        summary="Example status match",
        search_text="Example Air status match Gold",
    )
    db_session.add(event)
    db_session.flush()
    watch.current_event_id = event.id
    pages = {
        page.page_kind: page
        for page in db_session.scalars(
            select(StatusMatchWatchPage).where(
                StatusMatchWatchPage.watch_id == watch.id
            )
        )
    }
    for index, page in enumerate(pages.values()):
        db_session.add(
            EventEvidence(
                event_id=event.id,
                document_version_id=page.current_document_version_id,
                hint_index=index,
                source_url=page.canonical_url,
                locator="current page",
            )
        )
    db_session.flush()
    return event, watch, pages


def test_snapshot_fact_rebuild_replaces_obsolete_value(db_session) -> None:
    event, watch, pages = _snapshot_event(db_session)
    old_document = db_session.get(
        DocumentVersion, pages["faq"].current_document_version_id
    )
    assert old_document is not None
    current = FactSetRecord(
        event_id=event.id,
        version=1,
        schema_version="4",
        facts=_snapshot_fact(event, old_document, "2026-08-31"),
        has_conflicts=False,
    )
    db_session.add(current)
    db_session.flush()
    event.current_fact_set_id = current.id

    changed_fetcher = PageFetcher(_active_responses())
    changed_fetcher.responses["https://example.statusmatch.com/faq"] = (
        "<html><body>Applications close 2026-09-30.</body></html>"
    )
    monitor_statusmatch_watches(db_session, changed_fetcher)
    db_session.refresh(pages["faq"])
    new_document = db_session.get(
        DocumentVersion, pages["faq"].current_document_version_id
    )
    assert new_document is not None
    db_session.add(
        EventEvidence(
            event_id=event.id,
            document_version_id=new_document.id,
            hint_index=2,
            source_url=new_document.canonical_url,
            locator="updated deadline",
        )
    )
    db_session.flush()

    result = FactConsolidator(
        db_session,
        SequenceAIProvider([_snapshot_fact(event, new_document, "2026-09-30")]),
    ).consolidate(event)

    assert not result.reused
    assert result.fact_set.deadline.value == "2026-09-30"
    assert not result.fact_set.deadline.conflict
    assert db_session.scalar(
        select(func.count()).select_from(FactSetRecord).where(
            FactSetRecord.event_id == event.id
        )
    ) == 2


def test_snapshot_fact_rebuild_reuses_materially_identical_fact_set(db_session) -> None:
    event, _, pages = _snapshot_event(db_session)
    document = db_session.get(
        DocumentVersion, pages["faq"].current_document_version_id
    )
    assert document is not None
    current = FactSetRecord(
        event_id=event.id,
        version=1,
        schema_version="4",
        facts=_snapshot_fact(event, document, "2026-08-31"),
        has_conflicts=False,
    )
    db_session.add(current)
    db_session.flush()
    event.current_fact_set_id = current.id

    result = FactConsolidator(
        db_session,
        SequenceAIProvider([_snapshot_fact(event, document, "2026-08-31")]),
    ).consolidate(event)

    assert result.reused
    assert result.record.id == current.id
    assert db_session.scalar(
        select(func.count()).select_from(FactSetRecord).where(
            FactSetRecord.event_id == event.id
        )
    ) == 1


def test_daily_monitor_runs_even_when_gmail_collection_fails(session_factory) -> None:
    fetcher = PageFetcher(_active_responses())
    with session_factory.begin() as session:
        _seed_watch(session)
        monitor_statusmatch_watches(session, fetcher)

    def unavailable_gmail(_source_id: str):
        raise PermissionError("simulated Gmail OAuth failure")

    result = run_daily_cycle(
        session_factory,
        DailyWorkflowProvider(),
        unavailable_gmail,
        source_ids=["status_services_mail"],
        statusmatch_fetcher=fetcher,
        now=datetime(2026, 8, 24, 8, tzinfo=UTC),
    )

    assert result.status == "FAILED"
    assert result.sources[0].status == "FAILED"
    assert result.statusmatch_projects_checked == 1
    assert result.statusmatch_pages_checked == 2
    assert result.statusmatch_pages_changed == 0
    assert result.statusmatch_errors == ()
    assert result.statusmatch_projects_succeeded == 1


def test_daily_cycle_processes_changed_watch_pages_when_mail_source_not_selected(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        _seed_watch(session)

    class OneFeedItem:
        source_id = "ffb_elite_status_feed"

        def discover(self):
            return [
                DiscoveredItem(
                    source_id=self.source_id,
                    external_id="selected-feed-item",
                    discovered_url="https://example.com/feed-item",
                    canonical_url="https://example.com/feed-item",
                )
            ]

        def fetch(self, item):
            return RawDocument(
                source_id=self.source_id,
                external_id=item.external_id,
                canonical_url=item.canonical_url,
                body="Ordinary points news",
                content_type="text/plain",
            )

    result = run_daily_cycle(
        session_factory,
        DailyWorkflowProvider(),
        lambda _source_id: OneFeedItem(),
        source_ids=["ffb_elite_status_feed"],
        statusmatch_fetcher=PageFetcher(_active_responses()),
        now=datetime(2026, 8, 25, 8, tzinfo=UTC),
    )

    assert result.status == "SUCCEEDED"
    assert result.statusmatch_pages_changed == 2
    assert result.statusmatch_projects_selected == 1
    assert result.statusmatch_projects_succeeded == 1
    assert result.statusmatch_project_model_calls == 2
    assert result.documents_selected == 1
    assert result.documents_succeeded == 1
