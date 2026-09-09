import asyncio
from time import monotonic
from uuid import UUID, uuid4
import pytest
from journeyplus.agent.composition import compose_business
from journeyplus.agent.harness.contracts import ExecutionContext
from journeyplus.agent.tools.contracts import RoutesInput,DisplayInput
from journeyplus.agent.tools.routes import evaluate,merge_query
from journeyplus.agent.tools.presentation import present
from journeyplus.knowledge.models import MembershipProgram,MembershipTier
from tests.test_harness_runtime import FakeModel
from tests.test_knowledge_routes import edge
from sqlalchemy import select


def context(factory):
    runtime,store=compose_business(factory,FakeModel([]));w=store.create()
    return runtime,store,w,ExecutionContext(w['id'],str(uuid4()),'call','local-user',monotonic()+60,asyncio.Event(),store.artifacts,store,runtime.services)


def test_identity_exact_and_ambiguity_never_guess(session_factory):
    runtime,store,w,ctx=context(session_factory)
    with session_factory.begin() as s:
        p=MembershipProgram(canonical_key='sample',display_name='Sample',category='AIRLINE');s.add(p);s.flush()
        s.add_all([MembershipTier(program_id=p.id,canonical_key='gold',display_name='Gold'),MembershipTier(program_id=p.id,canonical_key='silver',display_name='Silver')])
    with runtime.services['knowledge'].read() as s:
        service=runtime.services['identities']
        assert service.resolve(s,{'program_name':'Sample','tier_name':'Gold'},require_tier=True)['status']=='OK'
        assert service.resolve(s,{'program_name':'Sample'},require_tier=True)['status']=='AMBIGUOUS'
        assert service.resolve(s,{'program_name':'Sam'},require_tier=True)['status']=='NOT_FOUND'


def test_whole_program_phrase_returns_candidates_without_binding(session_factory):
    from journeyplus.agent.services.identities import IdentityService
    with session_factory.begin() as session:
        session.add_all([MembershipProgram(canonical_key='one',display_name='Example Airways Club',category='AIRLINE'),
                         MembershipProgram(canonical_key='two',display_name='Example Hotel Club',category='HOTEL')])
    with session_factory() as session:
        service=IdentityService()
        result=service.resolve(session,{'program_name':'Example Airways'})
        assert result['status']=='NOT_FOUND'
        assert result['candidates'][0]['program_name']=='Example Airways Club'
        assert result['candidates'][0]['match_basis']=='whole_phrase_candidate'
        assert service.resolve(session,{'ref':result['candidates'][0]['ref']})['status']=='OK'
        assert len(service.resolve(session,{'program_name':'Example'})['candidates'])==2
        assert service.resolve(session,{'program_name':'Exam'})['status']=='NOT_FOUND'


def test_material_search_keeps_mapping_conditions_beyond_name_chunk():
    from journeyplus.agent.services.artifact_views import view
    mapping={'from_program':'Example Source','prices':{'amount':'49','currency':'USD'},
             'conditions':['condition '+str(i)+'x'*200 for i in range(30)]}
    records=[{'ref':'artifact:material','payload':{'options':[mapping],
              'sections':{'mapping-a':{'activity_ref':'activity','version_ref':'version','mapping':mapping},
                          'mapping-b':{'mapping':{'from_program':'Other Source','prices':{'amount':'999'}}}}}}]
    first=view(records,query='Example Source');parts=first['sections'];cursor=first['next_cursor']
    while cursor:
        page=view(records,query='Example Source',cursor=cursor);parts+=page['sections'];cursor=page['next_cursor']
    import json
    encoded=json.dumps(parts)
    assert '49' in encoded and 'condition 29' in encoded
    assert 'Other Source' not in encoded and '999' not in encoded
    condition_parts=[part for part in parts if '/conditions/' in part['path']]
    assert condition_parts
    for part in condition_parts:
        fields={key:value for parent in part['ancestors'] for key,value in parent['fields'].items()}
        assert fields['version_ref']=='version'
        assert fields['activity_ref']=='activity'
        assert fields['from_program']=='Example Source'
    assert all(p['path'].startswith('/sections/mapping-a') for p in parts)


