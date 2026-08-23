from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from journeyplus.contracts import EventHint, LifecycleStatus
from journeyplus.lifecycle.service import (
    as_beijing,
    normalize_event_time,
    windows_non_overlapping,
)
from journeyplus.models import DocumentVersion, EventEvidence, StatusEvent
from journeyplus.status_topic.source_context import catalog_authoritative_program


class CandidateRetriever:
    def __init__(
        self,
        session: Session,
        *,
        lookback_days: int = 730,
        limit: int = 10,
        candidate_pool_limit: int = 200,
    ) -> None:
        self._session = session
        self._lookback_days = lookback_days
        self._limit = limit
        self._candidate_pool_limit = candidate_pool_limit

    def retrieve(
        self,
        hint: EventHint,
        *,
        document: DocumentVersion | None = None,
    ) -> list[StatusEvent]:
        current = datetime.now(UTC)
        since = current - timedelta(days=self._lookback_days)
        candidates = list(
            self._session.scalars(
                select(StatusEvent)
                .where(
                    StatusEvent.created_at >= since,
                    StatusEvent.merged_into_id.is_(None),
                    StatusEvent.archived_at.is_(None),
                    StatusEvent.lifecycle_status != LifecycleStatus.EXPIRED,
                    or_(
                        StatusEvent.application_deadline_at.is_(None),
                        StatusEvent.application_deadline_at >= current,
                    ),
                )
                .order_by(StatusEvent.updated_at.desc())
                .limit(self._candidate_pool_limit)
            )
        )
        authoritative_program = (
            catalog_authoritative_program(self._session, document)
            if document is not None
            else None
        )
        new_links = _link_signals(document.normalized_body if document else "")
        candidate_links = self._candidate_link_signals(candidates) if new_links[0] else {}
        if authoritative_program is not None:
            candidate_project_hosts = self._candidate_project_hosts(candidates)
            new_project_hosts = matching_project_statusmatch_hosts(
                document.normalized_body if document else "",
                " ".join(
                    value
                    for value in (
                        authoritative_program,
                        hint.program,
                        hint.summary,
                    )
                    if value
                ),
            )
            candidates = [
                event
                for event in candidates
                if _program_score(event.program, authoritative_program) > 0
                or bool(
                    new_project_hosts
                    & candidate_project_hosts.get(event.id, set())
                )
            ]
        scored = [
            (
                _candidate_score(
                    event,
                    hint,
                    link_score=_shared_link_score(
                        new_links,
                        candidate_links.get(event.id, (set(), set())),
                    ),
                ),
                event,
            )
            for event in candidates
        ]
        return [
            event
            for score, event in sorted(scored, key=lambda item: item[0], reverse=True)
            if score[0] > 0
        ][: self._limit]

    def _candidate_link_signals(
        self, candidates: list[StatusEvent]
    ) -> dict[object, tuple[set[str], set[str]]]:
        if not candidates:
            return {}
        bodies: dict[object, list[str]] = defaultdict(list)
        for event_id, normalized_body in self._session.execute(
            select(EventEvidence.event_id, DocumentVersion.normalized_body)
            .join(
                DocumentVersion,
                DocumentVersion.id == EventEvidence.document_version_id,
            )
            .where(EventEvidence.event_id.in_([event.id for event in candidates]))
        ):
            bodies[event_id].append(normalized_body)
        return {
            event_id: _link_signals("\n".join(materials))
            for event_id, materials in bodies.items()
        }

    def _candidate_project_hosts(
        self, candidates: list[StatusEvent]
    ) -> dict[object, set[str]]:
        if not candidates:
            return {}
        events = {event.id: event for event in candidates}
        bodies: dict[object, list[str]] = defaultdict(list)
        for event_id, normalized_body in self._session.execute(
            select(EventEvidence.event_id, DocumentVersion.normalized_body)
            .join(
                DocumentVersion,
                DocumentVersion.id == EventEvidence.document_version_id,
            )
            .where(EventEvidence.event_id.in_(events))
        ):
            bodies[event_id].append(normalized_body)
        return {
            event_id: matching_project_statusmatch_hosts(
                "\n".join(materials), _event_identity(events[event_id])
            )
            for event_id, materials in bodies.items()
        }


def _candidate_score(
    event: StatusEvent,
    hint: EventHint,
    *,
    link_score: int = 0,
) -> tuple[int, datetime]:
    score = _program_score(event.program, hint.program)

    event_context = " ".join(
        value for value in (event.program, event.target_status, event.search_text) if value
    )
    hint_context = " ".join(
        value for value in (hint.program, hint.target_status, hint.summary) if value
    )
    shared_context = _distinctive_tokens(event_context) & _distinctive_tokens(
        hint_context
    )
    if len(shared_context) >= 2:
        score = max(score, 20 + min(len(shared_context), 10))
    score = max(score, link_score)
    score = max(score, _window_score(event, hint))

    updated_at = event.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    else:
        updated_at = updated_at.astimezone(UTC)
    return score, updated_at


