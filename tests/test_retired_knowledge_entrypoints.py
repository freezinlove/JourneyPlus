"""Production commands cannot re-enter the retired knowledge publication flow."""
import json
import pytest
from journeyplus import cli
from journeyplus.knowledge.audit import workflow_audit
from journeyplus.knowledge.workflow_knowledge import WorkflowKnowledgePort
from tests.test_agent_workflow_reads import original_factory, seed


def test_only_current_read_audit_remains_in_cli():
    parser = cli.build_parser()
    assert parser.parse_args(['knowledge-audit']).command == 'knowledge-audit'
    for command in ('knowledge-refresh', 'knowledge-backfill', 'knowledge-review-edition'):
        with pytest.raises(SystemExit) as error:
            parser.parse_args([command])
        assert error.value.code == 2


def test_current_audit_reads_original_schema_without_migration(original_factory, monkeypatch, capsys):
    seed(original_factory)
    monkeypatch.setattr(cli, 'engine_from_settings', lambda _: original_factory.kw['bind'])
    monkeypatch.setattr(cli, 'create_session_factory', lambda _: original_factory)
    original_factory.statements.clear()
    assert cli.main(['knowledge-audit']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['data_model'] == 'aiworkflow'
    assert result['counts']['article_opportunities'] == 1
    assert 'association_status' not in json.dumps(result)
    sql = '\n'.join(original_factory.statements).lower()
    assert 'membership_programs' not in sql and 'activity_knowledge_versions' not in sql
    assert not any(s.lstrip().lower().startswith(('insert ', 'update ', 'delete ', 'create ', 'alter ')) for s in original_factory.statements)
