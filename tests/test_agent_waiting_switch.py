"""Disabling waiting removes model access and skips scheduled checks together."""
import pytest

from journeyplus.agent.composition import compose_business
from tests.test_harness_runtime import FakeModel


@pytest.mark.parametrize('setting', [None, 'false', 'true'])
def test_waiting_switch_controls_tools_and_maintenance(session_factory, monkeypatch, setting):
    if setting is None:
        monkeypatch.delenv('JOURNEYPLUS_AGENT_WAITING_ENABLED', raising=False)
    else:
        monkeypatch.setenv('JOURNEYPLUS_AGENT_WAITING_ENABLED', setting)
    enabled = setting == 'true'
    runtime, store = compose_business(session_factory, FakeModel([]), read_factory=session_factory)
    names = {item.name for item in runtime.ports.registry.definitions()}
    assert ('waiting.manage' in names) == enabled
    assert {'routes.evaluate', 'activity.read', 'display.present', 'holdings.write'} <= names
    assert ('当前等待功能已关闭' in runtime.instructions) == (not enabled)
    calls = []
    monkeypatch.setattr(store, 'cleanup', lambda: calls.append('cleanup'))
    monkeypatch.setattr(runtime.services['waiting'], 'check', lambda: calls.append('waiting') or {'status': 'NO_HIT'})
    result = runtime.services['maintenance']()
    assert calls == (['cleanup', 'waiting'] if enabled else ['cleanup'])
    assert result['waiting']['status'] == ('NO_HIT' if enabled else 'DISABLED')
    if not enabled:
        validated, error = runtime.ports.registry.validate('waiting.manage', {'operation': 'create'})
        assert validated is None and error.error.code == 'UNKNOWN_TOOL'
