"""Scoped temporary objects; a reference cannot grant cross-workspace access."""
from journeyplus.agent.adapters.transactions import read_session
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

    def put(self, workspace_id, kind, payload, *, call_id=None, turn_id=None, source_refs=None):
        from journeyplus.agent.adapters.transactions import transaction
        with transaction(self.factory) as s:
            return self.put_in(s, workspace_id, kind, payload, call_id=call_id, turn_id=turn_id, source_refs=source_refs)

    def put_in(self, s, workspace_id, kind, payload, *, call_id=None, turn_id=None, source_refs=None):
        workspace = s.get(AgentInteraction, UUID(str(workspace_id)))
        if workspace is None or aware(workspace.expires_at) <= now_utc():
            raise LookupError('Workspace expired or missing')
        if len(json.dumps(payload, ensure_ascii=False, default=str).encode()) > 1_000_000:
            raise ValueError('Artifact exceeds one megabyte; split into referenced sections')
        row = Artifact(workspace_id=workspace.id, kind=kind, payload=payload,
            content_hash=digest(payload), source_refs=source_refs or [], created_by_call_id=call_id, created_by_turn_id=UUID(str(turn_id)) if turn_id else None,
            expires_at=workspace.expires_at)
        s.add(row)
        s.flush()
        return 'artifact:'+str(row.id)

    def put_once(self, workspace_id, kind, payload, *, call_id=None, turn_id=None, source_refs=None):
        """Reuse an identical immutable view while this workspace remains alive."""
        from journeyplus.agent.adapters.transactions import transaction
        with transaction(self.factory) as session:
            workspace = session.get(AgentInteraction, UUID(str(workspace_id)), with_for_update=True)
            if workspace is None or aware(workspace.expires_at) <= now_utc():
                raise LookupError('Workspace expired or missing')
            old = session.scalar(select(Artifact).where(
                Artifact.workspace_id == workspace.id, Artifact.kind == kind,
                Artifact.content_hash == digest(payload), Artifact.source_refs == (source_refs or []),
                Artifact.expires_at > now_utc())
                .order_by(Artifact.created_at, Artifact.id).limit(1))
            if old and old.source_refs == (source_refs or []):
                return 'artifact:'+str(old.id)
            return self.put_in(session, workspace_id, kind, payload, call_id=call_id,
                               turn_id=turn_id, source_refs=source_refs)

    def read(self, workspace_id, ref):
        identity, fragment = parse_ref(ref)
        with read_session(self.factory) as s:
            workspace=s.get(AgentInteraction,UUID(str(workspace_id)))
            if workspace is None or aware(workspace.expires_at)<=now_utc():raise LookupError('Workspace expired or outside user scope')
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
        with read_session(self.factory) as s:
            workspace=s.get(AgentInteraction,UUID(str(workspace_id)))
            if workspace is None or aware(workspace.expires_at)<=now_utc():raise LookupError('Workspace expired or outside user scope')
            stmt = select(Artifact).where(Artifact.workspace_id == UUID(str(workspace_id)), Artifact.expires_at > now_utc())
            if kind:
                stmt = stmt.where(Artifact.kind == kind)
            if query:
                from .search import json_search
                predicate=json_search(Artifact.payload,query,s.bind.dialect.name)
                if predicate is not None:stmt=stmt.where(predicate)
                matches=[row.id for row in s.scalars(stmt) if query.casefold() in json.dumps(row.payload,ensure_ascii=False).casefold()]
                stmt=stmt.where(Artifact.id.in_(matches))
            # Pagination and listing need no raw material/report/tool-result body.
            rows=list(s.execute(stmt.with_only_columns(Artifact.id,Artifact.kind,Artifact.source_refs,
                               Artifact.content_hash,Artifact.created_at).order_by(Artifact.created_at,Artifact.id)))
            from .pagination import page
            selected, next_cursor, total = page(rows, binding=[str(workspace_id), kind, query],
                identity=lambda row: str(row.id), cursor=cursor, limit=limit)
            return {'artifacts': [{'ref': 'artifact:'+str(r.id), 'kind': r.kind,
                                  'source_refs': r.source_refs, 'content_hash': r.content_hash} for r in selected],
                    'total': total, 'next_cursor': next_cursor}
