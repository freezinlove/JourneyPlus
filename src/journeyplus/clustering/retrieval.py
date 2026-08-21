from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.orm import Session

from journeyplus.contracts import EventHint
from journeyplus.models import StatusEvent


class CandidateRetriever:
    def __init__(
        self,
        session: Session,
        *,
        lookback_days: int = 730,
        limit: int = 10,
    ) -> None:
        self._session = session
        self._lookback_days = lookback_days
        self._limit = limit

    def retrieve(self, hint: EventHint) -> list[StatusEvent]:
        since = datetime.now(UTC) - timedelta(days=self._lookback_days)
        base = select(StatusEvent).where(
            StatusEvent.created_at >= since,
            StatusEvent.merged_into_id.is_(None),
        )
        dialect = self._session.get_bind().dialect.name
        terms = " ".join(
            value
            for value in (hint.program, hint.target_status, hint.summary)
            if value
        )
        if dialect == "postgresql":
            document = func.to_tsvector("simple", StatusEvent.search_text)
            query = func.plainto_tsquery("simple", terms)
            text_match = document.op("@@")(query)
        else:
            lowered = terms.casefold()
            text_match = func.lower(StatusEvent.search_text).like(f"%{lowered}%")
        query_stmt = base.where(
            or_(
                func.lower(StatusEvent.program) == hint.program.casefold(),
                StatusEvent.opportunity_type == hint.opportunity_type,
                text_match,
                and_(
                    hint.target_status is not None,
                    func.lower(cast(StatusEvent.target_status, String))
                    == (hint.target_status or "").casefold(),
                ),
            )
        ).limit(self._limit)
        candidates = list(self._session.scalars(query_stmt))
        return sorted(
            candidates,
            key=lambda event: _candidate_score(event, hint),
            reverse=True,
        )


def _candidate_score(event: StatusEvent, hint: EventHint) -> tuple[int, datetime]:
    score = 0
    score += 4 * (event.program.casefold() == hint.program.casefold())
    score += 2 * (event.opportunity_type == hint.opportunity_type)
    score += int(
        bool(event.target_status and hint.target_status)
        and event.target_status.casefold() == (hint.target_status or "").casefold()
    )
    updated_at = event.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    else:
        updated_at = updated_at.astimezone(UTC)
    return score, updated_at
