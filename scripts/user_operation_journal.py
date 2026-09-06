"""Explicit operator export/replay. Replay validates and rolls back by default."""
from argparse import ArgumentParser
from pathlib import Path
import json
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from journeyplus.config import Settings
from journeyplus.knowledge.user_journal import export_operations,replay_operations


def main():
    parser=ArgumentParser()
    parser.add_argument('action',choices=['export','replay']);parser.add_argument('--database',required=True)
    parser.add_argument('--file',required=True);parser.add_argument('--after-sequence',type=int,default=0)
    parser.add_argument('--apply',action='store_true',help='Commit verified replay; requires maintenance write pause')
    args=parser.parse_args();settings=Settings.from_env();path=Path(args.file).resolve()
    if not path.is_relative_to((Path.cwd()/'.secrets').resolve()):parser.error('Journal files must remain under .secrets')
    if args.after_sequence<0:parser.error('Checkpoint sequence must be nonnegative')
    if args.apply and (args.action!='replay' or not (settings.knowledge_user_writes_paused or settings.knowledge_read_mode=='rollback')):
        parser.error('--apply requires replay and the maintenance/rollback write pause')
    engine=create_engine(make_url(settings.database_url).set(database=args.database))
    with Session(engine) as session:
        if args.action=='export':
            operations=export_operations(session,args.after_sequence)
            path.parent.mkdir(parents=True,exist_ok=True)
            # Never silently overwrite an earlier recovery artifact.
            with path.open('x') as file:json.dump(operations,file,ensure_ascii=False,indent=2)
            path.chmod(0o600)
            print(json.dumps({'exported':len(operations),'last_sequence':operations[-1]['sequence'] if operations else args.after_sequence}))
        else:
            result=replay_operations(session,json.loads(path.read_text()))
            if args.apply:session.commit()
            else:session.rollback()
            print(json.dumps({**result,'committed':args.apply}))
    engine.dispose()


if __name__=='__main__':main()
