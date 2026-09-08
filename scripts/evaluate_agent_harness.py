"""Real model evaluation against an explicitly isolated database. No silent semantic pass."""
import argparse
import asyncio
import hashlib
import json
import re
import subprocess
from pathlib import Path
from time import monotonic
from sqlalchemy import create_engine,select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from journeyplus.config import Settings
from journeyplus.models import UserBusinessOperation
from journeyplus.agent.adapters.config import AgentConfig
from journeyplus.agent.adapters.model import AgentModel
from journeyplus.agent.composition import compose_business
from journeyplus.agent.adapters.models import RunCheckpoint
from uuid import UUID


def estimated_cost(metrics, input_price, output_price, input_limit=60000):
    """Conservative uncached list-price estimate, not a provider billing receipt."""
    return sum((item.get('usage') or {}).get('prompt_tokens', input_limit)*input_price +
               (item.get('usage') or {}).get('completion_tokens', 12000)*output_price
               for item in metrics)/1_000_000


async def evaluate(args):
    initial=Settings.from_env();url=make_url(initial.database_url)
    if args.database==url.database or not args.database.startswith('journeyplus_eval_'):
        raise ValueError('Explicit isolated evaluation database required')
    output=Path(args.output).resolve()
    if not output.is_relative_to((Path.cwd()/'.secrets').resolve()):
        raise ValueError('Private evaluation evidence must remain under .secrets')
    output.mkdir(parents=True,exist_ok=True)
    if any(output.iterdir()):raise ValueError('Evidence directory already used; choose a new attempt directory')
    fixture=Path(args.fixture)
    cases=json.loads(fixture.read_text())['cases']
    cases=[c for c in cases if c['split']==args.split and (not args.cases or c['id'] in args.cases.split(','))]
    if not cases:raise ValueError('No evaluation cases selected')
    if args.max_estimated_cost_yuan is not None and (args.input_price is None or args.output_price is None):
        raise ValueError('Cost ceiling requires explicit verified per-million-token prices')
    if any(value is not None and (value<0 or not __import__('math').isfinite(value))
           for value in (args.input_price,args.output_price,args.max_estimated_cost_yuan)):
        raise ValueError('Cost policy requires finite non-negative values')
    config=AgentConfig(args.model or initial.ai_model,initial.ai_base_url,initial.ai_api_key,32768,protocol=args.protocol,thinking=args.thinking,temperature=args.temperature,
                       input_token_soft=args.soft_input_tokens,input_token_limit=args.max_input_tokens)
    factory=sessionmaker(create_engine(url.set(database=args.database)),expire_on_commit=False)
    model=AgentModel(config)
    try:await model.initialize()
    except Exception:
        (output/'startup-failure.json').write_text(json.dumps({'model':config.model,'protocol':args.protocol,'probe':model.probe_diagnostics,'metrics':model.metrics},indent=2))
        await model.close();factory.kw['bind'].dispose()
        raise RuntimeError('Model capability probe failed; diagnostic evidence preserved') from None
    runtime,store=compose_business(factory,model,network_enabled=True)
    manifest={'database_alias':args.database,'model':config.model,'protocol':model.protocol,'thinking':config.thinking,
              'temperature':config.temperature,'context_window':config.context_window,'fixture_sha256':hashlib.sha256(fixture.read_bytes()).hexdigest(),
              'split':args.split,'repeat':args.repeat,'semantic_review_required':True,'probe':model.probe_diagnostics,
              'input_token_soft':config.input_token_soft,'input_token_limit':config.input_token_limit}
    if (output/'manifest.json').exists():raise ValueError('Evidence directory already used; preserve earlier attempts')
    source_files=sorted(p for root in ('src/journeyplus','migrations/versions') for p in Path(root).rglob('*') if p.is_file() and p.suffix in {'.py','.md','.js','.html','.css'})
    manifest['source_files']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    manifest['source_sha256']=hashlib.sha256(json.dumps(manifest['source_files'],sort_keys=True).encode()).hexdigest()
    import tarfile
    with tarfile.open(output/'source.tar.gz','w:gz') as archive:
        for path in source_files:archive.add(path,arcname=str(path))
    manifest['fresh_case_databases']=args.fresh_cases
    manifest['cost_policy']={'input_yuan_per_million':args.input_price,'output_yuan_per_million':args.output_price,
                             'ceiling_yuan':args.max_estimated_cost_yuan,'estimate_only':True,'cache_discounts_applied':False}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2))
    try:
        for repeat in range(args.repeat):
            for case in cases:
                if args.fresh_cases:
                    if url.host not in {'localhost','127.0.0.1'}:raise ValueError('Local test database required')
                    name=f'{args.database}_{case["id"].lower()}_{repeat+1}'
                    if not re.fullmatch(r'journeyplus_eval_[a-z0-9_]{1,45}',name):raise ValueError('Invalid isolated database name')
                    subprocess.run(['docker','compose','exec','-T','postgres','createdb','-U','journeyplus','-T',args.database,name],check=True,capture_output=True)
                    factory=sessionmaker(create_engine(url.set(database=name)),expire_on_commit=False)
                    await runtime.services['research'].close()
                    runtime,store=compose_business(factory,model,network_enabled=True)
                record={'id':case['id'],'repeat':repeat+1,'input':case['messages'],'expect':case['expect'],'turns':[],'assertion_failures':[],'semantic_review':'PENDING','database_alias':name if args.fresh_cases else args.database}
                started=monotonic();metric_start=len(model.metrics)
                with factory() as s:before=set(s.scalars(select(UserBusinessOperation.operation_id)))
                workspace=store.create()
                for index,message in enumerate(case['messages']):
                    if args.max_estimated_cost_yuan is not None:
                        # Reserve a complete turn's hard token budget before starting it.
                        cost=estimated_cost(model.metrics,args.input_price,args.output_price,args.max_input_tokens)
                        reserve=(args.max_input_tokens*args.input_price+12000*args.output_price)/1_000_000
                        if cost+reserve>args.max_estimated_cost_yuan:
                            record['assertion_failures'].append('EVALUATION_COST_CEILING')
                            (output/f"{case['id']}-{repeat+1}.json").write_text(json.dumps(record,ensure_ascii=False,indent=2))
                            print('Stopped before next turn: evaluation cost ceiling',flush=True)
                            return
                    current=store.read(workspace['id'])
                    run=store.start(workspace['id'],message,f'eval-{repeat}-{index}',current['revision'])
                    turn_start=monotonic();turn_metric_start=len(model.metrics)
                    await runtime.run(run['run_id'])
                    events,status=store.events(workspace['id'],run['run_id'])
                    with factory() as s:checkpoint=s.get(RunCheckpoint,UUID(run['run_id']));budget=checkpoint.remaining_budget
                    for key,maximum in budget.get('hard',{}).items():
                        if budget.get(key,0)>maximum:record['assertion_failures'].append(f'TURN_{index}_HARD_BUDGET_{key}')
                    record['turns'].append({'budget':budget,'model_metrics':model.metrics[turn_metric_start:],'run_id':run['run_id'],'status':status,'elapsed_seconds':monotonic()-turn_start,'events':events})
                    if asyncio.current_task().cancelling():
                        record['assertion_failures'].append('EVALUATION_INTERRUPTED')
                        (output/f"{case['id']}-{repeat+1}.json").write_text(json.dumps(record,ensure_ascii=False,indent=2))
                        raise asyncio.CancelledError
                    if status!='COMPLETED':record['assertion_failures'].append(f'TURN_{index}_{status}')
                history=store.load_context_index(workspace['id'])['messages']
                record['messages']=[m.model_dump(mode='json') for m in history]
                calls=[p for m in history for p in m.content if p.type=='tool_call']
                record['model_metrics']=model.metrics[metric_start:]
                with factory() as s:after=set(s.scalars(select(UserBusinessOperation.operation_id)))
                record['journal_delta']=len(after-before)
                from journeyplus.agent.evaluation import assess_case
                record['assertion_failures'].extend(assess_case(case['expect'],history,after!=before))
                record['elapsed_seconds']=monotonic()-started
                (output/f"{case['id']}-{repeat+1}.json").write_text(json.dumps(record,ensure_ascii=False,indent=2))
                factory.kw['bind'].dispose()
                print(case['id'],repeat+1,'assertions='+str(record['assertion_failures']),round(record['elapsed_seconds'],1),flush=True)
    finally:
        if args.input_price is not None and args.output_price is not None:
            (output/'cost-estimate.json').write_text(json.dumps({'estimated_yuan':estimated_cost(model.metrics,args.input_price,args.output_price,args.max_input_tokens),
                'input_yuan_per_million':args.input_price,'output_yuan_per_million':args.output_price,'requests':len(model.metrics),
                'actual_bill':False,'cache_discounts_applied':False},indent=2))
        await model.close();await runtime.services['research'].close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--split',choices=['development','holdout'],default='development')
    parser.add_argument('--cases')
    parser.add_argument('--repeat',type=int,choices=[1,2],default=1)
    parser.add_argument('--fixture',default='tests/fixtures/agent_harness/cases.json')
    parser.add_argument('--model',help='Explicit Agent-only model override')
    parser.add_argument('--protocol',choices=['auto','native','json'],default='auto')
    parser.add_argument('--thinking',action='store_true')
    parser.add_argument('--fresh-cases',action='store_true',help='Clone the explicitly provided local evaluation template for every case-run')
    parser.add_argument('--temperature',type=float,default=.2)
    parser.add_argument('--soft-input-tokens',type=int,default=45000)
    parser.add_argument('--max-input-tokens',type=int,default=60000)
    parser.add_argument('--input-price',type=float,help='Verified input yuan per million tokens for this endpoint')
    parser.add_argument('--output-price',type=float,help='Verified output yuan per million tokens for this endpoint')
    parser.add_argument('--max-estimated-cost-yuan',type=float,help='Stop before a turn if its reserved cost would exceed this batch ceiling')
    asyncio.run(evaluate(parser.parse_args()))


if __name__=='__main__':main()
