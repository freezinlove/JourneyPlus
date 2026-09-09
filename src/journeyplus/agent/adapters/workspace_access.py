"""Capabilities exposed to tools; no factory, raw session or runtime mutation."""
class WorkspaceAccess:
    def __init__(self, store):
        self._store = store

    def history(self, workspace_id, query=None, refs=None, cursor=None, limit=10):
        return self._store.history(workspace_id, query, refs, cursor, limit)

    def user_message_refs(self,workspace_id,turn_id):
        return self._store.user_message_refs(workspace_id,turn_id)

    def load_context_index(self, workspace_id):
        return self._store.load_context_index(workspace_id)

    def validate_reference(self, workspace_id, ref):
        return self._store.validate_reference(workspace_id, ref)

    def save_note(self, workspace_id, turn_id, call_id, expected_revision, content, source_message_refs):
        return self._store.save_note(workspace_id, turn_id, call_id, expected_revision, content, source_message_refs)

    def save_presentation(self, workspace_id, turn_id, call_id, replace_ref, build):
        return self._store.save_presentation(workspace_id, turn_id, call_id, replace_ref, build)

    def committed_call_result(self, workspace_id, turn_id, call_id):
        return self._store.committed_call_result(workspace_id, turn_id, call_id)
