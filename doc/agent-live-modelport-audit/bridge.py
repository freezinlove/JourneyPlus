"""Replace only AgentModel.stream; launch the existing agent.server entry point.

Requests and manually supplied ModelEvent responses use files, never a second DB.
Inherited initialize() performs the existing echo probe through this same bridge.
"""
import asyncio
import json
import os
from pathlib import Path
from time import monotonic
from journeyplus.agent.adapters.model import AgentModel
from journeyplus.agent.harness.contracts import ModelEvent, ModelUnavailable

DIRECTORY = Path(os.environ['JOURNEYPLUS_MODELPORT_BRIDGE_DIR'])
DIRECTORY.mkdir(parents=True, exist_ok=True)

class LiveModelBridge(AgentModel):
    sequence = 0

    async def stream(self, messages, definitions, limits, cancel_token):
        self.sequence += 1
        identity = f'{self.sequence:03d}'
        payload = {'sequence': self.sequence, 'messages': [m.model_dump(mode='json') for m in messages],
                   'tools': [{'name': d.name, 'description': d.description, 'input_schema': d.input_schema} for d in definitions],
                   'limits': limits, 'protocol': self.protocol}
        (DIRECTORY / f'{identity}.request.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        response = DIRECTORY / f'{identity}.response.json'
        deadline = monotonic() + limits.get('timeout', 45)
        while not response.exists():
            if cancel_token.is_set(): return
            if monotonic() >= deadline:
                raise ModelUnavailable(code='MODELPORT_BRIDGE_RESPONSE_TIMEOUT')
            await asyncio.sleep(.1)
        for item in json.loads(response.read_text()):
            if cancel_token.is_set(): return
            yield ModelEvent.model_validate(item)

if __name__ == '__main__':
    import journeyplus.agent.server as server
    server.AgentModel = LiveModelBridge
    server.main()
