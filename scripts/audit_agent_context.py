"""Offline replay of saved conversations. Bytes/estimates are NOT provider usage."""
import argparse
import json
from pathlib import Path
from statistics import median

from journeyplus.agent.adapters.model import inline_schema, wire_messages, native_names
from journeyplus.agent.harness.context import project
from journeyplus.agent.harness.contracts import Capabilities, ModelMessage, Part
from journeyplus.agent.tools.registration import definitions


def audit(paths):
    tools = definitions({})
    names=native_names(tools)
    schemas = [{'type': 'function', 'function': {'name': names[d.name], 'description': d.description,
                'parameters': inline_schema(d.input_schema)}} for d in tools]
    instructions = Path('src/journeyplus/agent/instructions.md').read_text()
    system = ModelMessage(role='system', content=[Part(type='text', text=instructions)])
    capabilities = Capabilities(native_tools=True, streaming=True, context_window=32768, max_output=2048)
    size = lambda value: len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())
    rows = []
    for path in paths:
        record = json.loads(path.read_text())
        messages = [ModelMessage.model_validate(m) for m in record.get('messages', [])]
        for index, message in enumerate(messages):
            if message.role != 'assistant':
                continue
            try:
                selected = project([system, *messages[:index]], tools, capabilities)
                wire = wire_messages(selected,names)
                rows.append({'file': str(path), 'message_index': index,
                             'input_bytes': size({'messages': wire, 'tools': schemas}),
                             'tool_result_bytes': sum(size(m) for m in wire if m['role'] == 'tool')})
            except ValueError:
                rows.append({'file': str(path), 'message_index': index, 'error': 'context_limit'})
    sizes = [r['input_bytes'] for r in rows if 'input_bytes' in r]
    return {'offline_only': True, 'schema_bytes': size(schemas), 'instructions_bytes': len(instructions.encode()),
            'projected_requests': len(rows), 'context_errors': len(rows)-len(sizes),
            'input_bytes_median': median(sizes) if sizes else None,
            'input_bytes_total': sum(sizes), 'input_bytes_max': max(sizes, default=0), 'rows': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('evidence', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.evidence)
    with args.output.open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}))
