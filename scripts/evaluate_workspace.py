"""Run bounded workspace tasks against an explicitly selected isolated database.

Outputs record observations and assertion failures, not a claim of semantic
correctness. Review each task's source-grounded checks before accepting it.
"""
from argparse import ArgumentParser
from decimal import Decimal
import json
from pathlib import Path
from time import monotonic
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from journeyplus.config import Settings
from journeyplus.ai.provider import OpenAICompatibleProvider
from journeyplus.agent.workspace import WorkspaceService,holding_snapshot
from journeyplus.agent.workspace_contracts import MessageRequest


def assess(case,view,answers):
    expected=case['expect'];failures=[]
    reads=[sum(b.get('tool') in {'query_activity_materials','query_membership_routes'} for b in a.get('basis',[])) for a in answers]
    if expected.get('route_read') and not any(b.get('tool')=='query_membership_routes' for a in answers for b in a.get('basis',[])):failures.append('MISSING_ROUTE_EVALUATION')
    if expected.get('no_errors') and any(a.get('error') for a in answers):failures.append('RECOVERABLE_ERROR')
    if 'business_reads' in expected and sum(reads)!=expected['business_reads']:failures.append('BUSINESS_READ_COUNT')
    if 'min_business_reads' in expected and sum(reads)<expected['min_business_reads']:failures.append('MISSING_BUSINESS_READ')
    if 'last_business_reads' in expected and reads[-1]!=expected['last_business_reads']:failures.append('LAST_TURN_READ_COUNT')
    if any(a.get('model_calls',0)>3 or a.get('repair_calls',0)>1 for a in answers):failures.append('CALL_BUDGET')
    blocks=answers[-1].get('blocks',[])
    final_text=answers[-1].get('text','')
    import re
    if any(not re.search(pattern,final_text,re.I) for pattern in expected.get('final_text_matches',[])):
        failures.append('MISSING_REQUESTED_EXPLANATION')
    if any(value not in final_text for value in expected.get('final_text_contains',[])):failures.append('MISSING_REQUESTED_EXPLANATION')
    if any(value in final_text for value in expected.get('final_text_not_contains',[])):failures.append('UNRELATED_FACT_SCOPE')
    targets=[route.get('to','').casefold() for block in blocks for route in block.get('payload',{}).get('routes',[])]
    if any(not any(value.casefold() in target for target in targets) for value in expected.get('final_route_targets_include',[])):failures.append('MISSING_COMPARISON_TARGET')
    if expected.get('final_block_any') and not set(expected['final_block_any'])&{b['type'] for b in blocks}:failures.append('MISSING_RESPONSE_BLOCK')
    if expected.get('pending_kind') and (view.get('pending_action') or {}).get('kind')!=expected['pending_kind']:failures.append('MISSING_PROPOSAL')
    if expected.get('no_pending_holding') and (view.get('pending_action') or {}).get('kind') in {'HOLDING_SAVE','HOLDING_EDIT'}:failures.append('UNREQUESTED_HOLDING_PROPOSAL')
    if expected.get('research_must_be_disabled') and not any(b.get('tool')=='research_statusmatcher' and b.get('status')=='DISABLED' for a in answers for b in a.get('basis',[])):failures.append('MISSING_EXPLICIT_RESEARCH_GATE')
    for block in blocks:
        for route in block.get('payload',{}).get('routes',[]):
            if route['classification']!='MATCH':continue
            limit=expected.get('max_match_amount')
            if limit:
                amounts=[Decimal(v['amount']) for v in route['cost']['totals'] if v['currency']==limit['currency']]
                if sum(amounts)>Decimal(limit['amount']):failures.append('OVER_BUDGET_MATCH')
            if expected.get('matches_must_be_free') and not route['cost']['is_proven_free']:failures.append('PAID_MATCH_FOR_FREE_QUERY')
            if expected.get('matches_require_no_challenge') and route['challenge']!='NONE':failures.append('UNPROVEN_NO_CHALLENGE_MATCH')
    return sorted(set(failures))


def main():
    parser=ArgumentParser();parser.add_argument('--database',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--cases',help='Comma-separated task IDs');parser.add_argument('--repeat',type=int,default=1)
    parser.add_argument('--split',choices=['development','holdout'],default='development',help='Holdout must be explicitly selected after implementation freeze')
    args=parser.parse_args();settings=Settings.from_env();url=make_url(settings.database_url)
    if args.database==url.database or not args.database.startswith(('journeyplus_knowledge_','journeyplus_eval_')):
        parser.error('Use an explicitly isolated knowledge/evaluation database, never the configured default database')
    output=Path(args.output).resolve();private=(Path.cwd()/'.secrets').resolve()
    if not output.is_relative_to(private):parser.error('Store live evaluation results under .secrets')
    if not 1<=args.repeat<=3:parser.error('repeat must be between 1 and 3')
    fixture=json.loads(Path('tests/fixtures/workspace_evaluation/tasks.json').read_text())
    cases=[c for c in fixture['cases'] if c['split']==args.split]
    if args.cases:
        selected=set(args.cases.split(','));cases=[c for c in cases if c['id'] in selected]
        if {c['id'] for c in cases}!=selected:parser.error('Unknown task ID')
    engine=create_engine(url.set(database=args.database));factory=sessionmaker(engine,expire_on_commit=False)
    provider=OpenAICompatibleProvider(settings,timeout_seconds=45)
    service=WorkspaceService(factory,provider,researcher=None)
    results=[];output.parent.mkdir(parents=True,exist_ok=True)
    for repeat in range(args.repeat):
        for case in cases:
            start=monotonic();answers=[];record={'id':case['id'],'split':case['split'],'repeat':repeat+1,'review_required':case['review_checks']}
            try:
                with factory() as s:before=holding_snapshot(s)
                view=service.create();record['workspace_id']=view['id']
                for index,message in enumerate(case['messages']):
                    view=service.message(UUID(view['id']),MessageRequest(text=message,client_message_id=f'eval-{index}',expected_revision=view['revision']))
                    answers.append(view['messages'][-1])
                record['assertion_failures']=assess(case,view,answers)
                with factory() as s:
                    if holding_snapshot(s)!=before:record['assertion_failures'].append('UNEXPECTED_HOLDING_WRITE')
                record['turns']=[{'text':a.get('text'),'blocks':[b['type'] for b in a.get('blocks',[])],
                    'model_calls':a.get('model_calls'),'repair_calls':a.get('repair_calls'),'error':a.get('error'),
                    'grounding_issues':a.get('grounding_issues',[]),'basis':a.get('basis',[]),
                    'provider_metrics':[o.get('provider') for o in a.get('input_observations',[])]} for a in answers]
            except Exception as exc:record.update(assertion_failures=['RUN_FAILED'],error_type=type(exc).__name__)
            record['seconds']=round(monotonic()-start,2);results.append(record)
            output.write_text(json.dumps({'database':args.database,'model':provider.metadata.model,'research_enabled':False,
                'split':args.split,'holdout_sha256':fixture.get('holdout_policy',{}).get('sha256') if args.split=='holdout' else None,
                'results':results},ensure_ascii=False,indent=2))
            print(case['id'],record['assertion_failures'] or 'ASSERTIONS_PASS',record['seconds'],flush=True)
            if 'UNEXPECTED_HOLDING_WRITE' in record['assertion_failures']:raise RuntimeError('Unexpected holding write; stop evaluation and inspect isolated state')
    engine.dispose()


if __name__=='__main__':main()
