"""HOME controls closure; all three pages still participate in change detection."""
import pytest
from sqlalchemy import select, func

from journeyplus.models import DocumentVersion, StatusEvent, StatusMatchWatch, StatusMatchWatchPage
from journeyplus.statusmatch.monitoring import monitor_statusmatch_projects
from journeyplus.statusmatch.service import monitor_statusmatch_watches
from tests.test_agent_workflow_reads import original_factory
from tests.test_statusmatch_monitoring import PageFetcher, _active_responses, _seed_watch


HOME = 'https://example.statusmatch.com/'
ENDED = '<html><body>This status match offer has ended.</body></html>'


def monitor(factory, fetcher, implementation):
    if implementation == 'prefetched':
        return monitor_statusmatch_projects(factory, fetcher)
    with factory.begin() as session:
        return monitor_statusmatch_watches(session, fetcher)


def seed(factory):
    with factory.begin() as session:
        watch = _seed_watch(session)
        event = StatusEvent(created_from_key='home-only-test', program='Example Club', summary='Matching activity')
        session.add(event); session.flush()
        watch.current_event_id = event.id
        return watch.id, event.id


@pytest.mark.parametrize('implementation', ['direct', 'prefetched'])
@pytest.mark.parametrize('changed_pages', [('faq',), ('terms',), ('faq','terms')])
def test_secondary_ended_text_is_a_content_change_not_a_lifecycle_signal(original_factory, implementation, changed_pages):
    watch_id, event_id = seed(original_factory)
    responses = _active_responses()
    first = monitor(original_factory, PageFetcher(responses), implementation)
    assert first.pages_changed == 3
    for page in changed_pages:
        responses[HOME+page] = ENDED
    fetcher = PageFetcher(responses)
    changed = monitor(original_factory, fetcher, implementation)
    assert fetcher.calls == [HOME, HOME+'faq', HOME+'terms']
    assert changed.pages_checked == 3 and changed.pages_changed == len(changed_pages)
    assert changed.projects_archived == 0 and not changed.errors
    with original_factory() as session:
        watch = session.get(StatusMatchWatch, watch_id)
        event = session.get(StatusEvent, event_id)
        assert watch.status == 'ACTIVE' and watch.last_error is None
        assert event.archived_at is None and event.lifecycle_status != 'EXPIRED'
        assert session.scalar(select(func.count()).select_from(DocumentVersion)) == 3+len(changed_pages)
        for page in session.scalars(select(StatusMatchWatchPage)):
            assert page.last_error is None
            if page.page_kind in changed_pages:
                assert 'has ended' in session.get(DocumentVersion, page.current_document_version_id).normalized_body
    again = PageFetcher(responses)
    unchanged = monitor(original_factory, again, implementation)
    assert unchanged.pages_changed == 0 and unchanged.pages_checked == 3
    assert again.calls == [HOME, HOME+'faq', HOME+'terms']


@pytest.mark.parametrize('implementation', ['direct','prefetched'])
def test_home_closure_archives_without_fetching_secondary_pages(original_factory, implementation):
    watch_id, event_id = seed(original_factory)
    monitor(original_factory, PageFetcher(_active_responses()), implementation)
    fetcher = PageFetcher({HOME:ENDED})  # Unexpected secondary requests would fail.
    result = monitor(original_factory, fetcher, implementation)
    assert fetcher.calls == [HOME] and result.pages_checked == 1
    assert result.projects_archived == 1 and not result.errors
    with original_factory() as session:
        assert session.get(StatusMatchWatch, watch_id) is None
        event = session.get(StatusEvent, event_id)
        assert event.archived_at is not None and event.lifecycle_status == 'EXPIRED'
        assert session.get(DocumentVersion,event.closure_document_version_id).canonical_url == HOME
        assert session.scalar(select(func.count()).select_from(DocumentVersion)) == 4


@pytest.mark.parametrize('implementation', ['direct','prefetched'])
def test_secondary_fetch_failure_is_still_an_error_not_closure(original_factory, implementation):
    watch_id, event_id = seed(original_factory)
    monitor(original_factory, PageFetcher(_active_responses()), implementation)
    responses = _active_responses(); responses[HOME+'faq'] = RuntimeError('temporary fetch failure')
    result = monitor(original_factory, PageFetcher(responses), implementation)
    assert result.projects_archived == 0 and result.errors
    with original_factory() as session:
        assert 'temporary fetch failure' in session.get(StatusMatchWatch,watch_id).last_error
        faq = session.scalar(select(StatusMatchWatchPage).where(
            StatusMatchWatchPage.watch_id == watch_id, StatusMatchWatchPage.page_kind == 'faq'))
        assert 'temporary fetch failure' in faq.last_error
        assert session.get(StatusEvent,event_id).archived_at is None
