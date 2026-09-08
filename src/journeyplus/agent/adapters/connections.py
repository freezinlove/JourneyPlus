"""Optional credentials limited to formal knowledge in the same logical database."""
import os
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


def knowledge_factory(user_factory):
    configured=os.environ.get('JOURNEYPLUS_AGENT_KNOWLEDGE_DATABASE_URL')
    if not configured:return user_factory,None
    source=user_factory.kw['bind'].url
    target=make_url(configured)
    if (source.get_backend_name(),source.host,source.port,source.database)!=(
        target.get_backend_name(),target.host,target.port,target.database):
        raise ValueError('Knowledge credentials must address the same logical database')
    engine=create_engine(target,pool_pre_ping=True,pool_timeout=10)
    return sessionmaker(engine,expire_on_commit=False),engine.dispose
