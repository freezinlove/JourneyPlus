from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from journeyplus.ai.provider import AIProvider
from journeyplus.article_pipeline.contracts import TitleScreenDecision
from journeyplus.article_pipeline.screening import BatchTitleScreener
from journeyplus.models import DocumentVersion


@dataclass(frozen=True, slots=True)
class TitleScreenGoldCase:
    document_version_id: UUID
    expected_positive: bool


@dataclass(frozen=True, slots=True)
class TitleScreenShadowReport:
    documents: int
    expected_positives: int
    positive_drops: int
    decisions: dict[str, int]
    batch_model_calls: int
    reused: int
    safe_to_enable_drop: bool


def run_title_screen_shadow(
    session: Session,
    provider: AIProvider,
    cases: list[TitleScreenGoldCase],
    *,
    batch_size: int = 25,
) -> TitleScreenShadowReport:
    documents: list[DocumentVersion] = []
    expected: dict[UUID, bool] = {}
    for case in cases:
        document = session.get(DocumentVersion, case.document_version_id)
        if document is None:
            raise LookupError(f"Document {case.document_version_id} was not found")
        documents.append(document)
        expected[document.id] = case.expected_positive
    calls_before = _call_count(provider)
    outcomes = BatchTitleScreener(
        session, provider, batch_size=batch_size
    ).screen(documents)
    decisions = Counter(str(item.result.decision) for item in outcomes)
    positive_drops = sum(
        expected[item.result.document_version_id]
        and item.result.decision == TitleScreenDecision.DROP
        for item in outcomes
    )
    return TitleScreenShadowReport(
        documents=len(cases),
        expected_positives=sum(case.expected_positive for case in cases),
        positive_drops=positive_drops,
        decisions=dict(sorted(decisions.items())),
        batch_model_calls=_call_count(provider) - calls_before,
        reused=sum(item.reused for item in outcomes),
        safe_to_enable_drop=positive_drops == 0,
    )


def _call_count(provider: AIProvider) -> int:
    value = getattr(provider, "calls", 0)
    return len(value) if isinstance(value, list) else int(value)
