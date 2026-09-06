import pytest
from journeyplus.agent.report_pages import list_report_urls,parse_report_detail


def page(body,label='Match'):
    return f'<article><h1>From A Gold to B Gold</h1><div class="result-box"><span>{label}</span></div><div class="instructions">{body}</div><dl><dt>Submitted</dt><dd>2026-09-01</dd></dl></article>'


def test_list_discovers_links_but_never_counts_summary_as_report():
    html='<div><h4 id="report-list-to">Obtaining</h4><a href="/report/1">Match</a><a href="/report/1?tracking=x">Match</a></div>'
    assert list_report_urls(html,'https://statusmatcher.com/company/b')==['https://statusmatcher.com/report/1']
    with pytest.raises(ValueError):parse_report_detail(html,'https://statusmatcher.com/report/1',{})


def test_detail_body_overrides_match_label_and_does_not_infer_dates_or_edition():
    report=parse_report_detail(page('I was offered a challenge and must fly four segments.'),'https://statusmatcher.com/report/1',{})
    assert report.reported_label=='MATCH' and report.normalized_outcome=='CHALLENGE'
    assert report.application_at is None and report.submitted_at is not None
    assert report.edition_ref is None and report.from_tier_ref is None
    contradictory=parse_report_detail(page('My application was approved but my request denied.'),'https://statusmatcher.com/report/2',{})
    assert contradictory.normalized_outcome=='UNKNOWN'


def test_label_alone_and_unmatched_identity_remain_unknown():
    report=parse_report_detail(page('I uploaded a screenshot.'),'https://statusmatcher.com/report/3',{'a gold':{'program_ref':'a','tier_ref':'gold'}})
    assert report.normalized_outcome=='UNKNOWN' and report.from_program_ref=='a'
    assert report.to_program_ref is None


def test_candidate_selection_prefers_relevant_recent_directions_without_inventing_dates():
    from datetime import date
    from tests.test_step_observations import target
    from journeyplus.agent.report_pages import select_report_candidates
    identities={'a gold':{'program_ref':'A'},'b gold':{'program_ref':'B'},'c gold':{'program_ref':'C'}}
    candidates=[{'url':str(i),'direction':direction,'submitted':stamp} for i,direction,stamp in [
        (1,'A Gold to B Gold','2020-01-01'),(2,'C Gold to B Gold','2026-09-01'),
        (3,'A Gold to B Gold',None),(4,'A Gold to B Gold','2026-08-01'),(5,'A Gold to B Gold','2030-01-01')]]
    assert [c['url'] for c in select_report_candidates(candidates,target(),identities,date(2026,9,6))]==['4','3','1']