def test_query_patch_replaces_target_and_sources():
    base={'sources':{'mode':'explicit','identities':[{'program_name':'A','tier_name':'Gold'}]},'target':{'program_name':'B','tier_name':'Gold'}}
    value=merge_query(base,{'target':{'program_name':'C'}})
    assert value.target.tier_name is None
    assert value.sources.identities[0].program_name=='A'
    assert merge_query(base,{'target':None}).target is None
    with pytest.raises(ValueError):merge_query(base,{'last_query':{}})


def test_route_artifact_preserves_explicit_inputs_and_display_order(session_factory):
    with session_factory.begin() as s:source,target=edge(s,alternative=True)
    runtime,store,w,ctx=context(session_factory)
    result=asyncio.run(evaluate(RoutesInput(operation='search',query={'sources':{'mode':'explicit','identities':[{'ref':'tier:'+str(source)}]}}),ctx))
    assert result.effective_input['use_saved_holdings'] is False
    refs=result.data['route_refs'][:2]
    assert len(refs)==2
    shown=asyncio.run(present(DisplayInput(blocks=[{'type':'route_graph','object_refs':list(reversed(refs))}]),ctx))
    assert shown.data['blocks'][0]['ordered_refs']==list(reversed(refs))
    original=store.artifacts.read(w['id'],shown.data['presentation_ref'])['payload']
    assert original['blocks'][0]['payload']['objects'][0]['ref']==refs[1]
    expected=[{'object_ref':obj['ref'],'url':brief['url'],'version_ref':brief['version_ref']}
              for obj in original['blocks'][0]['payload']['objects'] for brief in obj['data']['brief_links']]
    assert expected and shown.data['blocks'][0]['links']==expected
    again=asyncio.run(present(DisplayInput(blocks=[{'type':'route_graph','object_refs':list(reversed(refs))}]),ctx))
    assert again.data['presentation_ref']==shown.data['presentation_ref']
    inspected=asyncio.run(evaluate(RoutesInput(operation='inspect',route_refs=refs[:1]),ctx))
    scope=inspected.data['retrieval_scope']
    assert scope['new_search_performed'] is False
    assert scope['origin_queries']==[{'query_ref':result.data['query_ref'],'effective_query':result.data['effective_query']}]
    assert scope['origin_queries'][0]['effective_query']['target'] is None
    assert inspected.data['candidates'][0]['to']  # A concrete output target does not narrow the original query.


def test_route_object_rejects_wrong_kind_root_and_missing_steps(session_factory):
    from journeyplus.agent.services.route_objects import RouteObject
    _,store,w,_=context(session_factory)
    payload={'routes':{'r':{'step_refs':['s']}},'steps':{'s':{'version_ref':'v'}}}
    wrong=store.artifacts.put(w['id'],'NOTE',payload)
    with pytest.raises(ValueError):RouteObject.read(store.artifacts,w['id'],wrong+'#route:r')
    valid=store.artifacts.put(w['id'],'ROUTES',payload)
    with pytest.raises(ValueError):RouteObject.read(store.artifacts,w['id'],valid)
    other=store.create()
    with pytest.raises(LookupError):RouteObject.read(store.artifacts,other['id'],valid+'#route:r')
    damaged=store.artifacts.put(w['id'],'ROUTES',{'routes':payload['routes'],'steps':{}})
    with pytest.raises(ValueError):RouteObject.read(store.artifacts,w['id'],damaged+'#route:r')


