from datetime import datetime,UTC,timedelta
import httpx
from tests.test_step_observations import target
from tests.test_report_pages import page
from journeyplus.agent.step_research import StepResearchService,ResearchRun


def test_dual_gate_performs_no_http():
    def fail(request):raise AssertionError('Unrequested network')
    client=httpx.Client(transport=httpx.MockTransport(fail))
    for enabled,requested,status in [(False,True,'DISABLED'),(True,False,'NOT_REQUESTED')]:
        result=StepResearchService(enabled=enabled,client=client).research_steps([target()],{},user_requested=requested,workspace_expires_at=datetime.now(UTC)+timedelta(hours=1))
        assert result['status']==status and result['http_requests']==0


def test_detail_only_observations_survive_later_page_failure_and_cache_without_html():
    calls=[]
    def response(request):
        calls.append(str(request.url))
        if request.url.path=='/report/1':return httpx.Response(200,text=page('My application was approved.'))
        if request.url.query:return httpx.Response(503)
        return httpx.Response(200,text='<div><h4 id="report-list-to">Reports</h4><a href="/report/1">Match</a></div>')
    service=StepResearchService(enabled=True,client=httpx.Client(transport=httpx.MockTransport(response)),
        companies={'B':{'verified_url':'https://statusmatcher.com/company/b','verified_at':'2026-09-06'}},
        identities={'a gold':{'program_ref':'A','tier_ref':'A-gold'},'b gold':{'program_ref':'B','tier_ref':'B-gold'}})
    state={};kwargs=dict(user_requested=True,workspace_expires_at=datetime.now(UTC)+timedelta(hours=1))
    result=service.research_steps([target()],state,**kwargs)
    assert result['status']=='PARTIAL' and result['http_requests']==3
    observation=result['steps'][0]
    assert observation['coverage']['stopped_reason']=='HTTP_ERROR'
    assert observation['windows']['RECENT_SUBMISSION_APPLICATION_UNKNOWN']['partial_counts']=={'DIRECT_MATCH':1}
    assert '<article>' not in str(state) and 'instructions' not in str(state)
    changed=target().model_copy(update={'context':{'source_acquisition':'MATCHED'}})
    again=service.research_steps([changed],state,**kwargs)
    assert again['http_requests']==0 and len(calls)==3


def test_research_packet_survives_model_allowlist_without_full_report_dump():
    from journeyplus.agent.step_research import research_decision_packet,research_answer_text
    from journeyplus.knowledge.packets import decision_packet
    result={'status':'PARTIAL','http_requests':3,'steps':[{'step_ref':'s','status':'PARTIAL',
        'windows':{'APPLICATION_DATE_UNKNOWN':{'exact_counts':{},'partial_counts':{'DIRECT_MATCH':1},'unknown_count':2}},
        'reports':[{'report_ref':str(i),'url':f'https://statusmatcher.com/report/{i}','normalized_outcome':'UNKNOWN','evidence_excerpt':'Unknown outcome.'} for i in range(8)]}]}
    packet=decision_packet(research_decision_packet(result))
    observation=packet['data']['step_observations'][0]
    assert len(observation['citations'])==3 and 'reports' not in observation
    assert packet['coverage']['http_requests']==3
    answer=research_answer_text([packet],{'s':{'from':'A Gold','to':'B Gold'}})
    assert 'A Gold → B Gold' in answer and '部分可比直接匹配 1 例' in answer and '结果未知 2 例' in answer
    assert '不代表真实审批成功率' in answer


def test_two_lists_are_read_before_eight_detail_limit():
    calls=[]
    def response(request):
        calls.append(str(request.url))
        if request.url.path.startswith('/report/'):
            return httpx.Response(200,text=page('My application was approved.'))
        start=10 if request.url.query else 0
        links=''.join(f'<a href="/report/{i}">Match</a>' for i in range(start,start+10))
        return httpx.Response(200,text='<div><h4 id="report-list-to">Reports</h4>'+links+'</div>')
    service=StepResearchService(enabled=True,client=httpx.Client(transport=httpx.MockTransport(response)),
        companies={'B':{'verified_url':'https://statusmatcher.com/company/b','verified_at':'2026-09-06'}},
        identities={'a gold':{'program_ref':'A','tier_ref':'A-gold'},'b gold':{'program_ref':'B','tier_ref':'B-gold'}})
    result=service.research_steps([target()],{},user_requested=True,workspace_expires_at=datetime.now(UTC)+timedelta(hours=1))
    assert '/company/' in calls[0] and '/company/' in calls[1]
    assert len(calls)==10 and result['coverage']['detail_count']==8
    assert result['status']=='PARTIAL' and result['steps'][0]['coverage']['stopped_reason']=='REPORT_BUDGET'


def test_unavailable_second_step_does_not_erase_first_step_observations():
    def response(request):
        if request.url.path.startswith('/report/'):return httpx.Response(200,text=page('My application was approved.'))
        return httpx.Response(200,text='<div><h4 id="report-list-to">Reports</h4>'+('' if request.url.query else '<a href="/report/1">Match</a>')+'</div>')
    service=StepResearchService(enabled=True,client=httpx.Client(transport=httpx.MockTransport(response)),
        companies={'B':{'verified_url':'https://statusmatcher.com/company/b','verified_at':'2026-09-06'}},
        identities={'a gold':{'program_ref':'A','tier_ref':'A-gold'},'b gold':{'program_ref':'B','tier_ref':'B-gold'}})
    result=service.research_steps([target(),target().model_copy(update={'step_ref':'next','to_program_ref':'C'})],{},
        user_requested=True,workspace_expires_at=datetime.now(UTC)+timedelta(hours=1))
    assert result['status']=='PARTIAL' and result['http_requests']==3
    assert result['steps'][0]['status']=='COMPLETED' and len(result['steps'][0]['reports'])==1
    assert result['steps'][1]['status']=='UNAVAILABLE'
