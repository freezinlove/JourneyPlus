"""Scoped temporary objects; a reference cannot grant cross-workspace access."""
import hashlib
import json
from uuid import UUID
from sqlalchemy import select
from journeyplus.models import AgentInteraction, now_utc
from .models import Artifact


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def aware(value):
    from datetime import timezone
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def parse_ref(ref):
    root, _, fragment = ref.partition('#')
    if not root.startswith('artifact:'):
        raise ValueError('Expected typed artifact reference')
    return UUID(root[9:]), fragment


class ArtifactStore:
    def __init__(self, factory):
        self.factory = factory

    def put(self, workspace_id, kind, payload, *, call_id=None, source_refs=None):
        with self.factory.begin() as s:
            return self.put_in(s, workspace_id, kind, payload, call_id=call_id, source_refs=source_refs)

    def put_in(self, s, workspace_id, kind, payload, *, call_id=None, source_refs=None):
        workspace = s.get(AgentInteraction, UUID(str(workspace_id)))
        if workspace is None or aware(workspace.expires_at) <= now_utc():
            raise LookupError('Workspace expired or missing')
        if len(json.dumps(payload, ensure_ascii=False, default=str).encode()) > 1_000_000:
            raise ValueError('Artifact exceeds one megabyte; split into referenced sections')
        row = Artifact(workspace_id=workspace.id, kind=kind, payload=payload,
            content_hash=digest(payload), source_refs=source_refs or [], created_by_call_id=call_id,
            expires_at=workspace.expires_at)
        s.add(row)
        s.flush()
        return 'artifact:'+str(row.id)

    def read(self, workspace_id, ref):
        identity, fragment = parse_ref(ref)
        with self.factory() as s:
            row = s.get(Artifact, identity)
            if row is None or row.workspace_id != UUID(str(workspace_id)) or aware(row.expires_at) <= now_utc():
                raise LookupError('Artifact missing, expired or outside workspace')
            payload = row.payload
            if fragment:
                kind, _, key = fragment.partition(':')
                collection = payload.get({'route': 'routes', 'step': 'steps', 'report': 'reports', 'section':'sections'}.get(kind, ''), {})
                if key not in collection:
                    raise LookupError('Artifact member does not exist')
                payload = collection[key]
            return {'ref': ref, 'kind': row.kind, 'payload': payload, 'source_refs': row.source_refs}

    def search(self, workspace_id, *, kind=None, limit=10, cursor=None, query=None):
        with self.factory() as s:
            stmt = select(Artifact).where(Artifact.workspace_id == UUID(str(workspace_id)), Artifact.expires_at > now_utc())
            if kind:
                stmt = stmt.where(Artifact.kind == kind)
            rows = list(s.scalars(stmt.order_by(Artifact.created_at, Artifact.id)))
            if query:
                rows = [r for r in rows if query.casefold() in json.dumps(r.payload, ensure_ascii=False).casefold()]
            from .pagination import page
            selected, next_cursor, total = page(rows, binding=[str(workspace_id), kind, query],
                identity=lambda row: str(row.id), cursor=cursor, limit=limit)
            return {'artifacts': [{'ref': 'artifact:'+str(r.id), 'kind': r.kind,
                                  'source_refs': r.source_refs, 'content_hash': r.content_hash} for r in selected],
                    'total': total, 'next_cursor': next_cursor}
