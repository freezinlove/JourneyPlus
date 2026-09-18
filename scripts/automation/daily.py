#!/usr/bin/env python3
"""Host-side daily workflow and COS backup. Python stdlib only; never logs credentials."""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET


def digest(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


class COS:
    def __init__(self, bucket, region, role):
        if not all(re.fullmatch(r'[A-Za-z0-9_-]+', x) for x in (bucket, region, role)):
            raise ValueError('Invalid COS configuration')
        self.host = f'{bucket}.cos.{region}.myqcloud.com'
        self.role = role

    def request(self, method, key='', params=None, body=None, metadata=None):
        # Retrieve credentials for each request so long runs survive credential rotation.
        url = 'http://metadata.tencentyun.com/latest/meta-data/cam/security-credentials/' + self.role
        with urllib.request.urlopen(url, timeout=10) as r:
            cred = json.load(r)
        enc = lambda x: urllib.parse.quote(str(x), safe='-_.~')
        params = params or {}
        query = '&'.join(f'{enc(k.lower())}={enc(v)}' for k, v in sorted(params.items()))
        path = '/' + urllib.parse.quote(key, safe='/-_.~')
        keytime = f'{int(time.time())-60};{int(time.time())+3600}'
        canonical = f'{method.lower()}\n{path}\n{query}\nhost={enc(self.host)}\n'
        signkey = hmac.new(cred['TmpSecretKey'].encode(), keytime.encode(), hashlib.sha1).hexdigest()
        tosign = f'sha1\n{keytime}\n{hashlib.sha1(canonical.encode()).hexdigest()}\n'
        signature = hmac.new(signkey.encode(), tosign.encode(), hashlib.sha1).hexdigest()
        auth = (f'q-sign-algorithm=sha1&q-ak={cred["TmpSecretId"]}&q-sign-time={keytime}'
                f'&q-key-time={keytime}&q-header-list=host&q-url-param-list={";".join(sorted(params))}'
                f'&q-signature={signature}')
        headers = {'Authorization': auth, 'x-cos-security-token': cred['Token']}
        headers.update({'x-cos-meta-' + k: v for k, v in (metadata or {}).items()})
        with contextlib.ExitStack() as stack:
            data = None
            if body is not None:
                if body.stat().st_size >= 5 * 1024**3:
                    raise ValueError('Backup exceeds simple-upload 5 GiB limit; configure multipart before retry')
                data = stack.enter_context(body.open('rb'))
                headers['Content-Length'] = str(body.stat().st_size)
                headers['x-cos-server-side-encryption'] = 'AES256'
            req = urllib.request.Request('https://' + self.host + path + ('?' + query if query else ''),
                                         data=data, method=method, headers=headers)
            return urllib.request.urlopen(req, timeout=300)

    def head(self, key):
        try:
            with self.request('HEAD', key) as r:
                return dict(r.headers.items())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def download(self, key, path):
        with self.request('GET', key) as r, path.open('wb') as f:
            shutil.copyfileobj(r, f)

    def put_verified(self, key, path, run_id):
        sha = digest(path)
        with self.request('PUT', key, body=path, metadata={'sha256': sha, 'run-id': run_id}) as r:
            if r.status != 200:
                raise RuntimeError('COS upload failed')
        # Verify actual stored bytes, not just self-supplied object metadata.
        check = hashlib.sha256()
        with self.request('GET', key) as r:
            while chunk := r.read(1024 * 1024):
                check.update(chunk)
        if check.hexdigest() != sha:
            raise RuntimeError('COS checksum mismatch')

    def list(self, prefix):
        marker = ''
        result = []
        while True:
            params = {'prefix': prefix, 'max-keys': '1000'}
            if marker:
                params['marker'] = marker
            with self.request('GET', params=params) as r:
                root = ET.fromstring(r.read())
            for el in root.iter():
                el.tag = el.tag.split('}')[-1]
            keys = [el.findtext('Key') for el in root.findall('Contents')]
            result.extend(keys)
            if root.findtext('IsTruncated') != 'true':
                return result
            marker = root.findtext('NextMarker') or keys[-1]

    def delete(self, key):
        with self.request('DELETE', key):
            pass


RUN_ID = re.compile(r'\d{8}T\d{6}Z-[0-9a-f]{12}')


def rotate(cos, bundle, run_id, scratch):
    """Single-writer, retry-safe promotion; latest is one atomic COS object."""
    latest = 'journeyplus/latest/backup.tar'
    history = 'journeyplus/history/'
    candidate = f'journeyplus/pending/{run_id}.tar'
    cos.put_verified(candidate, bundle, run_id)
    head = cos.head(latest)
    old = None
    if head:
        head = {k.lower(): v for k, v in head.items()}
        previous = head.get('x-cos-meta-run-id', '')
        if not RUN_ID.fullmatch(previous):
            raise RuntimeError('Latest backup has unknown identity; refusing to replace it')
        if previous == run_id and head.get('x-cos-meta-sha256') != digest(bundle):
            raise RuntimeError('Run ID collision')
        if previous != run_id and previous < run_id:
            old = scratch / 'previous.tar'
            cos.download(latest, old)
            if digest(old) != head.get('x-cos-meta-sha256'):
                raise RuntimeError('Previous backup checksum mismatch')
            cos.put_verified(history + previous + '.tar', old, previous)
    else:
        previous = ''
    if previous <= run_id:
        try:
            cos.put_verified(latest, bundle, run_id)
        except Exception:
            if old is not None:
                cos.put_verified(latest, old, previous)
            raise
        # Covers retries after promotion succeeded but response/cleanup was lost.
        cos.delete(history + run_id + '.tar')
    else:
        # An older queued run may never roll latest backwards.
        cos.put_verified(history + run_id + '.tar', bundle, run_id)
    keys = sorted(k for k in cos.list(history)
                  if k.startswith(history) and k.endswith('.tar')
                  and RUN_ID.fullmatch(k[len(history):-4]))
    for key in keys[:-7]:
        cos.delete(key)
    cos.delete(candidate)


def compose(root):
    state = root / '.local/deploy'
    manifest = root / 'compose.deploy.yaml'
    if (state / 'current-image').exists() and (state / 'current-compose.yaml').exists():
        os.environ['JOURNEYPLUS_APP_IMAGE'] = (state / 'current-image').read_text().strip()
        manifest = state / 'current-compose.yaml'
    return ['docker', 'compose', '--project-directory', str(root), '--env-file', str(root / '.env.deploy'),
            '-f', str(manifest)]


def secrets(root):
    values = []
    for line in (root / '.env.deploy').read_text().splitlines():
        key, sep, value = line.partition('=')
        if sep and re.search('KEY|TOKEN|PASSWORD|SECRET', key, re.I):
            value = value.strip().strip('\"\'')
            if len(value) >= 6:
                values.append(value)
    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str) and re.search('secret|token|password', k, re.I) and len(v) >= 6:
                    values.append(v)
                else:
                    walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
    for path in (root / '.secrets').glob('*.json'):
        walk(json.loads(path.read_text()))
    return sorted(set(values), key=len, reverse=True)


