"""Assemble article briefs from persisted extraction copy, without model calls."""
from dataclasses import dataclass

from sqlalchemy import func, select

from journeyplus.article_pipeline.contracts import ArticleInterpretation
from journeyplus.contracts import (
    AnalysisStage, ArticleShortBrief, Brief, RunStatus, StatusMatchBrief, read_brief,
)
from journeyplus.knowledge.source_documents import source_links
from journeyplus.models import (
    AnalysisRun, ArticleAnalysisRecord, ArticleBriefRecord, SourceItem,
)

ARTICLE_BRIEF_PROMPT_VERSION = "article-brief-assembly-v1"
ARTICLE_BRIEF_SCHEMA_VERSION = "article-short-brief-1"


@dataclass(frozen=True)
class ArticleBriefGeneration:
    run: AnalysisRun
    record: ArticleBriefRecord
    brief: Brief | StatusMatchBrief
    reused: bool


class ArticleBriefGenerator:
    """Publish extracted copy. This assembler has no AI provider dependency."""

    def __init__(self, session):
        self._session = session

    def generate(self, opportunity):
        session = self._session
        current = (
            session.get(ArticleBriefRecord, opportunity.current_brief_id)
            if opportunity.current_brief_id else None
        )
        # Published historical copy is never regenerated implicitly.
        if current and current.input_version == opportunity.fact_signature:
            return ArticleBriefGeneration(
                session.get(AnalysisRun, current.analysis_run_id),
                current, read_brief(current.content), True,
            )
        analysis = session.get(ArticleAnalysisRecord, opportunity.analysis_id)
        extraction_run = session.get(AnalysisRun, analysis.analysis_run_id)
        if extraction_run.status != RunStatus.SUCCEEDED:
            raise ValueError("Cannot publish a brief from a failed extraction")
        extraction = ArticleInterpretation.model_validate(extraction_run.result)
        copy = next(
            op for op in extraction.opportunities
            if op.opportunity_index == opportunity.opportunity_index
        )
        # Only pre-merge persisted results may omit title. Do not hide corrupt new data.
        if not copy.title and extraction_run.prompt_version != "generic-article-interpretation-v11":
            raise ValueError("The extracted brief title is missing")
        item = session.get(SourceItem, analysis.source_item_id)
        brief = ArticleShortBrief(
            fact_set_id=opportunity.id,
            title=copy.title or item.title[:120],
            summary=copy.summary,
            source_links=source_links(session, opportunity),
        )
        key = f"ARTICLE_BRIEF:{opportunity.id}:{opportunity.fact_signature}:{ARTICLE_BRIEF_PROMPT_VERSION}"
        run = session.scalar(select(AnalysisRun).where(AnalysisRun.idempotency_key == key))
        if run is None:
            run = AnalysisRun(
                idempotency_key=key, document_version_id=analysis.document_version_id,
                stage=AnalysisStage.ARTICLE_BRIEF, input_version=opportunity.fact_signature,
                provider="program", model="none", model_config_version=ARTICLE_BRIEF_PROMPT_VERSION,
                prompt_version=ARTICLE_BRIEF_PROMPT_VERSION, schema_version=ARTICLE_BRIEF_SCHEMA_VERSION,
            )
            session.add(run)
        run.status = RunStatus.SUCCEEDED
        run.result = brief.model_dump(mode="json")
        run.error = None
        session.flush()
        version = (session.scalar(
            select(func.max(ArticleBriefRecord.version)).where(
                ArticleBriefRecord.opportunity_id == opportunity.id
            )
        ) or 0) + 1
        record = ArticleBriefRecord(
            opportunity_id=opportunity.id, analysis_run_id=run.id,
            input_version=opportunity.fact_signature, version=version,
            schema_version=brief.schema_version, content=brief.model_dump(mode="json"),
        )
        session.add(record)
        session.flush()
        opportunity.current_brief_id = record.id
        return ArticleBriefGeneration(run, record, brief, False)