def test_catalog_combined_program_tier_and_material_sections(session_factory):
    from journeyplus.agent.tools.contracts import CatalogInput,ActivityInput
    from journeyplus.agent.tools.knowledge import catalog,activity
    with session_factory.begin() as s:source,target=edge(s,alternative=True)
    runtime,store,w,ctx=context(session_factory)
    with session_factory() as s:
        tier=s.get(MembershipTier,source);program=s.get(MembershipProgram,tier.program_id)
        query=program.display_name+' '+tier.display_name
    found=asyncio.run(catalog(CatalogInput(query=query),ctx))
    assert any(item['ref']=='tier:'+str(source) for item in found.data['candidates'])
    from journeyplus.knowledge.models import Activity
    with session_factory() as s:identity=s.scalar(select(Activity.id))
    result=asyncio.run(activity(ActivityInput(selector={'ref':'activity:'+str(identity)},view='detail'),ctx))
    item=result.data['activities'][0]
    section=item['options'][0]['section_ref']
    expanded=asyncio.run(activity(ActivityInput(selector={'ref':item['ref']},view='detail',section_refs=[section]),ctx))
    assert expanded.data['sections'][0]['payload']['version_ref']==item['version_ref']
    assert expanded.data['sections'][0]['payload']['option']['ref']==item['options'][0]['ref']
    another=store.create()
    with pytest.raises(LookupError):store.artifacts.read(another['id'],section)


def test_catalog_cursor_rejects_changed_input_and_keeps_snapshot(session_factory):
    from journeyplus.agent.tools.contracts import CatalogInput
    from journeyplus.agent.tools.knowledge import catalog
    runtime,store,w,ctx=context(session_factory)
    with session_factory.begin() as s:
        s.add_all([MembershipProgram(canonical_key='sample-'+str(i),display_name='Sample '+str(i),category='AIRLINE') for i in range(3)])
    first=asyncio.run(catalog(CatalogInput(query='Sample',limit=1),ctx))
    assert first.next_cursor
    with session_factory.begin() as s:s.add(MembershipProgram(canonical_key='sample-new',display_name='Sample new',category='AIRLINE'))
    second=asyncio.run(catalog(CatalogInput(query='Sample',limit=1,cursor=first.next_cursor),ctx))
    assert second.coverage['total']==3
    with pytest.raises(ValueError):asyncio.run(catalog(CatalogInput(query='Changed',cursor=first.next_cursor),ctx))


def test_identity_can_read_scoped_material_without_catalog_receipt(session_factory):
    runtime,store,w,ctx=context(session_factory)
    with session_factory.begin() as s:
        program=MembershipProgram(canonical_key='sample',display_name='Sample',category='AIRLINE');s.add(program);s.flush()
        tier=MembershipTier(program_id=program.id,canonical_key='gold',display_name='Gold');s.add(tier);s.flush();identity=str(tier.id)
    ref=store.artifacts.put(w['id'],'MATERIAL',{'holdings':[{'tier_ref':'tier:'+identity}]})
    with runtime.services['knowledge'].read() as s:
        assert runtime.services['identities'].resolve(s,{'ref':ref},require_tier=True,context=ctx)['tier_ref']=='tier:'+identity
    from dataclasses import replace
    other=store.create()
    with runtime.services['knowledge'].read() as s:
        with pytest.raises(LookupError):runtime.services['identities'].resolve(s,{'ref':ref},context=replace(ctx,workspace_id=other['id']))


def test_oversized_artifact_text_can_be_read_completely_without_reinterpretation(session_factory):
    from journeyplus.agent.services.workspace import read
    from journeyplus.agent.tools.contracts import WorkspaceReadInput
    runtime,store,w,ctx=context(session_factory)
    original='原文😀包含未知费用，不应删掉。'*500
    ref=store.artifacts.put(w['id'],'MATERIAL',{'source_text':original})
    cursor=None;parts=[]
    while True:
        result=asyncio.run(read(WorkspaceReadInput(kind='artifact',refs=[ref],cursor=cursor),ctx))
        for item in result.data['sections']:
            assert item['artifact_ref']==ref and item['path']=='/source_text'
            parts.append(item['value'])
        cursor=result.next_cursor
        if cursor is None:break
    assert ''.join(parts)==original


def test_activity_name_lookup_respects_underlying_catalog_limit(session_factory):
    from journeyplus.agent.tools.contracts import ActivityInput
    from journeyplus.agent.tools.knowledge import activity
    runtime,store,w,ctx=context(session_factory)
    result=asyncio.run(activity(ActivityInput(selector={'query':'unregistered activity'},view='detail'),ctx))
    assert result.status=='EMPTY' and result.error is None


