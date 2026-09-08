"""Interactive reviewer in the model seat; real harness/tools, zero LLM requests.

This is diagnostic execution, never a real-model acceptance result. Each model
input is exported before the reviewer submits a response through stdin.
"""
import argparse
import asyncio
import json
import hashlib
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from journeyplus.config import Settings
from journeyplus.agent.adapters.model import AgentModel, decode_wire_containers, inline_schema, native_names, wire_messages
from journeyplus.agent.composition import compose_business
from journeyplus.agent.harness.contracts import Capabilities, ModelEvent


class ReviewerModel:
    configuration_id = 'interactive-reviewer-v1-no-llm'
    protocol = 'native'
    # Reuse only the pure wire-size estimator; never instantiate an HTTP client.
    estimate_input = AgentModel.estimate_input
    estimate_final_input = AgentModel.estimate_final_input

    def __init__(self, output, reader):
        self.output = output
        self.reader = reader
        self.number = 0

    def capabilities(self):
        return Capabilities(native_tools=True, streaming=True, context_window=32768, max_output=4096)

    async def stream(self, messages, definitions, limits, cancel_token):
        self.number += 1
        names = native_names(definitions)
        request = {'mode': 'manual-review-not-model-acceptance', 'limits': limits,
                   'messages': wire_messages(messages, names),
                   'tools': [{'type': 'function', 'function': {'name': names[d.name],
                              'description': d.description, 'parameters': inline_schema(d.input_schema)}}
                             for d in definitions] if limits.get('tools_allowed',True) else []}
        path = self.output / f'request-{self.number:03d}.json'
        path.write_text(json.dumps(request, ensure_ascii=False, indent=2))
        print('REVIEW_INPUT ' + str(path), flush=True)
        raw=await self.reader.readline()
        (self.output / f'response-{self.number:03d}.raw').write_bytes(raw)
        response = json.loads(raw)
        (self.output / f'response-{self.number:03d}.json').write_text(json.dumps(response, ensure_ascii=False, indent=2))
        message_id = str(uuid4())
        if response.get('text'):
            yield ModelEvent(type='text_delta', message_id=message_id, text=response['text'])
        reverse = {wire: name for name, wire in names.items()}
        for call in response.get('calls', []):
            name=reverse.get(call['name'],call['name'])
            definition=next((item for item in definitions if item.name==name),None)
            arguments,_=decode_wire_containers(call['arguments'],definition.input_schema) if definition else (call['arguments'],[])
            yield ModelEvent(type='tool_call_ready', message_id=message_id, call_id=str(uuid4()),
                             name=name, arguments=arguments)
        yield ModelEvent(type='turn_end', finish_reason='tool_calls' if response.get('calls') else 'stop')


async def main(args):
    original = make_url(Settings.from_env().database_url)
    if (args.database == original.database or not args.database.startswith('journeyplus_eval_')
            or original.host not in {'localhost', '127.0.0.1'}):
        raise ValueError('Explicit local isolated evaluation database required')
    output = Path(args.output).resolve()
    if not output.is_relative_to((Path.cwd() / '.secrets').resolve()):
        raise ValueError('Evidence must remain under .secrets')
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('Preserve existing evidence; choose a new output directory')
    engine = create_engine(original.set(database=args.database))
    reader = asyncio.StreamReader()
    transport, _ = await asyncio.get_running_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    model = ReviewerModel(output, reader)
    runtime, store = compose_business(sessionmaker(engine, expire_on_commit=False), model, network_enabled=args.network)
    workspace = store.create()
    (output / 'manifest.json').write_text(json.dumps({'mode': 'manual-review-not-model-acceptance',
        'model_api_calls': 0, 'network_enabled': args.network, 'database_alias': args.database,
        'reviewer_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'workspace_id': workspace['id'],
        'source_files': {str(p):hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(Path('src/journeyplus').rglob('*'))
                         if p.is_file() and p.suffix in {'.py','.md','.js','.html','.css'}}}, indent=2))
    try:
        while True:
            print('USER_INPUT', flush=True)
            raw = (await reader.readline()).decode().strip()
            if not raw:
                break
            if raw == 'QUIT':
                break
            text = json.loads(raw)['text']
            current = store.read(workspace['id'])
            run = store.start(workspace['id'], text, str(uuid4()), current['revision'])
            await runtime.run(run['run_id'])
            _, status = store.events(workspace['id'], run['run_id'])
            history = store.load_context_index(workspace['id'])['messages']
            (output / 'history.json').write_text(json.dumps([m.model_dump(mode='json') for m in history], ensure_ascii=False, indent=2))
            print('TURN_STATUS ' + status, flush=True)
            if status != 'COMPLETED':
                print('REVIEW_STOPPED: incomplete run; late input cannot start another turn.', flush=True)
                break
    finally:
        transport.close()
        await runtime.services['research'].close()
        engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--network',action='store_true',help='Allow real public web tools; still no model API')
    asyncio.run(main(parser.parse_args()))
