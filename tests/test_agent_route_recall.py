"""Archived routes stay readable; a step never silently selects a route."""
import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest

from journeyplus.agent.services.artifact_views import view
from journeyplus.agent.services.route_archive import overviews
from journeyplus.agent.services.route_objects import RouteObject, RouteReferenceError
from journeyplus.agent.tools.contracts import DisplayInput, WorkspaceReadInput
from journeyplus.agent.tools.presentation import present
from journeyplus.agent.services.workspace import read
from tests.test_harness_tools import context


def snapshot():
    return {'routes': {'r': {'step_refs': ['s']}}, 'route_order': ['r'], 'steps': {'s': {
        'from': 'Aeroplan Elite 50K', 'to': 'Flying Blue Gold',
        'fees': [{'amount': '199', 'currency': 'EUR', 'conditions': ['Greece']}],
        'status_validity': {'value': '批准后12个月', 'conflict': False, 'alternatives': []},
        'challenge': 'UNKNOWN', 'eligibility': 'UNKNOWN',
        'constraint_checks': [{'topic': 'ELIGIBILITY', 'result': 'UNKNOWN', 'reason': '仍需核实是否首次申请'}],
        'material_caveats': ['每人仅限一次'],
        'activity_ref': 'activity-id', 'version_ref': 'version-id',
        'action_link': 'https://flyingblue.statusmatch.com/',
        'raw_archive': '保留完整资料，包括不能丢掉的最后一段。' * 500,
    }}}


@pytest.mark.parametrize('kind', ['ROUTES', 'MATERIAL'])
def test_overview_keeps_step_facts_together_and_archive_lossless(kind):
    payload = snapshot()
    if kind == 'MATERIAL':
        payload = {'data': {'candidates': [{'ref': 'artifact:routes#route:r',
                    'step_refs': ['artifact:routes#step:s']}],
                    'steps': [{**payload['steps']['s'], 'ref': 'artifact:routes#step:s'}]}}
    record = {'ref': 'artifact:routes' if kind == 'ROUTES' else 'artifact:result',
              'kind': kind, 'payload': payload}
    original = deepcopy(record)
    first = view([record])
    section = first['sections'][0]
    assert section['section'] == 'route_overview' and section['derived'] is True
    assert 'path' not in section  # Derived views must not pretend to be a source JSON pointer.
    route = section['value']
    assert route['ref'] == 'artifact:routes#route:r'
    assert route['step_details_available'] is True
    step = route['steps'][0]
    assert step['fees'] == original['payload'].get('steps', {}).get('s', step)['fees']
    assert step['fees'][0]['conditions'] == ['Greece']
    assert step['status_validity']['value'] == '批准后12个月'
    assert step['challenge'] == 'UNKNOWN'
    assert step['constraint_checks'][0]['result'] == 'UNKNOWN'
    assert step['material_caveats'] == ['每人仅限一次']
    assert step['version_ref'] == 'version-id'
    assert step['action_link'] == 'https://flyingblue.statusmatch.com/'
    sections = list(first['sections'])
    cursor = first['next_cursor']
    while cursor:
        page = view([record], cursor=cursor)
        sections.extend(page['sections'])
        cursor = page['next_cursor']
    chunks = [s for s in sections if s.get('path', '').endswith('/raw_archive')]
    assert ''.join(s['value'] for s in chunks) == snapshot()['steps']['s']['raw_archive']
    assert record == original
    assert view([record], query='Greece')['sections'][0]['value']['steps'][0]['status_validity']['value'] == '批准后12个月'
    with pytest.raises(ValueError, match='STALE_REFERENCE'):
        view([record], query='other', cursor=first['next_cursor'])


def test_oversized_overview_is_an_explicit_index_not_partial_facts():
    payload = snapshot()
    payload['steps']['s']['status_validity']['alternatives'] = ['有争议的条件' * 2000]
    item = overviews({'ref': 'artifact:routes', 'kind': 'ROUTES', 'payload': payload})[0]['value']
    assert item['overview_omitted'] is True
    assert item['ref'] == 'artifact:routes#route:r'
    assert 'steps' not in item


