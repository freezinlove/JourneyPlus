"""Workspace-local minimal observations; context changes trigger reclassification."""
from datetime import datetime,timedelta,UTC
from copy import deepcopy
from pydantic import BaseModel,ConfigDict,Field
from typing import Literal
from journeyplus.knowledge.publication import signature
from journeyplus.agent.step_observations import ResearchTarget,ReportObservation,summarize_step


class ResearchCoverage(BaseModel):
    model_config=ConfigDict(extra='forbid')
    complete:bool=False
    requests:int=Field(default=0,ge=0,le=12)
    report_count:int=Field(default=0,ge=0,le=8)
    stopped_reason:Literal['REQUEST_BUDGET','BYTE_BUDGET','TIME_BUDGET','REPORT_BUDGET','HTTP_ERROR','PARSE_ERROR','NO_REPORTS']|None=None


def cache_key(target:ResearchTarget):
    # Context and step rendering IDs can change while the same versioned direction
    # remains useful. Reuse reports, never reuse the old comparability conclusion.
    return signature({'target':target.model_dump(exclude={'context','step_ref'}),'schema':1,'window':'12-24-months'})


def save_observations(state,target,reports,*,now:datetime,workspace_expires_at:datetime,coverage:dict):
    if now.tzinfo is None or workspace_expires_at.tzinfo is None:raise ValueError('Research cache timestamps need timezone')
    if len(reports)>8:raise ValueError('Report cache exceeds per-turn detail budget')
    coverage=ResearchCoverage.model_validate(coverage).model_dump(mode='json')
    if workspace_expires_at<=now:return
    records=state.setdefault('research',{}).setdefault('step_records_v1',{})
    key=cache_key(target)
    records[key]={'schema_version':1,'observed_at':now.isoformat(),
        'expires_at':min(now+timedelta(hours=1),workspace_expires_at).isoformat(),
        'reports':[r.model_dump(mode='json') for r in reports],'coverage':deepcopy(coverage)}


def cached_observations(state,target,*,now:datetime):
    records=state.get('research',{}).get('step_records_v1',{})
    for key in list(records):
        if datetime.fromisoformat(records[key]['expires_at'])<=now:del records[key]
    record=records.get(cache_key(target))
    if record is None:return None
    reports=[ReportObservation.model_validate(value) for value in record['reports']]
    summary=summarize_step(target,reports,today=now.astimezone(UTC).date())
    return {**summary,'observed_at':record['observed_at'],'expires_at':record['expires_at'],
            'coverage':deepcopy(record['coverage']),'reports':[r.model_dump(mode='json') for r in reports],
            'context_hash':signature(target.context),'cache_hit':True}