def test_activity_collection_beyond_fifty_is_retrievable_and_details_are_lazy(session_factory,monkeypatch):
    from tests.test_knowledge import fixture_draft
    from journeyplus.knowledge.publication import PublicationService
    from journeyplus.knowledge.reads import ActivityReadService
    from journeyplus.agent.tools.contracts import ActivityInput
    from journeyplus.agent.tools.knowledge import activity
    runtime,store,w,ctx=context(session_factory)
    with session_factory.begin() as s:
        for _ in range(53):
            draft,_,_=fixture_draft(s)
            PublicationService(s).publish(draft)
    reads=[];original=ActivityReadService.detail
    def detail(self,identity,version=None):
        reads.append((identity,version))
        return original(self,identity,version)
    monkeypatch.setattr(ActivityReadService,'detail',detail)
    args=ActivityInput(selector={'query':'示例 B 活动'},limit=10)
    first=asyncio.run(activity(args,ctx))
    assert len(reads)==10 and first.coverage['total']==53
    refs=[x['ref'] for x in first.data['activities']];cursor=first.next_cursor
    while cursor:
        page=asyncio.run(activity(args.model_copy(update={'cursor':cursor}),ctx))
        refs.extend(x['ref'] for x in page.data['activities']);cursor=page.next_cursor
    assert len(refs)==len(set(refs))==53
    assert len(reads)==53 and page.coverage['complete']


def test_bounded_route_pages_advance_by_returned_candidates_without_skipping():
    from journeyplus.agent.tools.routes import result_page
    payload={'route_order':[str(i) for i in range(25)],'routes':{str(i):{'ref':str(i),'step_refs':[str(i)],'from':'Source','to':'Target '+str(i),
             'cost':{'state':'UNKNOWN'},'material_caveats':['Long condition '*40]*6} for i in range(25)}}
    cursor=None;seen=[]
    while True:
        offset=int(cursor.rsplit('|',1)[1]) if cursor else 0
        rows,cursor=result_page(payload,'artifact:root',offset,20)
        seen.extend(row['ref'] for row in rows)
        assert all(row['caveats_truncated'] and row['material_caveat_count']==6 for row in rows)
        # Simulate JSONB's changed object order between the first and later pages.
        payload['routes']=dict(sorted(payload['routes'].items()))
        if not cursor:break
    assert seen==['artifact:root#route:'+str(i) for i in range(25)]


def test_route_detail_preserves_cost_scope_versions_and_complete_caveats():
    from journeyplus.agent.tools.routes import route_summary
    route={'ref':'r','step_refs':['s'],'cost':{'state':'PARTIAL','totals':[{'amount':'0'}],
        'is_proven_free':False,'scope':'Known mandatory charges only'},'material_caveats':['condition A','condition B']}
    steps={'s':{'from':'Source','to':'Target','activity_ref':'activity-a','version_ref':'version-a'}}
    summary=route_summary(route,'artifact:root',steps)
    detail=route_summary(route,'artifact:root',steps,detail=True)
    assert summary['cost']['scope']=='Known mandatory charges only'
    assert summary['cost']['total']=='UNKNOWN'
    assert summary['source_versions']==[{'activity_ref':'activity-a','version_ref':'version-a'}]
    assert summary['caveats_truncated']
    assert not detail['caveats_truncated'] and detail['material_caveats']==route['material_caveats']


def test_route_summary_exposes_actual_intermediate_steps_without_guessing():
    from journeyplus.agent.tools.routes import route_summary
    route={'ref':'r','step_refs':['a','b'],'from':'Start','to':'End'}
    steps={'a':{'from':'Start','to':'Intermediate'},'b':{'from':'Intermediate','to':'End'}}
    result=route_summary(route,'artifact:root',steps)
    assert result['path']==['Start','Intermediate','End']
    assert 'step_refs' not in result
    detail=route_summary(route,'artifact:root',steps,detail=True)
    assert detail['step_refs']==['artifact:root#step:a','artifact:root#step:b']
    assert 'path' not in route


