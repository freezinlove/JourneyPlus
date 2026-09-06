"""Read-only shadow inventory. Differences are observations, never automatic gold labels."""
from argparse import ArgumentParser
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from journeyplus.config import Settings
from journeyplus.product.opportunities import PersonalizedMatchService
from journeyplus.knowledge.compatibility import legacy_opportunity
from journeyplus.knowledge.routes import RouteQuery, RouteService


def compare(session):
    old = PersonalizedMatchService(session).read().model_dump(mode='json')
    new = RouteService(session).query(RouteQuery())
    edges = {}

    def visit(node):
        for edge in node['children']:
            key = (edge['source_node_id'], edge['target_node_id'])
            record = edges.setdefault(key, {'from':key[0], 'to':key[1], 'legacy_opportunities':set()})
            record['legacy_opportunities'].update(edge['opportunity_ids'])
            visit(edge['child'])

    for root in old['forest']['roots']:
        visit(root)
    fees = {(e['source_node_id'], e['target_node_id']):e['labels'] for e in old['edge_fees']}
    resolutions = {}
    for edge in edges.values():
        edge['legacy_opportunities'] = sorted(edge['legacy_opportunities'])
        for identity in edge['legacy_opportunities']:
            resolutions.setdefault(identity, legacy_opportunity(session, UUID(identity)))
        states = {resolutions[i]['status'] for i in edge['legacy_opportunities']}
        edge['classification'] = ('PUBLISHED_ACTIVITY_REQUIRES_SEMANTIC_COMPARISON' if 'RESOLVED' in states
            else 'PENDING_OFFICIAL_KNOWLEDGE' if 'NOT_PUBLISHED' in states
            else 'EXCLUDED_HISTORICAL_ARTICLE' if states == {'ARCHIVE_ONLY'} else 'UNRESOLVED_IDENTITY')
        edge['legacy_fee_labels'] = fees.get((edge['from'], edge['to']), [])
    steps = list(new['server_steps'].values())
    return {'generated_at':datetime.now(UTC).isoformat(), 'read_only':True,
        'limitations':['旧费用标签不是金标；不把所有差异归为纠错。',
            '旧图边和新多步骤路线不是同一计数单位。',
            '按明确旧ID对齐活动，等级／收费语义仍须核对证据，未按相似名称猜等级等价。',
            '隔离快照不证明官方活动今天仍开放；本报告不执行消费者切换。'],
        'counts':{'legacy_edges':len(edges),'legacy_fee_labels':len(fees),
            'new_routes':len(new['server_routes']),'new_shared_steps':len(steps),
            'legacy_edge_classifications':dict(Counter(e['classification'] for e in edges.values()))},
        'coverage':new['coverage'], 'versions':new['snapshot'],
        'identity_resolutions':resolutions, 'legacy_edges':list(edges.values()),
        'new_routes':list(new['server_routes'].values()), 'new_steps':steps}


def main():
    parser=ArgumentParser();parser.add_argument('--database',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();url=make_url(Settings.from_env().database_url)
    if args.database==url.database or not args.database.startswith(('journeyplus_knowledge_','journeyplus_eval_')):
        parser.error('Use an explicitly isolated evaluation database')
    output=Path(args.output).resolve()
    if not output.is_relative_to((Path.cwd()/'.secrets').resolve()) or output.exists():
        parser.error('Use a new file under .secrets; retain previous evidence')
    engine=create_engine(url.set(database=args.database))
    with Session(engine) as session:
        session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
        report=compare(session)
        session.rollback()
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as handle:
        output.chmod(0o600);json.dump(report,handle,ensure_ascii=False,indent=2)
    print(json.dumps(report['counts'],ensure_ascii=False));engine.dispose()


if __name__=='__main__':main()
