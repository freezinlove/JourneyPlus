"""Agent-only views of archived workflow data; persisted history stays intact."""
import json
import re
from sqlalchemy import select
from journeyplus.lifecycle.visibility import is_ended
from journeyplus.models import StatusEvent, FactSetRecord, ArticleOpportunityRecord
from journeyplus.agent.harness.contracts import Part, ToolResult
from .workspace_access import WorkspaceAccess

NOTICE = '活动已结束或资料已归档；此历史内容不再提供给 Agent，请重新查询当前活动。'
_UUID = re.compile(r'(?<![0-9a-f])[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}(?![0-9a-f])', re.I)
_ARTIFACT = re.compile(r'artifact:[0-9a-f-]{36}(?:#[a-z]+:[a-zA-Z0-9_-]+)?', re.I)


class ActivityViews:
    def __init__(self, knowledge, artifacts, store):
        self.knowledge, self.artifacts, self.store = knowledge, artifacts, store

    def checker(self, workspace_id):
        # Select identity/lifecycle metadata, never load archived facts or raw text.
        from sqlalchemy.orm import load_only
        with self.knowledge.read() as session:
            events = session.scalars(select(StatusEvent).options(load_only(
                StatusEvent.id, StatusEvent.archived_at, StatusEvent.lifecycle_status,
                StatusEvent.application_start_at, StatusEvent.application_deadline_at)))
            ended = {event.id for event in events if is_ended(event)}
            ids = {str(identity) for identity in ended}
            if ended:
                ids.update(str(identity) for identity in session.scalars(
                    select(FactSetRecord.id).where(FactSetRecord.event_id.in_(ended))))
            articles = session.scalars(select(ArticleOpportunityRecord).options(load_only(
                ArticleOpportunityRecord.id, ArticleOpportunityRecord.archived_at,
                ArticleOpportunityRecord.lifecycle_status, ArticleOpportunityRecord.application_start_at,
                ArticleOpportunityRecord.application_deadline_at, ArticleOpportunityRecord.visibility_until_at,
                ArticleOpportunityRecord.visibility_policy, ArticleOpportunityRecord.archive_reason)))
            ids.update(str(article.id) for article in articles if is_ended(article))
        if not ids:
            return lambda value: False
        memo = {}
        def blocked(value, trail=frozenset()):
            encoded = json.dumps(value, ensure_ascii=False, default=str)
            if ids.intersection(match.lower() for match in _UUID.findall(encoded)):
                return True
            for ref in _ARTIFACT.findall(encoded):
                ref = ref.partition('#')[0]
                if ref in trail:
                    continue
                if ref not in memo:
                    try:
                        artifact = self.artifacts.read(workspace_id, ref)
                    except (ValueError, LookupError):
                        memo[ref] = False  # Actual retrieval still enforces scope and expiry.
                    else:
                        memo[ref] = blocked({k:artifact[k] for k in ('payload','source_refs')}, trail | {ref})
                if memo[ref]:
                    return True
            return False
        messages = self.store.load_context_index(workspace_id)['messages']
        groups = []
        for message in messages:
            if message.role == 'user' or not groups:
                groups.append([])
            groups[-1].append(message)
        for group in groups:
            if any(blocked(m.model_dump(mode='json')) for m in group if m.role != 'user'):
                ids.update(m.id for m in group if m.id)
                memo.clear()
        return blocked

    def context(self, workspace_id, messages, note=None, focus=None):
        blocked = self.checker(workspace_id)
        groups = []
        for message in messages:
            if message.role == 'user' or not groups:
                groups.append([])
            groups[-1].append(message)
        hidden_messages = set()
        result = []
        for group in groups:
            unavailable = any(blocked(m.model_dump(mode='json')) for m in group if m.role != 'user')
            if unavailable:
                hidden_messages.update(m.id for m in group if m.id)
            for original in group:
                message = original.model_copy(deep=True)
                if unavailable and message.role != 'user':
                    message.metadata = {k:v for k,v in message.metadata.items() if k in {'turn_id','interrupted'}}
                    for index, part in enumerate(message.content):
                        if part.type == 'tool_result':
                            part.result = ToolResult.failure('ACTIVITY_ENDED', NOTICE, status='UNAVAILABLE').model_dump(mode='json')
                        elif part.type == 'tool_call':
                            part.arguments = {}
                        elif part.type == 'text':
                            part.text = NOTICE
                        elif part.type == 'artifact':
                            message.content[index] = Part(type='text',text=NOTICE)
                result.append(message)
        if note and (blocked(note) or hidden_messages):
            note = {'notice':NOTICE}
        if focus and blocked(focus):
            focus = {'notice':NOTICE}
        return result, note, focus

    def result(self, workspace_id, result):
        if self.checker(workspace_id)(result.model_dump(mode='json')):
            return ToolResult(call_id=result.call_id, status='UNAVAILABLE',
                error={'code':'ACTIVITY_ENDED','message':NOTICE})
        return result


class ActiveArtifacts:
    def __init__(self, original, views):
        self.original, self.views = original, views

    def __getattr__(self, name):
        return getattr(self.original, name)

    def read(self, workspace_id, ref):
        value = self.original.read(workspace_id, ref)
        if value['kind'] == 'NOTE':
            messages = self.views.store.load_context_index(workspace_id)['messages']
            _, projected, _ = self.views.context(workspace_id, messages, value['payload'])
            return {**value, 'payload':projected}
        if self.views.checker(workspace_id)(value):
            raise LookupError(NOTICE)
        return value

    def search(self, workspace_id, **filters):
        result = self.original.search(workspace_id, **filters)
        blocked = self.views.checker(workspace_id)
        result['artifacts'] = [({'ref':row['ref'], 'kind':'UNAVAILABLE', 'notice':NOTICE}
                                if blocked(row) else row) for row in result['artifacts']]
        return result


class ActiveWorkspace(WorkspaceAccess):
    def __init__(self, store, views):
        super().__init__(store)
        self.views = views

    def validate_reference(self, workspace_id, ref):
        if ref.startswith('artifact:'):
            return ActiveArtifacts(self.views.artifacts, self.views).read(workspace_id, ref)
        return super().validate_reference(workspace_id, ref)

    def history(self, workspace_id, query=None, refs=None, cursor=None, limit=10):
        data = super().history(workspace_id, query, refs, cursor, limit)
        # Classify whole original turns, even when the requested page starts midway.
        messages = self._store.load_context_index(workspace_id)['messages']
        projected, _, _ = self.views.context(workspace_id, messages)
        by_id = {m.id:m.model_dump(mode='json') for m in projected}
        data['messages'] = [by_id.get(m.get('id'),m) for m in data['messages']]
        return data
