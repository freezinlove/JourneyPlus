"""Resource accounting uses provider usage when present, explicit estimates otherwise."""
from dataclasses import dataclass, field
from time import monotonic
import json


@dataclass
class Budget:
    started: float = field(default_factory=monotonic)
    requests: int = 0
    tools: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated: bool = False
    soft: dict = field(default_factory=lambda: dict(seconds=120, requests=10, tools=20, input_tokens=45000, output_tokens=8000))
    hard: dict = field(default_factory=lambda: dict(seconds=180, requests=14, tools=28, input_tokens=60000, output_tokens=12000))
    notified: bool = False
    finalizing: bool = False
    model_configuration_id: str | None = None
    repeat_state: dict = field(default_factory=dict)
    completion_failures: int = 0

    def values(self):
        return dict(seconds=monotonic()-self.started, requests=self.requests, tools=self.tools,
                    input_tokens=self.input_tokens, output_tokens=self.output_tokens)

    def reached(self, level):
        return any(self.values()[key] >= value for key, value in getattr(self, level).items())

    def usage(self, usage, input_estimate, output_estimate):
        usage = usage or {}
        incoming = usage.get('input', usage.get('prompt_tokens'))
        outgoing = usage.get('output', usage.get('completion_tokens'))
        self.estimated |= incoming is None or outgoing is None
        self.input_tokens += incoming if incoming is not None else input_estimate
        self.output_tokens += outgoing if outgoing is not None else output_estimate

    def limits(self, capabilities):
        return {'max_output': max(0, min(4096, capabilities.max_output,
                                         self.hard['output_tokens']-self.output_tokens)),
                'tools_allowed': not self.finalizing,
                'timeout': max(0, min(45, self.hard['seconds']-(monotonic()-self.started)))}

    def snapshot(self):
        return {**self.values(), 'estimated': self.estimated, 'soft': self.soft, 'hard': self.hard,
                'notified': self.notified,'finalizing':self.finalizing,'model_configuration_id':self.model_configuration_id,
                'repeat_state':dict(self.repeat_state), 'completion_failures':self.completion_failures}


def estimate(value):
    return (len(json.dumps(value, ensure_ascii=False, default=str).encode()) + 2) // 3
