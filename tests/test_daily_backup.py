import hashlib
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('daily_backup', Path(__file__).parents[1] / 'scripts/automation/daily.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class Store:
    def __init__(self):
        self.data = {}
        self.fail = None
    def put_verified(self, key, path, run_id):
        if self.fail and self.fail in key:
            raise RuntimeError('network')
        self.data[key] = (path.read_bytes(), run_id)
    def head(self, key):
        if key not in self.data:
            return None
        data, run_id = self.data[key]
        return {'x-cos-meta-run-id': run_id, 'x-cos-meta-sha256': hashlib.sha256(data).hexdigest()}
    def download(self, key, path):
        path.write_bytes(self.data[key][0])
    def list(self, prefix):
        return [k for k in self.data if k.startswith(prefix)]
    def delete(self, key):
        self.data.pop(key, None)


def bundle(tmp, number):
    path = tmp / 'bundle.tar'
    path.write_bytes(f'database snapshot {number}'.encode())
    return path, f'202609{number:02d}T130000Z-000000000000'


def test_eight_distinct_backups_and_latest(tmp_path):
    store = Store()
    for n in range(1, 11):
        path, run_id = bundle(tmp_path, n)
        m.rotate(store, path, run_id, tmp_path)
    history = store.list('journeyplus/history/')
    assert len(history) == 7
    assert len(store.data) == 8
    assert store.data['journeyplus/latest/backup.tar'][1].startswith('20260910')
    assert sorted(store.data[k][1][:8] for k in history) == [f'202609{n:02d}' for n in range(3, 10)]


@pytest.mark.parametrize('failure', ['pending/', 'history/', 'latest/'])
def test_failure_keeps_previous_backup(tmp_path, failure):
    store = Store()
    m.rotate(store, *bundle(tmp_path, 1), tmp_path)
    old = store.data['journeyplus/latest/backup.tar']
    store.fail = failure
    with pytest.raises(RuntimeError):
        m.rotate(store, *bundle(tmp_path, 2), tmp_path)
    assert store.data['journeyplus/latest/backup.tar'] == old
    store.fail = None
    m.rotate(store, *bundle(tmp_path, 2), tmp_path)
    assert len(store.data) == 2


def test_retry_does_not_duplicate_or_rollback_latest(tmp_path):
    store = Store()
    for n in [1, 3, 3, 2, 2]:
        m.rotate(store, *bundle(tmp_path, n), tmp_path)
    assert len(store.data) == 3
    assert store.data['journeyplus/latest/backup.tar'][1].startswith('20260903')


def test_unknown_latest_never_overwritten(tmp_path):
    store = Store()
    store.data['journeyplus/latest/backup.tar'] = (b'original', 'unknown')
    with pytest.raises(RuntimeError, match='unknown identity'):
        m.rotate(store, *bundle(tmp_path, 1), tmp_path)
    assert store.data['journeyplus/latest/backup.tar'][0] == b'original'


def test_only_managed_history_deleted(tmp_path):
    store = Store()
    store.data['journeyplus/history/manual-archive.tar'] = (b'manual', 'manual')
    for n in range(1, 11):
        m.rotate(store, *bundle(tmp_path, n), tmp_path)
    assert 'journeyplus/history/manual-archive.tar' in store.data


def test_business_failure_not_success():
    assert m.workflow_ok(0, {'status': 'SUCCEEDED'})
    assert not m.workflow_ok(0, {'status': 'FAILED'})
    assert not m.workflow_ok(0, None)
    assert not m.workflow_ok(1, {'status': 'SUCCEEDED'})
    assert not m.workflow_ok(0, {'status': 'SKIPPED'})


def test_log_redaction():
    assert m.scrub('password=abcdef Bearer abc.xyz', ['abcdef']) == 'password=[REDACTED] Bearer [REDACTED]'


def test_workflow_failure_still_produces_database_backup(tmp_path, monkeypatch):
    import io
    import json
    import tarfile
    (tmp_path / '.env.deploy').write_text('API_KEY=super-secret-value\n')
    (tmp_path / '.secrets').mkdir()
    state = tmp_path / 'state'
    class Process:
        stdout = io.StringIO('Bearer abc.def\n{"status":"FAILED","error":"super-secret-value"}\n')
        def wait(self):
            return 0
    monkeypatch.setattr(m.subprocess, 'Popen', lambda *a, **k: Process())
    def command(args, **kwargs):
        if 'pg_dump' in args:
            kwargs['stdout'].write(b'custom database archive')
    monkeypatch.setattr(m.subprocess, 'run', command)
    assert m.capture(tmp_path, state) is False
    run = next((state / 'runs').iterdir())
    result = json.loads((run / 'result.json').read_text())
    assert result['backup_ok'] and not result['workflow_ok']
    assert 'super-secret-value' not in (run / 'workflow.log').read_text()
    with tarfile.open(run / 'backup.tar') as tar:
        assert 'database.dump' in tar.getnames()


def test_failed_dump_uploads_logs_without_replacing_latest(tmp_path, monkeypatch):
    import tarfile
    (tmp_path / '.env.deploy').write_text('')
    (tmp_path / '.secrets').mkdir()
    def failure(*args, **kwargs):
        raise RuntimeError('database offline')
    monkeypatch.setattr(m.subprocess, 'run', failure)
    state = tmp_path / 'state'
    assert m.capture(tmp_path, state, backup_only=True) is False
    run = next((state / 'runs').iterdir())
    with tarfile.open(run / 'backup.tar') as tar:
        assert 'database.dump' not in tar.getnames()
        assert 'workflow.log' in tar.getnames()
    store = Store()
    store.data['journeyplus/latest/backup.tar'] = (b'valid old backup', 'original')
    m.upload_pending(store, state)
    assert store.data['journeyplus/latest/backup.tar'][0] == b'valid old backup'
    assert len(store.list('journeyplus/failures/')) == 1
    assert (run / 'uploaded').exists()


def test_retry_never_calls_workflow(tmp_path, monkeypatch):
    import json
    state = tmp_path / 'state'
    run = state / 'runs' / '20260918T130000Z-000000000000'
    run.mkdir(parents=True)
    (run / 'backup.tar').write_bytes(b'backup')
    (run / 'result.json').write_text(json.dumps({'backup_ok': True}))
    monkeypatch.setattr(m, 'capture', lambda *a: pytest.fail('retry called workflow'))
    store = Store()
    m.upload_pending(store, state)
    m.upload_pending(store, state)
    assert len(store.data) == 1
