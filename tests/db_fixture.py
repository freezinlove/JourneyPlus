import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from journeyplus.models import Base

@pytest.fixture
def factory():
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    yield sessionmaker(engine,expire_on_commit=False)
    engine.dispose()
