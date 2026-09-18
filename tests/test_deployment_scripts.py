"""Exercise deployment failure ordering with a fake Docker CLI; never contact a server."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
REVISION = 'a' * 40
IMAGE = 'ghcr.io/freezinlove/journeyplus@sha256:' + 'b' * 64

FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
args=sys.argv[1:]; base=pathlib.Path(os.environ['MOCK_STATE'])
scenario=os.environ['MOCK_SCENARIO']
with (base/'calls').open('a') as out: out.write(json.dumps(args)+'\n')
if 'login' in args:
    sys.stdin.read(); sys.exit(0)
if 'pull' in args:
    sys.exit(9 if scenario=='pull-fails' else 0)
if args[:2]==['image','inspect']:
    print(os.environ['MOCK_REVISION']); sys.exit(0)
if args[0]=='inspect':
    print('sha256:old-image' if args[-1]=='app-container' else 'healthy'); sys.exit(0)
if args[0]=='run': sys.exit(0)
if 'ps' in args:
    print('app-container' if args[-1]=='app' else 'postgres-container'); sys.exit(0)
if 'psql' in args:
    changed=(base/'migrated').exists() and scenario=='changed-health-fails'
    print('revision-after' if changed else 'revision-before'); sys.exit(0)
if 'pg_dump' in args:
    print('backup-content'); sys.exit(8 if scenario=='backup-fails' else 0)
if 'pg_restore' in args:
    assert sys.stdin.read()=='backup-content\n'; sys.exit(0)
if 'upgrade' in args:
    (base/'migrated').touch(); sys.exit(7 if scenario=='migration-fails' else 0)
if 'up' in args:
    if scenario.endswith('health-fails') and not (base/'up-failed').exists():
        (base/'up-failed').touch(); sys.exit(6)
sys.exit(0)
'''


@pytest.mark.parametrize('scenario', [
    'success', 'pull-fails', 'backup-fails', 'migration-fails',
    'unchanged-health-fails', 'changed-health-fails',
])
def test_release_failure_boundaries(tmp_path, scenario):
    project = tmp_path / 'project'
    project.mkdir()
    (project / '.env.deploy').write_text('')
    (project / '.secrets').mkdir()
    manifest = project / 'compose.deploy.yaml'
    manifest.write_text('')
    binary = tmp_path / 'bin'
    binary.mkdir()
    docker = binary / 'docker'
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    # macOS does not ship flock; this fake is only for the single-process harness.
    flock = binary / 'flock'
    flock.write_text('#!/bin/sh\nexit 0\n')
    flock.chmod(0o755)
    env = {**os.environ, 'PATH': str(binary) + os.pathsep + os.environ['PATH'],
           'MOCK_STATE': str(tmp_path), 'MOCK_SCENARIO': scenario, 'MOCK_REVISION': REVISION}
    result = subprocess.run(['bash', str(ROOT/'scripts/deploy/release.sh'),
                             REVISION, IMAGE, str(project), str(manifest)],
                            input='ephemeral-test-token', text=True, capture_output=True, env=env)
    calls = [json.loads(line) for line in (tmp_path/'calls').read_text().splitlines()]
    assert 'ephemeral-test-token' not in result.stdout + result.stderr
    assert (result.returncode == 0) == (scenario == 'success'), result.stdout + result.stderr
    stop = [c for c in calls if 'stop' in c]
    ups = [c for c in calls if 'up' in c]
    migrations = [c for c in calls if 'upgrade' in c]
    if scenario == 'pull-fails':
        assert not stop and not ups and not migrations
    elif scenario == 'backup-fails':
        assert stop and len(ups) == 1 and not migrations
    elif scenario == 'migration-fails':
        assert migrations and not ups
        assert '不自动恢复数据库' in result.stderr
    elif scenario == 'unchanged-health-fails':
        assert len(ups) == 2 and '上一应用已恢复' in result.stderr
    elif scenario == 'changed-health-fails':
        assert len(ups) == 1 and '不自动恢复数据库' in result.stderr
    else:
        state = project/'.local/deploy'
        assert (state/'current-image').read_text().strip() == IMAGE
        assert (state/'previous-image').read_text().strip() == 'sha256:old-image'
        assert list((state/'backups').glob('*.dump'))


@pytest.mark.parametrize('command', ['bash', 'deploy bad bad', 'deploy ' + REVISION + ' evil/image', 'deploy a;whoami'])
def test_forced_entry_rejects_unapproved_commands(command):
    result = subprocess.run(['bash', str(ROOT/'scripts/deploy/entry.sh')],
                            env={**os.environ, 'SSH_ORIGINAL_COMMAND': command}, capture_output=True)
    assert result.returncode == 64


def test_manual_workflow_does_not_trigger_on_push():
    workflow = (ROOT/'.github/workflows/deploy.yml').read_text()
    trigger = workflow.split('\non:', 1)[1].split('\npermissions:', 1)[0]
    assert 'workflow_dispatch:' in trigger
    assert 'push:' not in trigger and 'pull_request:' not in trigger and 'schedule:' not in trigger
    assert "github.ref == 'refs/heads/main'" in workflow
    assert 'cancel-in-progress: false' in workflow
