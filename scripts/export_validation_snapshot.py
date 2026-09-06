"""Export bounded public activity facts, never user holdings or workspace history."""
from argparse import ArgumentParser
from pathlib import Path
from uuid import UUID
import json
import re
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from journeyplus.config import Settings
from journeyplus.knowledge.routes import RouteService,RouteQuery
from journeyplus.knowledge.reads import ActivityReadService
from journeyplus.knowledge.references import ReferenceMap
from journeyplus.knowledge.packets import project_model_packet


def main():
    parser=ArgumentParser();parser.add_argument('--database',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();url=make_url(Settings.from_env().database_url)
    if args.database==url.database or not args.database.startswith('journeyplus_knowledge_'):parser.error('Use the isolated validation database')
    with Session(create_engine(url.set(database=args.database))) as session:
        # Synthetic test assumption, explicitly independent of saved holdings.
        query=RouteQuery(starting_tier_ids=[UUID('e0cf2d95-e71a-47a6-a5d5-fad75019f833')],use_saved_holdings=False,max_amount=100,currency='USD')
        full=RouteService(session).query(query)
        full['data']['cards']=list(full['server_routes'].values());full['data']['steps']=full['server_steps']
        full['coverage'].update(returned_count=len(full['server_routes']),presentation_has_more=False)
        reader=ActivityReadService(session);activities=[]
        for name in ['Royal Jordanian','Club Avolta','Malaysia Airlines Enrich','Flying Blue']:
            for activity in reader.locate(text=name):
                detail=reader.detail(activity.id)
                if 'version_ref' not in detail:continue
                activities.append({k:detail[k] for k in ['ref','version_ref','name','edition','kind','published_at','freshness','card','sources']})
        refs=ReferenceMap({})
        snapshot={'schema_version':1,'captured_on':'2026-09-06','purpose':'Frozen development regression facts, not current offers or a production seed',
                  'privacy':'Public source facts only; no saved holdings, workspace messages, email content, tokens or StatusMatcher reports. Identifiers are local fixture aliases.',
                  'assumption':'Synthetic Air Canada Aeroplan Elite 50K, USD100 cap, no saved holdings',
                  'routes':refs.encode(project_model_packet(full)),'activities':refs.encode(activities),
                  'defects':{'unstructured_input':'tests/fixtures/workspace_evaluation/tasks.json: development chat and clarification cases',
                             'fee_scope_and_unknown':'tests/test_knowledge_routes.py',
                             'alternative_paths_and_pagination':'tests/test_knowledge_pagination.py',
                             'experience_permission_visibility':'tests/test_research_intent.py'}}
    # Legacy edition keys can embed IDs inside a longer string.
    encoded=json.dumps(snapshot,ensure_ascii=False,indent=2)
    encoded=re.sub(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b',lambda match:refs.encode(match[0]),encoded)
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(encoded+'\n')
    print({'route_count':len(snapshot['routes']['data']['cards']),'activity_count':len(activities),'bytes':out.stat().st_size})


if __name__=='__main__':main()