def _window_score(event: StatusEvent, hint: EventHint) -> int:
    hint_start = normalize_event_time(hint.application_start, end_of_day=False)
    hint_deadline = normalize_event_time(hint.application_deadline, end_of_day=True)
    if windows_non_overlapping(
        hint_start,
        hint_deadline,
        event.application_start_at,
        event.application_deadline_at,
    ):
        return 0
    exact_boundaries = sum(
        left is not None and right is not None and left == right
        for left, right in (
            (
                hint_start,
                as_beijing(event.application_start_at)
                if event.application_start_at
                else None,
            ),
            (
                hint_deadline,
                as_beijing(event.application_deadline_at)
                if event.application_deadline_at
                else None,
            ),
        )
    )
    if exact_boundaries:
        return 35 + exact_boundaries * 5
    if (hint_start or hint_deadline) and (
        event.application_start_at or event.application_deadline_at
    ):
        return 25
    return 0


def _event_identity(event: StatusEvent) -> str:
    return " ".join(
        value
        for value in (
            event.program,
            event.target_status,
            event.summary,
            event.search_text,
        )
        if value
    )


def _program_score(left: str, right: str) -> int:
    normalized_left = _normalized_text(left)
    normalized_right = _normalized_text(right)
    if normalized_left == normalized_right:
        return 100
    if (
        min(
            len(normalized_left.replace(" ", "")),
            len(normalized_right.replace(" ", "")),
        )
        >= 4
        and (
            normalized_left in normalized_right
            or normalized_right in normalized_left
        )
    ):
        return 80
    shared = _distinctive_tokens(left) & _distinctive_tokens(right)
    return 60 + min(len(shared), 10) if len(shared) >= 2 else 0


_GENERIC_TOKENS = {
    "airline",
    "airlines",
    "airways",
    "club",
    "elite",
    "fast",
    "gold",
    "hotel",
    "hotels",
    "match",
    "offer",
    "offers",
    "opportunity",
    "paid",
    "platinum",
    "program",
    "programme",
    "reward",
    "rewards",
    "silver",
    "status",
    "track",
}


def _normalized_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().replace("&", " ")
    return " ".join(re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", normalized))


def _distinctive_tokens(value: str) -> set[str]:
    return {
        token
        for token in _normalized_text(value).split()
        if token not in _GENERIC_TOKENS and (len(token) >= 3 or not token.isascii())
    }


_URL_RE = re.compile(r"https?://[^\s)\]>\"']+", re.IGNORECASE)
_MARKDOWN_LINK_RE = re.compile(
    r"\[([^\]]+)\]\((https?://[^\s)]+)\)", re.IGNORECASE
)


def _link_signals(value: str) -> tuple[set[str], set[str]]:
    exact: set[str] = set()
    hosts: set[str] = set()
    for raw_url in _URL_RE.findall(value):
        parsed = urlsplit(raw_url.rstrip(".,;:!?"))
        host = (parsed.hostname or "").casefold()
        if host.startswith("www."):
            host = host[4:]
        if not host:
            continue
        path = parsed.path.rstrip("/") or "/"
        hosts.add(host)
        exact.add(f"{host}{path}")
    return exact, hosts


def matching_project_statusmatch_hosts(value: str, identity: str) -> set[str]:
    """Return project-specific StatusMatch hosts that belong to one event identity."""

    matching = _matching_project_statusmatch_hosts(_link_signals(value)[1], identity)
    identity_tokens = _distinctive_tokens(identity)
    for label, raw_url in _MARKDOWN_LINK_RE.findall(value):
        host = _normalized_host(raw_url)
        if (
            _is_project_statusmatch_host(host)
            and _distinctive_tokens(label) & identity_tokens
        ):
            matching.add(host)
    return matching


def _matching_project_statusmatch_hosts(
    hosts: set[str], identity: str
) -> set[str]:
    compact_identity = _compact_identifier(identity)
    if not compact_identity:
        return set()
    matching: set[str] = set()
    suffix = ".statusmatch.com"
    for host in hosts:
        if not _is_project_statusmatch_host(host):
            continue
        project = _compact_identifier(host[: -len(suffix)])
        if len(project) >= 3 and project in compact_identity:
            matching.add(host)
    return matching


def _compact_identifier(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(re.findall(r"[a-z0-9]+", normalized))


def _normalized_host(raw_url: str) -> str:
    host = (urlsplit(raw_url).hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


def _is_project_statusmatch_host(host: str) -> bool:
    return host != "statusmatch.com" and host.endswith(".statusmatch.com")


def _shared_link_score(
    left: tuple[set[str], set[str]],
    right: tuple[set[str], set[str]],
) -> int:
    if left[0] & right[0]:
        return 55
    shared_hosts = left[1] & right[1]
    if any(
        host == "statusmatch.com" or host.endswith(".statusmatch.com")
        for host in shared_hosts
    ):
        return 50
    return 15 if shared_hosts else 0
