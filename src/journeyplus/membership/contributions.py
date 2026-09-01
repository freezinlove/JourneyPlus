from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.article_pipeline.visibility import is_mapping_visible
from journeyplus.contracts import FactSet, MappingAvailability
from journeyplus.lifecycle.service import BEIJING_TZ, as_beijing
from journeyplus.membership.contracts import (
    ContributionCertainty,
    ExcludedMappingContribution,
    MappingContributionProvenance,
    MappingContributionSource,
    MembershipMappingContribution,
    MembershipProgramCategory,
)
from journeyplus.membership.normalization import stable_id
from journeyplus.models import (
    ArticleAnalysisRecord,
    ArticleOpportunityRecord,
    DocumentVersion,
    SourceItem,
    StatusMatchArticleRoute,
)
from journeyplus.opportunity_shaping import (
    opportunity_kind_for_facts,
    with_legacy_opportunity_kind,
)
from journeyplus.contracts import OpportunityKind
from journeyplus.statusmatch.graph import MembershipGraphService
from journeyplus.statusmatch.graph_contracts import GraphSnapshot


ORDINARY_ARTICLE_SOURCE_ID = "loyaltylobby_feed"


@dataclass(frozen=True, slots=True)
class MappingContributionBatch:
    contributions: tuple[MembershipMappingContribution, ...] = ()
    excluded: tuple[ExcludedMappingContribution, ...] = ()


@dataclass(frozen=True, slots=True)
class OfficialMappingContributionBatch(MappingContributionBatch):
    snapshot: GraphSnapshot | None = None


class StatusMatchOfficialContributionAdapter:
    """Read-only adapter over the current authoritative StatusMatch graph."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def read(self) -> OfficialMappingContributionBatch:
        snapshot = MembershipGraphService(self._session).build()
        node_by_id = {node.id: node for node in snapshot.nodes}
        contributions: list[MembershipMappingContribution] = []
        for edge in snapshot.edges:
            source_node = node_by_id[edge.source_node_id]
            target_node = node_by_id[edge.target_node_id]
            for claim in edge.claims:
                contributions.append(
                    _official_contribution(
                        claim=claim,
                        source_program=source_node.program,
                        source_tier=source_node.tier,
                        target_program=target_node.program,
                        target_tier=target_node.tier,
                        certainty=ContributionCertainty.EXACT,
                    )
                )
        for rule in snapshot.rules:
            target_node = node_by_id[rule.target_node_id]
            for claim in rule.claims:
                contribution = _official_contribution(
                    claim=claim,
                    source_program=claim.source_program,
                    source_tier=claim.source_tier,
                    target_program=target_node.program,
                    target_tier=target_node.tier,
                    certainty=ContributionCertainty(str(rule.certainty)),
                )
                contributions.append(
                    contribution.model_copy(
                        update={
                            "rule_source_program_key": rule.source_program_key,
                            "rule_source_tier_key": rule.source_tier_key,
                            "source_category": MembershipProgramCategory(
                                str(rule.source_category)
                            ),
                        }
                    )
                )
        return OfficialMappingContributionBatch(
            snapshot=snapshot,
            contributions=tuple(
                sorted(contributions, key=lambda item: item.contribution_id)
            ),
        )


class OrdinaryArticleContributionAdapter:
    """Read grounded direct mappings from current ordinary article analyses."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def read(self, *, now: datetime | None = None) -> MappingContributionBatch:
        current = as_beijing(now or datetime.now(BEIJING_TZ))
        analyses = list(
            self._session.scalars(
                select(ArticleAnalysisRecord)
                .join(SourceItem, SourceItem.id == ArticleAnalysisRecord.source_item_id)
                .where(
                    ArticleAnalysisRecord.status == "SUCCEEDED",
                    SourceItem.source_id == ORDINARY_ARTICLE_SOURCE_ID,
                )
                .order_by(
                    ArticleAnalysisRecord.source_item_id,
                    ArticleAnalysisRecord.created_at.desc(),
                    ArticleAnalysisRecord.id.desc(),
                )
            )
        )
        latest: dict[UUID, ArticleAnalysisRecord] = {}
        for analysis in analyses:
            latest.setdefault(analysis.source_item_id, analysis)
        routed_document_ids = set(
            self._session.scalars(select(StatusMatchArticleRoute.document_version_id))
        )
        contributions: list[MembershipMappingContribution] = []
        excluded: list[ExcludedMappingContribution] = []
        for source_item_id, analysis in latest.items():
            item = self._session.get(SourceItem, source_item_id)
            document = self._session.get(DocumentVersion, analysis.document_version_id)
            if item is None or document is None:
                excluded.append(
                    _excluded(
                        analysis.id,
                        "MISSING_SOURCE_MATERIAL",
                        "SourceItem or DocumentVersion is missing",
                    )
                )
                continue
            opportunities = list(
                self._session.scalars(
                    select(ArticleOpportunityRecord)
                    .where(ArticleOpportunityRecord.analysis_id == analysis.id)
                    .order_by(ArticleOpportunityRecord.opportunity_index)
                )
            )
            if analysis.document_version_id in routed_document_ids:
                excluded.extend(
                    _excluded(
                        opportunity.id,
                        "ROUTED_STATUSMATCH_SUPPLEMENT",
                        "Linked StatusMatch articles are highlights-only",
                    )
                    for opportunity in opportunities
                )
                continue
            for opportunity in opportunities:
                visibility_reason = _visibility_exclusion_reason(
                    opportunity, current=current
                )
                if visibility_reason is not None or not is_mapping_visible(
                    opportunity,
                    analysis,
                    item,
                    now=current,
                    latest_successful_analysis_id=analysis.id,
                ):
                    excluded.append(
                        _excluded(
                            opportunity.id,
                            visibility_reason or "NOT_CURRENT",
                            "Article opportunity is not a current mapping contributor",
                        )
                    )
                    continue
                opportunity_kind = opportunity_kind_for_facts(
                    opportunity.facts,
                    summary=opportunity.summary,
                    target_status=opportunity.target_status,
                )
                if opportunity_kind != OpportunityKind.STATUS_MATCH:
                    excluded.append(
                        _excluded(
                            opportunity.id,
                            "OTHER_OPPORTUNITY_KIND",
                            "Opportunity is retained for briefs but excluded from personalized mappings",
                        )
                    )
                    continue
                try:
                    facts = FactSet.model_validate(
                        with_legacy_opportunity_kind(
                            opportunity.facts,
                            summary=opportunity.summary,
                            target_status=opportunity.target_status,
                        )
                    )
                except Exception as exc:
                    excluded.append(
                        _excluded(
                            opportunity.id,
                            "INVALID_FACT_SET",
                            " ".join(str(exc).split())[:1000],
                        )
                    )
                    continue
                for mapping_index, mapping in enumerate(facts.status_mappings):
                    if mapping.availability == MappingAvailability.UNAVAILABLE:
                        excluded.append(
                            _excluded(opportunity.id, "UNAVAILABLE", None)
                        )
                        continue
                    if mapping.conflict:
                        excluded.append(_excluded(opportunity.id, "CONFLICTING", None))
                        continue
                    if not mapping.source_tiers:
                        excluded.append(
                            _excluded(opportunity.id, "MISSING_SOURCE_TIER", None)
                        )
                        continue
                    if not _evidence_is_grounded(mapping.evidence, document):
                        excluded.append(_excluded(opportunity.id, "UNGROUNDED", None))
                        continue
                    for tier_index, source_tier in enumerate(mapping.source_tiers):
                        contributions.append(
                            MembershipMappingContribution(
                                contribution_id=stable_id(
                                    "article-contribution",
                                    str(opportunity.id),
                                    str(mapping_index),
                                    str(tier_index),
                                ),
                                source=MappingContributionSource.ORDINARY_ARTICLE,
                                source_program=mapping.source_program,
                                source_tier=source_tier,
                                target_program=opportunity.program,
                                target_tier=mapping.target_tier,
                                availability=mapping.availability,
                                conditions=mapping.conditions,
                                evidence=mapping.evidence,
                                conflict=False,
                                certainty=ContributionCertainty.EXACT,
                                visible_from_at=opportunity.application_start_at,
                                visible_until_at=opportunity.visibility_until_at,
                                provenance=MappingContributionProvenance(
                                    subject_id=opportunity.id,
                                    opportunity_id=opportunity.id,
                                    source_document_version_id=document.id,
                                    source_url=item.canonical_url,
                                ),
                            )
                        )
        return MappingContributionBatch(
            contributions=tuple(
                sorted(contributions, key=lambda item: item.contribution_id)
            ),
            excluded=tuple(
                sorted(excluded, key=lambda item: (item.reason, str(item.subject_id)))
            ),
        )


