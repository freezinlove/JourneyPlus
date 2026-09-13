import asyncio
import pytest
from journeyplus.agent.services.research import parse_page
from journeyplus.agent.services.web_projection import page_excerpt
from journeyplus.agent.tools.contracts import WebReadInput, WorkspaceReadInput, DisplayInput
from journeyplus.agent.tools.research import read as read_web
from journeyplus.agent.services.workspace import read as read_workspace
from journeyplus.agent.services.display import present
from tests.test_harness_tools import context
from tests.test_report_pages import page


def snapshot(html, url='https://statusmatcher.com/company/kenya-airways'):
    return parse_page(url,url,html.encode(),html,12000,False)[0]


class SnapshotReader:
    def __init__(self, raw):self.raw=raw;self.calls=0
    async def page(self,*args):self.calls+=1;return self.raw


def read_snapshot(ctx,raw):
    ctx.services['research']=SnapshotReader(raw)
    return asyncio.run(read_web(WebReadInput(url=raw['url']),ctx))


def test_company_cleaning_keeps_facts_directions_and_each_website_next_link():
    html='''<body><nav>Navigation</nav><div class="col-lg-9"><section>
    <h3>Kenya Airways</h3><p>34 of 58 reports (59%)</p>
    <a href="https://kenya-airways.statusmatch.com">Apply</a><p>Contact: asante@example.com</p>
    <div class="ad-container">Discover more <a href="https://ads.example">Buy now</a></div>
    <div><h4 id="report-list-to">Obtaining Asante</h4><p>Cathay to Asante</p>
    <a href="/report/1">Match</a><a href="?page-to=1#report-list-to">Next Page</a></div>
    <h4 id="new-report">Add New Status Match Report</h4>
    <form><label>From Program</label><select><option>Other Club</option></select>
    <p>Please include how you contacted the firm</p></form>
    <div><h4 id="report-list-from">Leveraging Asante</h4><p>Asante to Turkish</p>
    <a href="/report/2">Deny</a><a href="?page-from=1#report-list-from">Next Page</a></div>
    </section></div><div class="col-lg-3">User Management</div><footer>Copyright</footer></body>'''
    raw=snapshot(html)
    data,coverage,cursor=page_excerpt(raw,'artifact:page',WebReadInput(url=raw['url']))
    for keep in ('34 of 58','59%','Cathay to Asante','Asante to Turkish','asante@example.com'):
        assert keep in data['text']
    for noise in ('Discover more','Buy now','From Program','Other Club','Please include','Add New','User Management','Copyright','Navigation'):
        assert noise not in data['text']
    urls=[link['url'] for link in data['links']]
    assert 'https://kenya-airways.statusmatch.com' in urls
    assert any('page-to=1' in url for url in urls) and any('page-from=1' in url for url in urls)
    assert not any('ads.example' in url for url in urls)
    assert raw['raw_html']==html and coverage['complete'] and not cursor


def test_cleaning_is_site_specific_and_applies_to_explicit_sections():
    html='<main><h3>Reports</h3><p>Useful report</p><form><p>Form help</p></form></main>'
    raw=snapshot(html)
    data,_,_=page_excerpt(raw,'artifact:p',WebReadInput(url=raw['url'],sections=['Reports']))
    assert 'Useful report' in data['text'] and 'Form help' not in data['text']
    other=snapshot(html,'https://example.com/article')
    data,_,_=page_excerpt(other,'artifact:p',WebReadInput(url=other['url']))
    assert 'Form help' in data['text']  # No new generic web policy.


def test_long_cleaned_web_body_resumes_without_losing_ending():
    body='会员资料说明。 '*1800+'Finally approved after 24 hours.'
    raw=snapshot(page(body),'https://statusmatcher.com/report/1')
    args=WebReadInput(url=raw['url'])
    start=links=0;parts=[]
    while True:
        data,_,cursor=page_excerpt(raw,'artifact:p',args,start,links)
        parts.append(data['text'])
        if not cursor:break
        _,start,links,_=cursor.split('|');start=int(start);links=int(links)
    assert body in ''.join(parts)
    assert ''.join(parts).count('会员资料说明。')==1800