def test_workspace_reads_persisted_tool_result_as_route_overview(session_factory):
    from journeyplus.agent.harness.contracts import ToolResult
    _, store, workspace, ctx = context(session_factory)
    payload = snapshot()
    route_root = store.artifacts.put(workspace['id'], 'ROUTES', payload)
    result = ToolResult(data={'candidates': [{'ref': route_root+'#route:r',
                        'step_refs': [route_root+'#step:s']}],
                        'steps': [{**payload['steps']['s'], 'ref': route_root+'#step:s'}]})
    # Use the production result recorder, including its actual archive kind.
    run = store.start(workspace['id'], '找回原来的路线', str(uuid4()), workspace['revision'])
    owner = str(uuid4())
    store.claim_run(run['run_id'], owner)
    call = {'call_id': ctx.call_id, 'name': 'routes.evaluate', 'arguments': {'operation': 'inspect'}}
    store.tool_intent(run['run_id'], owner, call, 'READ')
    archived = store.tool_result(run['run_id'], owner, call, result)
    page = asyncio.run(read(WorkspaceReadInput(kind='artifact', refs=[archived]), ctx))
    overview = page.data['sections'][0]
    assert overview['section'] == 'route_overview'
    assert overview['value']['steps'][0]['status_validity']['value'] == '批准后12个月'


def test_wrong_step_returns_only_same_snapshot_routes_and_never_presents(session_factory):
    _, store, workspace, ctx = context(session_factory)
    payload = snapshot()
    payload['steps']['t'] = {**payload['steps']['s'], 'from': 'Flying Blue Gold', 'to': 'Another Gold'}
    payload['steps']['u'] = {**payload['steps']['s'], 'from': 'Other Silver', 'to': 'Other Gold'}
    payload['routes'].update({'r2': {'step_refs': ['s', 't'], 'cost': {'state': 'UNKNOWN'}}, 'unrelated': {'step_refs': ['u']}})
    payload['route_order'] = ['r', 'r2', 'unrelated']
    root = store.artifacts.put(workspace['id'], 'ROUTES', payload)
    store.artifacts.put(workspace['id'], 'ROUTES', payload)  # Never combine snapshots.
    before = store.read(workspace['id'])
    failed = asyncio.run(present(DisplayInput(blocks=[{'type': 'route_graph', 'object_refs': [root+'#step:s']}]), ctx))
    assert failed.status == 'ERROR'
    error = failed.error.model_dump()
    assert error['code'] == 'WRONG_REFERENCE_TYPE'
    assert [c['ref'] for c in error['candidates']] == [root+'#route:r', root+'#route:r2']
    assert error['candidates'][1]['path'] == ['Aeroplan Elite 50K', 'Flying Blue Gold', 'Another Gold']
    assert error['fields'][0]['candidates_complete'] is True
    assert store.read(workspace['id']) == before
    assert not failed.artifact_refs
    chosen = error['candidates'][1]['ref']
    shown = asyncio.run(present(DisplayInput(blocks=[{'type': 'route_graph', 'object_refs': [chosen]}]), ctx))
    assert shown.status == 'OK'
    assert shown.data['blocks'][0]['ordered_refs'] == [chosen]
    other = store.create()
    with pytest.raises(LookupError):
        RouteObject.read(store.artifacts, other['id'], root+'#step:s')


def test_many_route_choices_are_bounded_and_explicitly_incomplete(session_factory):
    _, store, workspace, ctx = context(session_factory)
    payload = snapshot()
    payload['routes'] = {str(i): {'step_refs': ['s']} for i in range(12)}
    payload['route_order'] = list(payload['routes'])
    root = store.artifacts.put(workspace['id'], 'ROUTES', payload)
    with pytest.raises(RouteReferenceError) as caught:
        RouteObject.read(store.artifacts, workspace['id'], root)
    assert len(caught.value.candidates) == 10 and caught.value.total == 12
    failed = asyncio.run(present(DisplayInput(blocks=[{'type': 'route_graph', 'object_refs': [root+'#step:s']}]), ctx))
    assert failed.error.fields[0]['matching_route_count'] == 12
    assert failed.error.fields[0]['candidates_complete'] is False
    assert failed.error.fields[0]['snapshot_ref'] == root