def _official_contribution(
    *, claim, source_program: str, source_tier: str, target_program: str,
    target_tier: str, certainty: ContributionCertainty,
) -> MembershipMappingContribution:
    evidence = list(claim.evidence)
    first = evidence[0]
    return MembershipMappingContribution(
        contribution_id=f"official:{claim.id}",
        source=MappingContributionSource.STATUSMATCH_OFFICIAL,
        source_program=source_program,
        source_tier=source_tier,
        target_program=target_program,
        target_tier=target_tier,
        availability=claim.availability,
        conditions=claim.conditions,
        evidence=evidence,
        conflict=claim.conflict,
        conflict_note=claim.conflict_note,
        certainty=certainty,
        source_category=MembershipProgramCategory(str(claim.source_category)),
        provenance=MappingContributionProvenance(
            subject_id=claim.fact_set_id,
            source_document_version_id=first.document_version_id,
            source_url=str(first.source_url),
            fact_set_id=claim.fact_set_id,
            event_id=claim.event_id,
            watch_id=claim.watch_id,
        ),
    )


def _excluded(
    subject_id: UUID,
    reason: str,
    detail: str | None,
) -> ExcludedMappingContribution:
    return ExcludedMappingContribution(
        subject_id=subject_id,
        source=MappingContributionSource.ORDINARY_ARTICLE,
        reason=reason,
        detail=detail,
    )


def _visibility_exclusion_reason(
    opportunity: ArticleOpportunityRecord, *, current: datetime
) -> str | None:
    if opportunity.archived_at is not None:
        return "ARCHIVED"
    if opportunity.application_start_at is not None:
        if current < as_beijing(opportunity.application_start_at):
            return "UPCOMING"
    if opportunity.visibility_until_at is None:
        return "MISSING_VISIBILITY"
    if current >= as_beijing(opportunity.visibility_until_at):
        return "EXPIRED"
    return None


def _evidence_is_grounded(evidence, document: DocumentVersion) -> bool:
    body = " ".join(document.normalized_body.split()).casefold()
    if not evidence:
        return False
    return all(
        item.document_version_id == document.id
        and " ".join(item.locator.split()).casefold() in body
        for item in evidence
    )
