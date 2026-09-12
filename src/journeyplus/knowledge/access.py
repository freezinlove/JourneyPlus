"""Read-only access to published business knowledge, independent of Agent."""
from contextlib import contextmanager
from sqlalchemy import text


class KnowledgePort:
    def __init__(self,factory):self._factory=factory

    @staticmethod
    def activity_reader(session):
        from .reads import ActivityReadService
        return ActivityReadService(session)

    @staticmethod
    def current_version(session, identity):
        from .models import Activity
        row=session.get(Activity,identity)
        return str(row.current_version_id) if row and row.current_version_id else None

    def availability(self):
        from sqlalchemy import select, func
        from .models import MembershipProgram, MembershipTier, ActivityKnowledgeVersion
        with self.read() as session:
            programs=session.scalar(select(func.count()).select_from(MembershipProgram))
            tiers=session.scalar(select(func.count()).select_from(MembershipTier))
            published=session.scalar(select(func.count()).select_from(ActivityKnowledgeVersion).where(ActivityKnowledgeVersion.status=='PUBLISHED'))
        return {'status':'AVAILABLE' if programs and tiers and published else 'UNAVAILABLE',
                'program_count':programs,'tier_count':tiers,'published_version_count':published,
                'message':None if programs and tiers and published else
                    '当前服务尚未接入已发布的会籍匹配知识，暂不能查询匹配路线。旧版活动和简报数据不等于新版知识已接入。'}

    @contextmanager
    def read(self):
        with self._factory() as session:
            if session.bind.dialect.name=='postgresql':
                session.execute(text('SET TRANSACTION READ ONLY'))
                session.execute(text("SET LOCAL statement_timeout = '10s'"))
                session.execute(text("SET LOCAL lock_timeout = '10s'"))
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
