"""Upgrade an explicitly named local evaluation database; never use .env target."""
import argparse
import os
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from journeyplus.config import Settings


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--database',required=True);args=parser.parse_args()
    if not args.database.startswith('journeyplus_eval_'):parser.error('Evaluation database prefix required')
    url=make_url(Settings.from_env().database_url).set(database=args.database)
    if url.host not in {'127.0.0.1','localhost','::1'}:parser.error('Only local PostgreSQL is allowed')
    if not url.drivername.startswith('postgresql'):parser.error('PostgreSQL required')
    engine=create_engine(url)
    with engine.connect() as connection:
        if connection.scalar(text('select current_database()'))!=args.database:raise RuntimeError('Database identity mismatch')
        before=connection.scalar(text('select version_num from alembic_version'))
    # env.py reads Settings.from_env and overrides Alembic's sqlalchemy.url.
    # Set its actual input, then verify the connected database after migration.
    os.environ['JOURNEYPLUS_DATABASE_URL']=url.render_as_string(hide_password=False)
    command.upgrade(Config('alembic.ini'),'head')
    with engine.connect() as connection:
        assert connection.scalar(text('select current_database()'))==args.database
        after=connection.scalar(text('select version_num from alembic_version'))
    engine.dispose();print({'database':args.database,'before':before,'after':after})


if __name__=='__main__':main()
