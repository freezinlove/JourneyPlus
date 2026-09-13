import pytest
from journeyplus.agent.report_pages import list_report_urls,parse_report_detail


def page(body,label='Match'):
    return f'<article><h1>From A Gold to B Gold</h1><div class="result-box"><span>{label}</span></div><div class="instructions">{body}</div><dl><dt>Submitted</dt><dd>2026-09-01</dd></dl></article>'


def test_list_discovers_links_but_never_counts_summary_as_report():
    html='<div><h4 id="report-list-to">Obtaining</h4><a href="/report/1">Match</a><a href="/report/1?tracking=x">Match</a></div>'
    assert list_report_urls(html,'https://statusmatcher.com/company/b')==['https://statusmatcher.com/report/1']
    with pytest.raises(ValueError):parse_report_detail(html,'https://statusmatcher.com/report/1')


def test_detail_preserves_label_and_full_body_without_inferred_outcome():
    body='I was offered a challenge and must fly four segments.'
    report=parse_report_detail(page(body),'https://statusmatcher.com/report/1')
    assert report.reported_label=='MATCH' and report.text==body
    assert report.application_at is None and report.submitted_at=='2026-09-01'
    assert 'normalized_outcome' not in type(report).model_fields
    long_body='Please complete identity verification. '*40+'Finally, my match was approved.'
    report=parse_report_detail(page(long_body),'https://statusmatcher.com/report/2')
    assert report.text==long_body and report.text.endswith('my match was approved.')


def test_parser_preserves_names_without_requiring_database_identities():
    report=parse_report_detail(page('I uploaded a screenshot.'),'https://statusmatcher.com/report/3')
    assert report.original_from=='A Gold' and report.original_to=='B Gold'
    assert report.text=='I uploaded a screenshot.' and report.reported_label=='MATCH'
    assert 'from_program_ref' not in type(report).model_fields


def test_candidate_selection_prefers_relevant_recent_directions_without_inventing_dates():
    from datetime import date
    from tests.test_step_observations import target
    from journeyplus.agent.report_pages import select_report_candidates
    identities={'a gold':{'program_ref':'A'},'b gold':{'program_ref':'B'},'c gold':{'program_ref':'C'}}
    candidates=[{'url':str(i),'direction':direction,'submitted':stamp} for i,direction,stamp in [
        (1,'A Gold to B Gold','2020-01-01'),(2,'C Gold to B Gold','2026-09-01'),
        (3,'A Gold to B Gold',None),(4,'A Gold to B Gold','2026-08-01'),(5,'A Gold to B Gold','2030-01-01')]]
    assert [c['url'] for c in select_report_candidates(candidates,target(),identities,date(2026,9,6))]==['4','3','1']