def test_full_report_survives_projection_workspace_pagination_and_card_detail(session_factory):
    _,store,w,ctx=context(session_factory)
    # The default parser must not open the knowledge database to read a report.
    class NoKnowledge:
        def read(self):raise AssertionError('Unrequested catalog lookup')
    ctx.services['knowledge']=NoKnowledge()
    body='Verification details. '*900+'Finally, my application succeeded after 24 hours.'
    raw=snapshot(page(body),'https://statusmatcher.com/report/123')
    result=read_snapshot(ctx,raw)
    row=result.data['report']
    assert result.status=='PARTIAL' and result.next_cursor
    assert 'normalized_outcome' not in row and 'comparisons' not in result.data
    assert 'from_tier_ref' not in row and 'notes' not in row
    assert row['reported_label']=='MATCH' and row['body_complete']
    report_ref=result.data['report_ref']
    assert store.artifacts.read(w['id'],report_ref)['payload']['text']==body
    parts=[];cursor=None
    while True:
        read=asyncio.run(read_workspace(WorkspaceReadInput(kind='artifact',refs=[report_ref],cursor=cursor),ctx))
        parts.extend(s['value'] for s in read.data.get('sections',[]) if s['path']=='/text')
        cursor=read.next_cursor
        if not cursor:break
    assert ''.join(parts)==body
    shown=asyncio.run(present(DisplayInput(blocks=[{'type':'experience','object_refs':[report_ref]}]),ctx))
    payload=store.artifacts.read(w['id'],shown.data['presentation_ref'])['payload']
    assert payload['blocks'][0]['payload']['objects'][0]['data']['text']==body


def test_report_without_website_label_does_not_invent_one(session_factory):
    _,store,w,ctx=context(session_factory)
    html='<article><h1>From A Gold to B Gold</h1><div class="instructions">My application was approved.</div></article>'
    result=read_snapshot(ctx,snapshot(html,'https://statusmatcher.com/report/2'))
    row=result.data['report']
    assert 'reported_label' not in row and 'normalized_outcome' not in row
    assert result.data['text']=='My application was approved.' and result.status=='OK'


def test_model_can_present_page_directly_without_extra_parse_call(session_factory):
    _,store,w,ctx=context(session_factory)
    body='Please verify identity. '*50+'Match confirmed after 24 hours.'
    raw=snapshot(page(body),'https://statusmatcher.com/report/321')
    read=read_snapshot(ctx,raw)
    ref=read.data['page_ref']
    shown=asyncio.run(present(DisplayInput(blocks=[{'type':'experience','object_refs':[ref]}]),ctx))
    payload=store.artifacts.read(w['id'],shown.data['presentation_ref'])['payload']
    obj=payload['blocks'][0]['payload']['objects'][0]
    assert obj['ref']==ref and obj['data']['text']==body
    assert obj['data']['reported_label']=='MATCH' and obj['data']['original_from']=='A Gold'
    assert 'raw_html' not in obj['data']
    assert store.artifacts.read(w['id'],ref)['payload']['raw_html']==raw['raw_html']


def test_report_cursor_reuses_snapshot_and_refresh_keeps_previous_report(session_factory):
    _,store,w,ctx=context(session_factory)
    body='完整申请过程。 '*2200+'Approved at the end.'
    first=read_snapshot(ctx,snapshot(page(body),'https://statusmatcher.com/report/9'))
    reader=ctx.services['research'];parts=[first.data['text']];current=first
    while current.next_cursor:
        current=asyncio.run(read_web(WebReadInput(url=reader.raw['url'],cursor=current.next_cursor),ctx))
        assert current.artifact_refs==first.artifact_refs
        assert current.data['report_ref']==first.data['report_ref']
        assert 'text' not in current.data['report']
        parts.append(current.data['text'])
    assert ''.join(parts)==body and reader.calls==1
    reader.raw=snapshot(page('Updated report.'),reader.raw['url'])
    ctx.call_id='refresh-report'
    fresh=asyncio.run(read_web(WebReadInput(url=reader.raw['url'],refresh=True),ctx))
    assert fresh.data['report_ref']!=first.data['report_ref']
    assert store.artifacts.read(w['id'],first.data['report_ref'])['payload']['text']==body
    assert store.artifacts.read(w['id'],fresh.data['report_ref'])['payload']['text']=='Updated report.'


