"""Read-only access to published business knowledge, independent of Agent."""
from contextlib import contextmanager
from sqlalchemy import text


class KnowledgePort:
    def __init__(self,factory):self._factory=factory

    @contextmanager
    def read(self):
        with self._factory() as session:
            if session.bind.dialect.name=='postgresql':session.execute(text('SET TRANSACTION READ ONLY'))
            try:
                yield session
                if session.new or session.dirty or session.deleted:
                    raise RuntimeError('Knowledge read port attempted mutation')
            finally:session.rollback()

    def read_reference(self,ref):
        from uuid import UUID
        from .reads import ActivityReadService
        from .models import MembershipProgram,MembershipTier
        kind,separator,identity=ref.partition(':')
        with self.read() as s:
            if kind=='activity':
                identity,version_separator,version=identity.partition('@')
                if not version_separator:raise ValueError('Published activity reference requires a version')
                return ActivityReadService(s).detail(UUID(identity),UUID(version))
            model={'program':MembershipProgram,'tier':MembershipTier}.get(kind)
            if model is None:raise ValueError('Unsupported published reference')
            row=s.get(model,UUID(identity))
            if row is None:raise LookupError('Published identity not found')
            return {'ref':ref,'name':row.display_name}
