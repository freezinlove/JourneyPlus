"""Normal product CLI with read-only logging around the real provider adapter.

Does not provide model responses or change tools/DB/configuration. HTTP headers
(including credentials) are never recorded. Request bodies contain conversation
data. Run explicitly for an audit; output is local and excluded from Git.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from journeyplus.agent.adapters.model import AgentModel

OUTPUT_ROOT = Path(os.environ.get(
    'JOURNEYPLUS_AGENT_AUDIT_DIR',
    str(Path(__file__).resolve().parents[1] / '.local' / 'agent-audits'),
)).expanduser()


class ObservedModel(AgentModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.output_dir = OUTPUT_ROOT / (
            datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex
        ) / 'exchange'
        self.output_dir.mkdir(parents=True, exist_ok=False)
        self.sequence = 0
        async def observe_request(request):
            payload = json.loads(request.content)
            (self.output_dir / f'{self.sequence:03d}.wire.json').write_text(
                json.dumps(payload, ensure_ascii=False, indent=2))
        self.client.event_hooks['request'].append(observe_request)

    async def stream(self, messages, definitions, limits, cancel_token):
        self.sequence += 1
        identity = f'{self.sequence:03d}'
        (self.output_dir / f'{identity}.input.json').write_text(json.dumps({
            'messages': [m.model_dump(mode='json') for m in messages],
            'tools': [{'name': d.name, 'description': d.description, 'input_schema': d.input_schema}
                      for d in definitions],
            'limits': limits, 'protocol': self.protocol,
            'explicit_cache': self.config.explicit_cache,
        }, ensure_ascii=False, indent=2))
        events = []
        metric_count = len(self.metrics)
        try:
            async for event in super().stream(messages, definitions, limits, cancel_token):
                events.append(event.model_dump(mode='json'))
                yield event
        finally:
            (self.output_dir / f'{identity}.output.json').write_text(json.dumps(events, ensure_ascii=False, indent=2))
            if len(self.metrics) > metric_count:
                (self.output_dir / f'{identity}.metrics.json').write_text(json.dumps(self.metrics[-1], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    import journeyplus.agent.adapters.model as adapter
    adapter.AgentModel = ObservedModel
    from journeyplus.cli import main
    raise SystemExit(main())
