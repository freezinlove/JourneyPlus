import asyncio

from journeyplus.agent.tools.contracts import RoutesInput
from journeyplus.agent.tools.routes import evaluate
from tests.test_harness_memory import setup
from tests.test_knowledge_routes import edge


def test_patch_without_quotations_inherits_conditions_and_records_actual_diff(session_factory):
    with session_factory.begin() as session:
        source, target = edge(session)
    runtime, store, workspace, run, ctx, _ = setup(session_factory)
    first = asyncio.run(evaluate(RoutesInput(operation='search', query={
        'sources': {'mode': 'explicit', 'identities': [{'ref': 'tier:' + str(source)}]},
        'target': {'ref': 'tier:' + str(target)},
        'constraints': {'max_amount': '250', 'currency': 'EUR', 'residency': 'Greece'},
    }), ctx))
    validated, error = runtime.ports.registry.validate('routes.evaluate', {
        'operation': 'search', 'query_ref': first.data['query_ref'],
        'patch': {'constraints': {'max_amount': '100'}},
    })
    assert error is None
    result = asyncio.run(runtime.ports.registry.execute(validated, ctx))
    assert result.error is None
    query = result.data['effective_query']
    assert query['sources'] == first.data['effective_query']['sources']
    assert query['target'] == first.data['effective_query']['target']
    assert query['constraints']['max_amount'] == '100'
    assert query['constraints']['currency'] == 'EUR'
    assert query['constraints']['residency'] == 'Greece'
    lineage = result.data['query_context']
    assert lineage['changes'] == [{'field': '/constraints/max_amount', 'before': '250', 'after': '100'}]
    assert lineage['source_message_refs'] == store.user_message_refs(workspace['id'], ctx.turn_id)
    assert 'constraint_changes' not in lineage