@pytest.mark.parametrize('url',[
    'https://statusmatcher.com/company/kenya-airways', 'https://example.com/report/9'])
def test_other_pages_do_not_create_reports(session_factory,url):
    _,store,w,ctx=context(session_factory)
    result=read_snapshot(ctx,snapshot(page('Application completed.'),url))
    assert 'report_ref' not in result.data and len(result.artifact_refs)==1


def test_changed_report_layout_keeps_readable_page_without_invented_report(session_factory):
    _,store,w,ctx=context(session_factory)
    result=read_snapshot(ctx,snapshot('<main><p>Readable but changed layout.</p></main>',
                                     'https://statusmatcher.com/report/9'))
    assert result.status=='PARTIAL' and result.data['report_error']
    assert 'Readable but changed layout.' in result.data['text']
    assert 'report_ref' not in result.data


def test_failed_report_save_does_not_publish_half_a_snapshot(session_factory,monkeypatch):
    from sqlalchemy import select,func
    from journeyplus.agent.adapters.models import Artifact
    _,store,w,ctx=context(session_factory)
    original=store.artifacts.put_in
    def fail_report(session,workspace,kind,*args,**kwargs):
        if kind=='REPORT':raise RuntimeError('Report storage failed')
        return original(session,workspace,kind,*args,**kwargs)
    monkeypatch.setattr(store.artifacts,'put_in',fail_report)
    with pytest.raises(RuntimeError,match='Report storage failed'):
        read_snapshot(ctx,snapshot(page('Complete report.'),'https://statusmatcher.com/report/9'))
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Artifact))==0


@pytest.mark.parametrize('kind',['route_graph','comparison'])
@pytest.mark.parametrize('alias',['report_ref','page_ref'])
def test_saved_report_attaches_to_graph_and_comparison_without_parsing(session_factory,monkeypatch,kind,alias):
    from tests.test_knowledge_routes import edge
    from journeyplus.agent.tools.routes import evaluate
    from journeyplus.agent.tools.contracts import RoutesInput
    with session_factory.begin() as session:source,_=edge(session,alternative=True)
    _,store,w,ctx=context(session_factory)
    body='Complete application with requirements and final outcome.'
    report=read_snapshot(ctx,snapshot(page(body),'https://statusmatcher.com/report/9'))
    def no_parse(*args,**kwargs):raise AssertionError('Display must not parse again')
    monkeypatch.setattr('journeyplus.agent.services.research_pages.parse_report_detail',no_parse)
    ctx.call_id='routes'
    routes=asyncio.run(evaluate(RoutesInput(operation='search',query={
        'sources':{'mode':'explicit','identities':[{'ref':'tier:'+str(source)}]}}),ctx))
    ctx.call_id='display'
    shown=asyncio.run(present(DisplayInput(blocks=[{'type':kind,
        'object_refs':routes.data['route_refs'][:2],
        'research_refs':[report.data[alias]]}]),ctx))
    block=store.artifacts.read(w['id'],shown.data['presentation_ref'])['payload']['blocks'][0]
    attached=block['payload']['research'][0]
    assert attached['ref']==report.data['report_ref']
    assert attached['data']['text']==body
    assert attached['bindings'][0]['compatible_steps']
    assert store.artifacts.read(w['id'],attached['ref'])['payload']['text']==body