def test_route_partial_zero_is_not_exposed_as_a_free_total():
    from journeyplus.agent.tools.routes import route_summary
    route={'ref':'r','step_refs':[], 'cost':{'state':'PARTIAL','is_proven_free':False,
           'totals':[{'amount':'0','currency':None,'role':'APPLICATION'}]}}
    summary=route_summary(route,'artifact:root')
    assert summary['cost']['total']=='UNKNOWN' and 'totals' not in summary['cost']
    assert summary['cost']['known_subtotal']==route['cost']['totals']
    assert summary['cost']['is_proven_free'] is False
    assert 'totals' in route['cost']


def test_same_path_rule_variants_are_counted_across_pages_without_invented_steps():
    from journeyplus.agent.tools.routes import result_page
    payload={'routes':{'r1':{'ref':'r1','step_refs':['a']},'r2':{'ref':'r2','step_refs':['b']}},
             'steps':{'a':{'from':'Origin','to':'Destination'},'b':{'from':'Origin','to':'Destination'}}}
    first,cursor=result_page(payload,'artifact:root',0,1)
    second,last=result_page(payload,'artifact:root',int(cursor.rsplit('|',1)[1]),1)
    assert first[0]['path']==second[0]['path']==['Origin','Destination']
    assert first[0]['same_path_variants']=={'index':1,'total':2}
    assert second[0]['same_path_variants']=={'index':2,'total':2}
    assert first[0]['ref']!=second[0]['ref'] and last is None


def test_business_snapshot_ignores_agent_messages_but_tracks_user_revision(session_factory):
    from journeyplus.agent.services.snapshots import snapshot_for
    from journeyplus.agent.tools.contracts import HoldingsReadInput
    from journeyplus.models import StatusHolding
    runtime,store,w,ctx=context(session_factory)
    snapshot=snapshot_for('holdings.read',runtime.services['knowledge'],session_factory)
    args=HoldingsReadInput()
    initial=snapshot(args,ctx)
    store.start(w['id'],'This is only a message','snapshot-message',0)
    assert snapshot(args,ctx)==initial
    with session_factory.begin() as session:
        session.add(StatusHolding(program_key='snapshot-program',tier_key='gold',program_display_name='Snapshot Program',tier_display_name='Gold'))
    assert snapshot(args,ctx)!=initial


def test_activity_read_accepts_computed_route_and_preserves_version(session_factory):
    from journeyplus.agent.tools.knowledge import activity
    from journeyplus.agent.tools.contracts import ActivityInput
    with session_factory.begin() as session:source,target=edge(session,alternative=True)
    runtime,store,w,ctx=context(session_factory)
    result=asyncio.run(evaluate(RoutesInput(operation='search',query={'sources':{'mode':'explicit','identities':[{'ref':'tier:'+str(source)}]}}),ctx))
    ref=result.data['route_refs'][0]
    root=store.artifacts.read(w['id'],ref.split('#')[0])['payload']
    expected={step['version_ref'] for step in root['steps'].values()}
    details=asyncio.run(activity(ActivityInput(selector={'ref':ref},view='detail'),ctx))
    assert details.data['activities']
    assert {item['version_ref'] for item in details.data['activities']}<=expected
    with pytest.raises(ValueError):
        asyncio.run(activity(ActivityInput(selector={'ref':ref},version_ref='00000000-0000-0000-0000-000000000001'),ctx))


