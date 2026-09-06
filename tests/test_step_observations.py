from datetime import date
import pytest
from journeyplus.agent.step_observations import ResearchTarget,ReportObservation,comparability,report_window,summarize_step


def target():
    return ResearchTarget(step_ref='s',option_version_ref='o',activity_version_ref='v',edition_ref='round2',
        from_program_ref='A',from_tier_ref='A-gold',to_program_ref='B',to_tier_ref='B-gold',method='MATCH',context={'source_acquisition':'EARNED'})


def report(**updates):
    return ReportObservation.model_validate({'report_ref':'123','url':'https://statusmatcher.com/report/123',
        'from_program_ref':'A','from_tier_ref':'A-gold','to_program_ref':'B','to_tier_ref':'B-gold','method':'MATCH','edition_ref':'round2',
        'context':{'source_acquisition':'EARNED'},'normalized_outcome':'DIRECT_MATCH','evidence_excerpt':'My application was approved.',**updates})


def test_same_program_is_not_same_tier_edition_or_source_acquisition():
    assert comparability(target(),report())['state']=='EXACT'
    assert comparability(target(),report(edition_ref=None))['state']=='PARTIAL'
    assert comparability(target(),report(to_tier_ref='B-silver'))['state']=='INCOMPARABLE'
    assert comparability(target(),report(context={'source_acquisition':'MATCHED'}))['state']=='INCOMPARABLE'


def test_submission_date_does_not_become_recent_application_date():
    today=date(2026,9,6)
    assert report_window(report(submitted_at={'precision':'DATE','date':'2026-09-01'}),today)=='RECENT_SUBMISSION_APPLICATION_UNKNOWN'
    assert report_window(report(application_at={'precision':'DATE','date':'2025-09-06'}),today)=='APPLICATION_12M'
    assert report_window(report(application_at={'precision':'DATE','date':'2025-09-05'}),today)=='APPLICATION_12_TO_24M'
    assert report_window(report(application_at={'precision':'MONTH','month':'2026-09'}),today)=='APPLICATION_DATE_UNKNOWN'


def test_unknown_outcomes_and_labels_are_not_in_known_denominator():
    records=[report(),report(report_ref='124',url='https://statusmatcher.com/report/124',evidence_excerpt=None,reported_label='MATCH'),
             report(report_ref='125',url='https://statusmatcher.com/report/125',normalized_outcome='UNKNOWN')]
    result=summarize_step(target(),records+[records[0]],today=date(2026,9,6))
    count=result['windows']['APPLICATION_DATE_UNKNOWN']
    assert count['known_outcome_count']==1 and count['unknown_count']==2
    assert count['exact_counts']=={'DIRECT_MATCH':1}
    assert len(result['observations'])==3


def test_report_url_drops_tracking_and_rejects_company_summaries():
    assert report(url='https://statusmatcher.com/report/123?tracking=one#text').url=='https://statusmatcher.com/report/123'
    with pytest.raises(ValueError):report(url='https://statusmatcher.com/company/example')


def test_conflicting_duplicate_report_does_not_select_first_success():
    records=[report(),report(normalized_outcome='DENIED',evidence_excerpt='Denied.')]
    first=summarize_step(target(),records,today=date(2026,9,6))
    assert first==summarize_step(target(),list(reversed(records)),today=date(2026,9,6))
    assert first['conflict_count']==1
    assert first['windows']['APPLICATION_DATE_UNKNOWN']['known_outcome_count']==0
    assert first['windows']['APPLICATION_DATE_UNKNOWN']['unknown_count']==1


def test_residency_comparability_uses_same_alias_rules_as_routes():
    context={'source_acquisition':'EARNED','residency':'CA'}
    scoped=target().model_copy(update={'context':context})
    assert comparability(scoped,report(context={**context,'residency':'加拿大'}))['state']=='EXACT'
    ambiguous=comparability(scoped,report(context={**context,'residency':'Americas'}))
    assert ambiguous['state']=='PARTIAL' and ambiguous['missing']==['residency']
