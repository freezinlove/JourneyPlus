"""Run the unchanged current official workflow against the restored legacy DB."""
import json
import time
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from journeyplus.ai.provider import OpenAICompatibleProvider
from journeyplus.config import Settings
from journeyplus.models import DocumentVersion
from journeyplus.sources.base import HttpxFetcher
from journeyplus.sources.registry import seed_sources
from journeyplus.statusmatch.audit import audit_statusmatch_projects
from journeyplus.statusmatch.graph import MembershipGraphService
from journeyplus.statusmatch.project_workflow import process_pending_statusmatch_projects


folder = Path(__file__).resolve().parent
manifest = json.loads((folder / 'manifest.json').read_text())
settings = Settings.from_env()
url = make_url(settings.database_url)
assert url.database == 'journeyplus' and manifest['database'].startswith('journeyplus_old_flyingblue_')
engine = create_engine(url.set(database=manifest['database']), pool_pre_ping=True)
factory = sessionmaker(engine, expire_on_commit=False)


def save(name, value):
    (folder / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


class ObservedProvider:
    def __init__(self):
        self.delegate = OpenAICompatibleProvider(settings)
        self.metadata = self.delegate.metadata
        self.calls = []

    def generate_structured(self, **kwargs):
        record = {'number': len(self.calls) + 1, 'output_model': kwargs['output_model'].__name__}
        self.calls.append(record)
        started = time.monotonic()
        print(json.dumps({'model_call_started': record}, ensure_ascii=False), flush=True)
        try:
            result = self.delegate.generate_structured(**kwargs)
            record['status'] = 'SUCCEEDED'
            save('model-output-' + str(record['number']) + '.json', result.model_dump(mode='json'))
            return result
        except Exception as exc:
            record.update(status='FAILED', error=str(exc)[:1500])
            raise
        finally:
            record['elapsed_seconds'] = round(time.monotonic() - started, 2)
            record['metrics'] = self.delegate.last_call_metrics
            save('model-calls.json', self.calls)
            print(json.dumps({'model_call_finished': record}, ensure_ascii=False), flush=True)


class ObservedFetcher:
    def __init__(self):
        self.delegate = HttpxFetcher()

    def get(self, url):
        result = self.delegate.get(url)
        print(json.dumps({'fetched': result.final_url, 'characters': len(result.body)}), flush=True)
        return result


provider = ObservedProvider()
try:
    with factory.begin() as session:
        seed_sources(session)
    report = audit_statusmatch_projects(factory, provider, hosts=[manifest['host']], fetcher=ObservedFetcher())
    save('first-run.json', report)
    print(json.dumps({'first_run_processing': report['processing']}, ensure_ascii=False), flush=True)
    if report['processing']['succeeded']:
        before = len(provider.calls)
        reuse = process_pending_statusmatch_projects(factory, provider, hosts=[manifest['host']], limit=1)
        save('unchanged-input-check.json', {'processing': asdict(reuse), 'additional_model_calls': len(provider.calls) - before})
        with factory() as session:
            graph = MembershipGraphService(session).build()
            save('graph.json', graph.model_dump(mode='json'))
            audit = MembershipGraphService(session).audit()
            save('graph-audit.json', audit.model_dump(mode='json'))
    with factory() as session:
        docs = []
        for doc in session.scalars(select(DocumentVersion)):
            stem = 'document-' + str(doc.id)
            (folder / (stem + '.html')).write_text(doc.raw_body)
            (folder / (stem + '.txt')).write_text(doc.normalized_body)
            docs.append({'id': str(doc.id), 'url': doc.canonical_url, 'raw_file': stem + '.html', 'text_file': stem + '.txt'})
        save('documents.json', docs)
finally:
    engine.dispose()
