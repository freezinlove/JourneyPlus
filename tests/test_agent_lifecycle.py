"""Real application lifespans with local models; no provider clients."""
import asyncio
from fastapi.testclient import TestClient
from journeyplus.agent.adapters.unconfigured import UnconfiguredModel
from journeyplus.agent.adapters.lazy_model import LazyModel
from journeyplus.product.api import create_product_app


def test_slow_and_failed_initialization_do_not_gate_product(session_factory):
    class Slow(UnconfiguredModel):
        disabled = False
        closed = False
        async def initialize(self):
            await asyncio.sleep(.1)
            raise ValueError('private configuration must not appear in status')
        async def close(self):
            self.closed = True
    model = Slow()
    app = create_product_app(session_factory, agent_model=model)
    with TestClient(app) as client:
        assert client.get('/holdings').status_code == 200
        assert client.get('/knowledge').status_code == 200
        for _ in range(100):
            status = client.get('/v3/agent/status').json()
            if status['status'] == 'UNAVAILABLE':
                break
            import time
            time.sleep(.005)
        assert status == {'status': 'UNAVAILABLE', 'error_type': 'ValueError'}
        assert model.closed
        w = client.post('/v3/agent/workspaces', json={}).json()
        reply = client.post('/v3/agent/workspaces/'+w['id']+'/runs', json={
            'text': 'hello', 'client_message_id': 'one', 'expected_revision': 0})
        assert reply.status_code == 503


def test_disabled_shell_does_not_probe_or_recover_pending_runs(session_factory):
    from journeyplus.agent.composition import compose_business
    model = UnconfiguredModel()
    async def forbidden():
        raise AssertionError('disabled model must not initialize')
    model.initialize = forbidden
    runtime, store = compose_business(session_factory, model)
    w = store.create(); run = store.start(w['id'], 'retained pending', 'one', 0)
    with TestClient(create_product_app(session_factory, agent_model=model)) as client:
        assert client.get('/v3/agent/status').json()['status'] == 'DISABLED'
        assert store.events(w['id'], run['run_id'])[1] == 'RUNNING'


def test_configuration_failure_is_local_and_creation_is_deferred(session_factory):
    made = []
    def factory():
        made.append(True)
        raise ValueError('missing configuration')
    app = create_product_app(session_factory, agent_model=LazyModel(factory))
    assert made == []
    with TestClient(app) as client:
        assert client.get('/holdings').status_code == 200
        assert made == [True]
        assert client.get('/v3/agent/status').json()['status'] == 'UNAVAILABLE'
