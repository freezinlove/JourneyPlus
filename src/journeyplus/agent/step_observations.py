"""Minimal workspace-only experience records and conservative comparability."""
from calendar import monthrange
from datetime import date
from typing import Literal,Annotated
from urllib.parse import urlsplit,urlunsplit

from pydantic import Field,field_validator
from journeyplus.contracts import StrictModel
from journeyplus.knowledge.contracts import Temporal


class ResearchTarget(StrictModel):
    step_ref:str
    option_version_ref:str
    activity_version_ref:str
    edition_ref:str
    from_program_ref:str|None=None
    from_tier_ref:str|None=None
    to_program_ref:str
    to_tier_ref:str
    method:Literal['MATCH','CHALLENGE','OTHER']
    context:dict[Literal['source_acquisition','residency','prior_participation'],str]=Field(default_factory=dict)


class ReportObservation(StrictModel):
    schema_version:Literal[1]=1
    report_ref:str=Field(min_length=1,max_length=100)
    url:str=Field(max_length=2048)
    submitted_at:Temporal|None=None
    application_at:Temporal|None=None
    from_program_ref:str|None=None
    from_tier_ref:str|None=None
    to_program_ref:str|None=None
    to_tier_ref:str|None=None
    original_from:str|None=Field(default=None,max_length=200)
    original_to:str|None=Field(default=None,max_length=200)
    method:Literal['MATCH','CHALLENGE','OTHER']|None=None
    edition_ref:str|None=None
    reported_label:Literal['MATCH','CHALLENGE','DENY','OTHER']|None=None
    normalized_outcome:Literal['DIRECT_MATCH','CHALLENGE','DENIED','UNKNOWN']='UNKNOWN'
    context:dict[Literal['source_acquisition','residency','prior_participation'],str]=Field(default_factory=dict)
    notes:list[Annotated[str,Field(max_length=300)]]=Field(default_factory=list,max_length=5)
    evidence_excerpt:str|None=Field(default=None,max_length=600)

    @field_validator('url')
    @classmethod
    def report_url(cls,value):
        from journeyplus.agent.research_http import permitted_url
        parsed=urlsplit(permitted_url(value))
        if not parsed.path.startswith('/report/'):raise ValueError('A company list is not a report detail')
        return urlunsplit((parsed.scheme,parsed.netloc,parsed.path.rstrip('/'),'',''))


def comparability(target:ResearchTarget,report:ReportObservation):
    missing=[];mismatch=[]
    for field in ('from_program_ref','from_tier_ref','to_program_ref','to_tier_ref','method','edition_ref'):
        wanted=getattr(target,field);actual=getattr(report,field)
        if wanted is None:
            missing.append(field)
        elif actual is None:missing.append(field)
        elif wanted!=actual:mismatch.append(field)
    for field,wanted in target.context.items():
        if wanted=='UNKNOWN':continue
        actual=report.context.get(field)
        if actual in {None,'UNKNOWN'}:missing.append(field)
        elif field=='residency':
            from journeyplus.knowledge.countries import country_equal
            equal=country_equal(actual,wanted)
            if equal is None:missing.append(field)
            elif not equal:mismatch.append(field)
        elif actual!=wanted:mismatch.append(field)
    return {'state':'INCOMPARABLE' if mismatch else 'PARTIAL' if missing else 'EXACT',
            'missing':missing,'mismatches':mismatch}


def months_ago(today,months):
    year,month=divmod(today.year*12+today.month-1-months,12)
    return date(year,month+1,min(today.day,monthrange(year,month+1)[1]))


def exact_date(value):
    if value is None:return None
    if value.precision=='DATE':return value.date
    if value.precision=='INSTANT':return value.instant.date()
    return None


def report_window(report:ReportObservation,today:date):
    applied=exact_date(report.application_at)
    if applied:
        if applied>today:return 'FUTURE_DATE'
        if applied>=months_ago(today,12):return 'APPLICATION_12M'
        if applied>=months_ago(today,24):return 'APPLICATION_12_TO_24M'
        return 'HISTORICAL_APPLICATION'
    submitted=exact_date(report.submitted_at)
    if submitted and submitted>today:return 'FUTURE_DATE'
    if submitted and submitted>=months_ago(today,12):return 'RECENT_SUBMISSION_APPLICATION_UNKNOWN'
    return 'APPLICATION_DATE_UNKNOWN'


def summarize_step(target:ResearchTarget,reports:list[ReportObservation],*,today:date):
    windows={};observations=[];incomparable=0;conflicts=0
    groups=[]
    for report in reports:
        keys={('id',report.report_ref),('url',report.url)}
        overlapping=[group for group in groups if group[0]&keys]
        members=[report]
        for group in overlapping:
            keys.update(group[0]);members.extend(group[1]);groups.remove(group)
        groups.append((keys,members))
    from journeyplus.knowledge.publication import signature
    for _,members in sorted(groups,key=lambda group:sorted(group[0])):
        report=min(members,key=lambda r:(r.report_ref,r.url))
        substantive={signature(r.model_dump(mode='json',exclude={'report_ref','url','notes','evidence_excerpt','original_from','original_to'})) for r in members}
        if len(substantive)>1:
            conflicts+=1
            observations.append({'report_ref':report.report_ref,'comparability':{'state':'PARTIAL','missing':['conflicting_report_versions'],'mismatches':[]},'window':'APPLICATION_DATE_UNKNOWN','conflict':True})
            counts=windows.setdefault('APPLICATION_DATE_UNKNOWN',{'exact_counts':{},'partial_counts':{},'unknown_count':0,'known_outcome_count':0,'report_refs':[]})
            counts['unknown_count']+=1;counts['report_refs'].append(report.report_ref)
            continue
        comparison=comparability(target,report);window=report_window(report,today)
        observations.append({'report_ref':report.report_ref,'comparability':comparison,'window':window})
        if comparison['state']=='INCOMPARABLE' or window=='FUTURE_DATE':incomparable+=1;continue
        counts=windows.setdefault(window,{'exact_counts':{},'partial_counts':{},'unknown_count':0,'known_outcome_count':0,'report_refs':[]})
        counts['report_refs'].append(report.report_ref)
        # A page label alone never becomes a verified result.
        outcome=report.normalized_outcome if report.evidence_excerpt else 'UNKNOWN'
        if outcome=='UNKNOWN':counts['unknown_count']+=1;continue
        bucket=counts['exact_counts' if comparison['state']=='EXACT' else 'partial_counts']
        bucket[outcome]=bucket.get(outcome,0)+1;counts['known_outcome_count']+=1
    return {'step_ref':target.step_ref,'activity_version_ref':target.activity_version_ref,
            'windows':windows,'incomparable_count':incomparable,'conflict_count':conflicts,'observations':observations,
            'limitations':['用户自报案例不代表真实审批概率。','申请日期未知与近期提交分开统计。','不同步骤不混合计数或连乘概率。']}
