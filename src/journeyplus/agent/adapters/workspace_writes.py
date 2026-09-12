"""Atomic workspace effects. Business services receive no session factory."""
from sqlalchemy import select, func
from .models import Artifact
from journeyplus.agent.harness.contracts import ToolResult


class WorkspaceWrites:
    def save_note(self, workspace_id, turn_id, call_id, expected_revision, content, source_message_refs):
        from journeyplus.agent.adapters.transactions import transaction
        with transaction(self.factory) as session:
            workspace = self.workspace(session, workspace_id, True)
            state = dict(workspace.state)
            if state['note_revision'] != expected_revision:
                return ToolResult.failure('CONFLICT', 'Note revision changed')
            if source_message_refs:
                # Validate on the transaction's own connection, avoiding nested
                # sessions and preserving the workspace lock throughout commit.
                from uuid import UUID
                from journeyplus.workspace_models import WorkspaceMessage
                found = set(map(str, session.scalars(select(WorkspaceMessage.id).where(
                    WorkspaceMessage.workspace_id == workspace.id,
                    WorkspaceMessage.id.in_([UUID(ref) for ref in source_message_refs])))))
                if set(source_message_refs) - found:
                    raise ValueError('Note source reference missing')
            ref = self.artifacts.put_in(session, workspace_id, 'NOTE', {
                'content': content, 'source_message_refs': source_message_refs,
                'origin_scope': 'Messages in the execution turn; not verified provenance of every note statement',
                'revision': expected_revision + 1}, call_id=call_id, turn_id=turn_id)
            state.update(note_revision=expected_revision + 1, note_ref=ref)
            workspace.state = state
        return ToolResult(data={'revision': expected_revision + 1, 'note_ref': ref}, artifact_refs=[ref])

    def save_presentation(self, workspace_id, turn_id, call_id, replace_ref, build):
        # Resolve referenced immutable objects before opening the write transaction.
        # A retry still validates its input; committed payloads remain authoritative.
        payload = build()
        from uuid import UUID
        from journeyplus.agent.adapters.transactions import transaction
        with transaction(self.factory) as session:
            workspace = self.workspace(session, workspace_id, True)
            old = session.scalar(select(Artifact).where(
                Artifact.workspace_id == workspace.id, Artifact.kind == 'PRESENTATION',
                Artifact.created_by_turn_id == UUID(turn_id), Artifact.created_by_call_id == call_id))
            if old:
                return 'artifact:' + str(old.id), old.payload
            revision = session.scalar(select(func.count()).select_from(Artifact).where(
                Artifact.workspace_id == workspace.id, Artifact.kind == 'PRESENTATION')) + 1
            receipt = {'revision': revision, **payload}
            ref = self.artifacts.put_in(session, workspace_id, 'PRESENTATION', receipt,
                                       call_id=call_id, turn_id=turn_id)
            state = dict(workspace.state)
            state['presentation_refs'] = [item for item in state['presentation_refs'] if item != replace_ref] + [ref]
            workspace.state = state
        return ref, receipt