def scrub(text, hidden):
    for value in hidden:
        text = text.replace(value, '[REDACTED]')
    return re.sub(r'(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]+', r'\1[REDACTED]', text)


def workflow_ok(code, summary):
    return code == 0 and isinstance(summary, dict) and summary.get('status') == 'SUCCEEDED'


def capture(root, state, backup_only=False):
    run_id = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:12]
    run = state / 'runs' / run_id
    run.mkdir(parents=True)
    cmd = compose(root)
    hidden = secrets(root)
    start = dt.datetime.now(dt.timezone.utc).isoformat()
    summary, code = None, 0
    with (run / 'workflow.log').open('w') as log:
        if not backup_only:
            proc = subprocess.Popen(cmd + ['exec', '-T', 'app', 'journeyplus', 'run-daily'],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                clean = scrub(line, hidden)
                log.write(clean)
                log.flush()
                try:
                    candidate = json.loads(clean)
                    if isinstance(candidate, dict) and 'status' in candidate:
                        summary = candidate
                except ValueError:
                    pass
            code = proc.wait()
        else:
            log.write('Backup-only verification; AIWorkflow was not executed.\n')
    result = {'run_id': run_id, 'started_at': start, 'workflow_finished_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'mode': 'backup-only' if backup_only else 'daily', 'exit_code': code,
              'workflow_ok': backup_only or workflow_ok(code, summary), 'summary': summary}
    # Always try backing up even if workflow returned business failure or exited nonzero.
    (run / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    files = ['workflow.log', 'result.json']
    try:
        with (run / 'database.dump.partial').open('wb') as out:
            subprocess.run(cmd + ['exec', '-T', 'postgres', 'pg_dump', '-U', 'journeyplus', '-d', 'journeyplus',
                                 '--format=custom', '--no-owner', '--no-acl'], stdout=out, stderr=subprocess.PIPE, check=True)
        with (run / 'database.dump.partial').open('rb') as inp:
            subprocess.run(cmd + ['exec', '-T', 'postgres', 'pg_restore', '--list'], stdin=inp,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
        (run / 'database.dump.partial').rename(run / 'database.dump')
        files.insert(0, 'database.dump')
        result['backup_ok'] = True
    except Exception as exc:
        result['backup_ok'] = False
        result['backup_error_type'] = type(exc).__name__
    (run / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    (run / 'SHA256SUMS').write_text(''.join(f'{digest(run / name)}  {name}\n' for name in files))
    with tarfile.open(run / 'backup.tar.partial', 'w') as archive:
        for name in files + ['SHA256SUMS']:
            archive.add(run / name, arcname=name)
    (run / 'backup.tar.partial').rename(run / 'backup.tar')
    print('Backup prepared:', run_id, flush=True)
    return result['workflow_ok'] and result['backup_ok']


def upload_pending(cos, state):
    for run in sorted((state / 'runs').glob('*')):
        bundle = run / 'backup.tar'
        if not bundle.exists() or (run / 'uploaded').exists():
            continue
        with tempfile.TemporaryDirectory(dir=state) as directory:
            result = json.loads((run / 'result.json').read_text())
            if result['backup_ok']:
                rotate(cos, bundle, run.name, Path(directory))
            else:
                # Failed dumps do not replace the latest usable database backup.
                prefix = 'journeyplus/failures/'
                cos.put_verified(prefix + run.name + '.tar', bundle, run.name)
                keys = sorted(k for k in cos.list(prefix) if k.endswith('.tar')
                              and RUN_ID.fullmatch(k[len(prefix):-4]))
                for key in keys[:-7]:
                    cos.delete(key)
        (run / 'uploaded').write_text(dt.datetime.now(dt.timezone.utc).isoformat())
        print('COS backup verified:', run.name, flush=True)
    # Keep eight successful local batches; never remove unuploaded batches.
    uploaded = sorted(p for p in (state / 'runs').glob('*') if (p / 'uploaded').exists())
    for run in uploaded[:-8]:
        shutil.rmtree(run)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['daily', 'retry', 'backup-only'])
    parser.add_argument('--root', required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    root = args.root.resolve()
    state = root / '.local/automation'
    state.mkdir(parents=True, exist_ok=True)
    lock = root / '.local/deploy/release.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Deployment or workflow is running; retry later.', flush=True)
            return 75
        ok = True
        if args.mode != 'retry':
            if shutil.disk_usage(root).free < 1024**3:
                raise RuntimeError('Less than 1 GiB disk free')
            ok = capture(root, state, args.mode == 'backup-only')
        cos = COS(os.environ['COS_BUCKET'], os.environ['COS_REGION'], os.environ['COS_ROLE'])
        upload_pending(cos, state)
        return 0 if ok else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Do not print URLs, response bodies, subprocess output or signed headers.
        print('Automation failed:', type(exc).__name__, flush=True)
        raise SystemExit(1)
