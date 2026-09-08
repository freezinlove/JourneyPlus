"""Agent configuration and tools cannot become Workflow control dependencies."""
import ast
from importlib.util import resolve_name
from pathlib import Path


ROOT = Path(__file__).parents[1] / 'src' / 'journeyplus'


def imports(path):
    package='journeyplus.'+'.'.join(path.relative_to(ROOT).parts[:-1])
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node,ast.Import):
            yield from (item.name for item in node.names)
        elif isinstance(node,ast.ImportFrom):
            name='.'*node.level+(node.module or '')
            base=resolve_name(name,package) if node.level else name
            yield base
            yield from (base+'.'+item.name for item in node.names)


def test_workflow_has_no_agent_runtime_or_tool_dependency():
    paths=[ROOT/'workflow.py']
    for name in ('article_pipeline','ai','briefs','sources','statusmatch','automation'):
        paths.extend((ROOT/name).rglob('*.py'))
    for path in paths:
        assert not any(name.startswith('journeyplus.agent') for name in imports(path)),path


def test_tools_and_services_do_not_reenter_the_agent_controller():
    forbidden=('journeyplus.agent.harness.runtime','journeyplus.agent.workspace',
               'journeyplus.agent.controller','journeyplus.agent.composition')
    handlers={'journeyplus.agent.tools.'+name for name in
              ('knowledge','routes','holdings','research','workspace','presentation','waiting')}
    for layer in ('tools','services'):
        for path in (ROOT/'agent'/layer).glob('*.py'):
            names=set(imports(path))
            assert not any(name.startswith(forbidden) for name in names),path
            assert not names & handlers,path


def test_agent_configuration_does_not_mutate_workflow_configuration(monkeypatch):
    from dataclasses import asdict
    from journeyplus.config import Settings
    from journeyplus.agent.adapters.config import AgentConfig
    before=asdict(Settings.from_env())
    monkeypatch.setenv('JOURNEYPLUS_AGENT_MODEL','isolated-test-model')
    monkeypatch.setenv('JOURNEYPLUS_AGENT_CONTEXT_WINDOW','32768')
    monkeypatch.setenv('JOURNEYPLUS_AGENT_NETWORK_ENABLED','false')
    monkeypatch.setenv('JOURNEYPLUS_AGENT_THINKING','true')
    config=AgentConfig.from_env()
    assert config.model=='isolated-test-model' and config.thinking
    assert not config.network_enabled
    assert asdict(Settings.from_env())==before
