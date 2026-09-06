"""Network-free publication of prefetched official pages, one project at a time."""
from types import SimpleNamespace

from sqlalchemy import select

from journeyplus.models import StatusMatchWatch, StatusMatchWatchPage
from journeyplus.statusmatch.closure import assess_statusmatch_home_closure
from journeyplus.statusmatch.fetching import fetch_statusmatch_page
from journeyplus.statusmatch.service import StatusMatchMonitoringSummary, monitor_statusmatch_watches
from journeyplus.statusmatch.watchlist import ensure_statusmatch_watch, statusmatch_page_item


class _PageCache:
    def __init__(self):
        self.responses = {}

    def get(self, url):
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def _snapshot(session, watch):
    return (watch.current_event_id, tuple(session.execute(
        select(StatusMatchWatchPage.page_kind, StatusMatchWatchPage.canonical_url,
               StatusMatchWatchPage.current_document_version_id, StatusMatchWatchPage.last_checked_at)
        .where(StatusMatchWatchPage.watch_id == watch.id).order_by(StatusMatchWatchPage.page_kind)).all()))


def monitor_statusmatch_projects(factory, fetcher, *, checked_at=None, hosts=None):
    """Finish HTTP before entering the source publication transaction.

    Reuse the established parser/closure/error policies through an in-memory response
    cache. Cache misses fail closed; publication cannot fall back to live HTTP.
    """
    with factory() as session:
        query = select(StatusMatchWatch.id, StatusMatchWatch.host).order_by(StatusMatchWatch.host)
        if hosts is not None:
            query = query.where(StatusMatchWatch.host.in_({h.casefold().rstrip('.') for h in hosts}))
        selected = list(session.execute(query))
    results = []
    errors = []
    for watch_id, host in selected:
        with factory.begin() as session:
            watch = session.get(StatusMatchWatch, watch_id)
            if watch is None:
                continue
            ensure_statusmatch_watch(session, host)
            baseline = _snapshot(session, watch)
            items = {kind: statusmatch_page_item(host=host, page_kind=kind, canonical_url=url, refresh=True)
                     for kind, url, _, _ in baseline[1]}
        cache = _PageCache()
        class RecordingFetcher:
            def get(self, url):
                response = fetcher.get(url)
                cache.responses[url] = response
                return response
        recording = RecordingFetcher()
        for kind in ('activity', 'faq', 'terms'):
            item = items.get(kind)
            if item is None:
                continue
            try:
                raw = fetch_statusmatch_page(item, recording)
                if kind == 'activity':
                    document = SimpleNamespace(raw_body=raw.body, normalized_body='', content_type=raw.content_type,
                                               canonical_url=raw.canonical_url)
                    source = SimpleNamespace(raw_metadata=raw.metadata)
                    if assess_statusmatch_home_closure(activity=document, activity_item=source).closed:
                        break
            except Exception as exc:
                cache.responses[item.canonical_url] = exc
                if kind == 'activity':
                    break
        with factory.begin() as session:
            watch = session.scalar(select(StatusMatchWatch).where(StatusMatchWatch.id == watch_id).with_for_update())
            if watch is None or _snapshot(session, watch) != baseline:
                errors.append(f'{host}:STALE_MONITORING_BASELINE')
                continue
            results.append(monitor_statusmatch_watches(session, cache, checked_at=checked_at, hosts=[host]))
    return StatusMatchMonitoringSummary(
        projects_checked=len(selected),
        pages_checked=sum(r.pages_checked for r in results),
        pages_changed=sum(r.pages_changed for r in results),
        projects_archived=sum(r.projects_archived for r in results),
        changed_document_version_ids=tuple(d for r in results for d in r.changed_document_version_ids),
        errors=tuple(errors) + tuple(e for r in results for e in r.errors),
    )
