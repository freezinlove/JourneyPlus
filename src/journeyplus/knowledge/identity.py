"""Explicit activity identity operations; never infer an edition from a name/year.

Callers own the short transaction. Historical versions and their source bindings
remain on their original activity when an identity is merged.
"""
from __future__ import annotations

import json
import re
from uuid import UUID
from typing import Literal
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from journeyplus.contracts import StrictModel
from journeyplus.knowledge.models import Activity, EvidenceReference, KnowledgeMigrationLink, ActivityEditionReview


class UnresolvedActivityEdition(ValueError):
    pass


class EditionReviewRequest(StrictModel):
    source_table:Literal['status_events','article_opportunities']
    source_id:str=Field(min_length=1,max_length=100)
    current_id:UUID
    review_id:UUID
    decision:Literal['SAME','NEW','UNRESOLVED']
    reason:str=Field(min_length=1,max_length=2000)
    evidence_ids:list[UUID]=Field(default_factory=list,max_length=30)
    official_document_ids:list[UUID]=Field(default_factory=list,max_length=10)
    reviewed_document_ids:list[UUID]|None=None
    expected_version:UUID|None
    edition_key:str|None=Field(default=None,max_length=200)


class ActivityIdentityService:
    def __init__(self, session: Session):
        self.session = session

    def resolve(self, activity_id: UUID) -> Activity:
        seen = set()
        while activity_id not in seen:
            seen.add(activity_id)
            activity = self.session.get(Activity, activity_id)
            if activity is None:
                raise ValueError('Activity identity does not exist')
            if activity.merged_into_id is None:
                return activity
            activity_id = activity.merged_into_id
        raise ValueError('Activity identity merge cycle')

    def resolve_source(self,source_table:str,source_id:str,default_id:UUID)->Activity:
        review=self.session.scalar(select(ActivityEditionReview).where(
            ActivityEditionReview.source_table==source_table,ActivityEditionReview.source_id==str(source_id)).order_by(
                ActivityEditionReview.created_at.desc(),ActivityEditionReview.id.desc()).limit(1))
        if review is None:return self.resolve(default_id)
        if review.decision=='UNRESOLVED':raise UnresolvedActivityEdition('活动期次尚未确认，保留来源并暂缓发布')
        return self.resolve(review.target_activity_id)

    def review_edition(self,source_table:str,source_id:str,current_id:UUID,*,review_id:UUID,
                       decision:str,reason:str,evidence_ids:list[UUID],official_document_ids:list[UUID],
                       expected_version:UUID|None,edition_key:str|None=None,reviewed_document_ids:list[UUID]|None=None)->Activity|None:
        """Explicit source review, not a model tool or a brand/year heuristic.

        The caller supplies the verified official document scope. An unresolved
        review blocks publication until a later explicit review resolves it.
        """
        if source_table not in {'status_events','article_opportunities'}:raise ValueError('Unsupported edition source')
        if decision not in {'SAME','NEW','UNRESOLVED'} or not reason.strip():raise ValueError('Explicit edition decision and reason required')
        reviewed_document_ids=official_document_ids if reviewed_document_ids is None else reviewed_document_ids
        fingerprint=json.dumps({'current_id':str(current_id),'decision':decision,'reason':reason,
            'evidence_ids':sorted(map(str,evidence_ids)),'official_document_ids':sorted(map(str,official_document_ids)),
            'expected_version':str(expected_version) if expected_version else None,'edition_key':edition_key,
            'reviewed_document_ids':sorted(map(str,reviewed_document_ids))},sort_keys=True)
        current=self.session.scalar(select(Activity).where(Activity.id==current_id).with_for_update().execution_options(populate_existing=True))
        if current is None or current.merged_into_id:raise ValueError('Choose the canonical activity for edition review')
        prior=self.session.get(ActivityEditionReview,review_id)
        if prior:
            if prior.source_table!=source_table or prior.source_id!=str(source_id) or prior.request_json!=json.loads(fingerprint):
                raise ValueError('Edition review id reused with different content')
            return self.session.get(Activity,prior.target_activity_id) if prior.target_activity_id else None
        if current.current_version_id!=expected_version:raise ValueError('Activity changed since edition review')
        evidence=[self.session.get(EvidenceReference,e) for e in evidence_ids]
        if any(e is None for e in evidence):raise ValueError('Unknown edition evidence')
        if any(e.document_version_id not in reviewed_document_ids for e in evidence):raise ValueError('Edition evidence is outside the reviewed source scope')
        if decision in {'SAME','NEW'} and not evidence:raise ValueError('Edition decision requires evidence')
        target=current
        if decision=='NEW':
            if not edition_key or not edition_key.strip():raise ValueError('New edition requires a stable explicit key')
            if any(e.document_version_id not in official_document_ids for e in evidence):raise ValueError('New edition requires scoped official evidence')
            quote='\n'.join(e.quote for e in evidence)
            if re.search(r'(?:not|no)\s+(?:a\s+)?new (?:round|campaign)|not (?:eligible|permitted|allowed) (?:to apply )?again|cannot apply again|不是新一轮|不得再次申请',quote,re.I):
                raise ValueError('Edition evidence contains an unresolved negative statement')
            if not re.search(r'new (?:round|campaign)|(?:eligibility|application) reset|(?:apply|eligible) again|campaign (?:id|identifier)|新一轮|资格重置|可再次申请|活动标识',quote,re.I):
                raise ValueError('Year or brand text alone does not establish a new edition')
            from journeyplus.knowledge.publication import signature
            key='edition:'+signature({'source_table':source_table,'source_id':str(source_id),'edition_key':edition_key})
            target=self.session.scalar(select(Activity).where(Activity.identity_key==key))
            if target is None:
                target=Activity(identity_key=key,primary_program_id=current.primary_program_id,kind=current.kind,edition_key=edition_key)
                self.session.add(target);self.session.flush()
        if decision=='UNRESOLVED':target=None
        self.session.add(ActivityEditionReview(id=review_id,source_table=source_table,source_id=str(source_id),
            activity_id=current.id,base_version_id=expected_version,decision=decision,
            target_activity_id=target.id if target else None,reason=reason,request_json=json.loads(fingerprint)))
        self.session.flush()
        return target

    def merge(self, source_id: UUID, target_id: UUID, *, reason: str,
              evidence_ids: list[UUID], expected_source_version: UUID | None,
              expected_target_version: UUID | None) -> Activity:
        if source_id == target_id:
            raise ValueError('Cannot merge an activity into itself')
        if not reason.strip() or not evidence_ids:
            raise ValueError('Explicit same-edition reason and evidence are required')
        for identifier in evidence_ids:
            if self.session.get(EvidenceReference, identifier) is None:
                raise ValueError('Unknown identity evidence')
        # Rare administrative operation: stable lock order serializes concurrent
        # A→B / B→A decisions and chains without rewriting published versions.
        rows = {a.id: a for a in self.session.scalars(
            select(Activity).order_by(Activity.id).with_for_update()
            .execution_options(populate_existing=True))}
        if source_id not in rows or target_id not in rows:
            raise ValueError('Activity identity does not exist')
        source, target = rows[source_id], rows[target_id]
        if target.merged_into_id is not None:
            raise ValueError('Choose the current canonical target explicitly')
        if source.merged_into_id == target_id:
            return target
        if source.merged_into_id is not None:
            raise ValueError('Source was already merged elsewhere')
        if (source.current_version_id, target.current_version_id) != (
                expected_source_version, expected_target_version):
            raise ValueError('Activity changed since identity review')
        if source.primary_program_id != target.primary_program_id or source.kind != target.kind:
            raise ValueError('Different program or activity kind cannot be merged')
        source.merged_into_id = target.id
        self.session.add(KnowledgeMigrationLink(
            legacy_table='activities', legacy_id=str(source.id), legacy_path='identity',
            migration_version='activity-identity-v1', target_table='activities',
            target_id=target.id, status='MAPPED', reason=json.dumps({
                'reason': reason, 'evidence_ids': list(map(str, evidence_ids)),
                'source_version': str(expected_source_version) if expected_source_version else None,
                'target_version': str(expected_target_version) if expected_target_version else None,
            }, ensure_ascii=False)))
        self.session.flush()
        return target