def test_evidence_projection_keeps_qualifiers_without_replaying_all_material():
    from journeyplus.agent.services.materials import sectioned,summary
    from journeyplus.agent.services.artifact_views import view
    detail={'ref':'a','version_ref':'v','name':'Activity','brief_url':'/knowledge?a',
        'facts':{'conditions':{'items':[{'value':'Government issued document required'}]}},
        'options':[{'ref':'o','label':'Method','availability':'AVAILABLE','prices':[{'amount':'49','currency':'USD','known_state':'KNOWN','raw_text':'Unless otherwise stated'}],
                    'mappings':[{'ref':'m','from_program':'Other','from_tiers':['Gold'],'to_tier':'Silver'}]}],
        'evidence':{'data':{'facts':[{'field':'prices','value':{'raw_text':'Unless otherwise stated','known_state':'KNOWN'}}],
            'snippets':[{'ref':str(i),'text':'Source '*1000} for i in range(10)]},'coverage':{'complete':False},'expansions':[{'ref':'more'}]}}
    material=sectioned(detail);projection=summary(material,'artifact:a','evidence')
    assert 'options' not in projection and 'snippets' not in projection['evidence']
    assert projection['evidence']['facts'][0]['value']['raw_text']=='Unless otherwise stated'
    assert projection['evidence']['source_section_count']==10 and projection['evidence']['expansions']==[{'ref':'more'}]
    result=view([{'ref':'artifact:a','payload':material}],query='prices')
    assert result['section_count']==1
    assert result['sections'][0]['value']['prices'][0]['raw_text']=='Unless otherwise stated'
    assert result['sections'][0]['value']['option_ref']=='o'


def test_source_search_matches_price_content_not_uuid_substrings():
    from journeyplus.agent.services.artifact_views import view
    snippets=[{'ref':'abc-149-def','text':'FAQ navigation','source_role':'OFFICIAL'},
              {'ref':'actual','text':'Application fee USD 149 unless otherwise stated.','source_role':'OFFICIAL'}]
    result=view([{'ref':'artifact:x','payload':{'snippets':snippets}}],query='149')
    assert 'FAQ navigation' not in str(result['sections'])
    assert 'unless otherwise stated' in str(result['sections'])


def test_search_subtotal_and_path_are_citable_at_returned_member_reference(session_factory):
    with session_factory.begin() as session:
        source,_=edge(session,unknown_price=True)
    runtime,store,workspace,ctx=context(session_factory)
    result=asyncio.run(evaluate(RoutesInput(operation='search',query={
        'sources':{'mode':'explicit','identities':[{'ref':'tier:'+str(source)}]}}),ctx))
    from journeyplus.agent.services.completion import pointer
    for candidate in result.data['candidates']:
        snapshot=store.artifacts.read(workspace['id'],candidate['ref'])['payload']
        assert pointer(snapshot,'/path')==candidate['path']
        assert pointer(snapshot,'/cost/known_subtotal')==candidate['cost']['known_subtotal']
        assert pointer(snapshot,'/cost/total')=='UNKNOWN'
        assert candidate['cost']['details_omitted']
        assert snapshot['cost']['conditional_items']  # Expansion retains all fee evidence.


def test_complete_candidate_retrieval_is_independent_of_global_knowledge_gaps():
    from journeyplus.agent.tools.routes import coverage
    raw={'search_complete':False,'searched_published_graph_complete':True,
         'knowledge_complete':False,'stopped_reason':'KNOWLEDGE_GAPS',
         'incomplete_published_activity_count':1}
    assert not coverage(raw,23,8,0)['complete']
    final=coverage(raw,23,3,20)
    assert final['complete'] and final['retrieval_complete'] and final['search_complete']
    assert not final['knowledge_complete']
    assert final['knowledge_gap_reason']=='KNOWLEDGE_GAPS'
    assert final['stopped_reason'] is None
    capped=coverage({'search_complete':False,'stopped_reason':'STATE_BUDGET'},23,23)
    assert not capped['complete'] and capped['stopped_reason']=='STATE_BUDGET'


def test_explicit_free_filter_does_not_page_paid_nearby_routes_as_matches(session_factory):
    with session_factory.begin() as session:
        source,_=edge(session)
    runtime,store,workspace,ctx=context(session_factory)
    result=asyncio.run(evaluate(RoutesInput(operation='search',query={
        'sources':{'mode':'explicit','identities':[{'ref':'tier:'+str(source)}]},
        'constraints':{'free_only':True}}),ctx))
    assert result.status=='EMPTY' and result.data['candidates']==[]
    assert result.data['search_metrics']['candidate_counts']['NEARBY']==1
    snapshot=store.artifacts.read(workspace['id'],result.artifact_refs[-1])['payload']
    assert len(snapshot['routes'])==1 and snapshot['route_order']==[]
    assert result.coverage['retrieval_complete']  # No invisible "next free" page.
