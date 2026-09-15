"""Agent-only settings. Workflow settings are read as initial defaults, never changed."""
from dataclasses import dataclass, field
import os
from journeyplus.config import Settings


@dataclass(frozen=True)
class AgentConfig:
    model: str
    base_url: str
    api_key: str = field(repr=False)
    context_window: int = 0
    protocol: str = 'auto'
    temperature: float = .2
    thinking: bool = False
    network_enabled: bool = False
    model_output_limit: int = 0
    explicit_cache: bool = False
    model_timing_enabled: bool = True
    context_token_budget: int = 500000

    def __post_init__(self):
        if self.context_window <= 2048:
            raise ValueError('JOURNEYPLUS_AGENT_CONTEXT_WINDOW must explicitly specify the model context window')
        if self.protocol not in {'auto', 'native', 'json'}:
            raise ValueError('Invalid Agent protocol')
        if self.model_output_limit < 0:
            raise ValueError('Model output capability must be nonnegative')
        if self.context_token_budget <= 0:
            raise ValueError('Agent context token budget must be positive')

    @classmethod
    def from_env(cls):
        initial = Settings.from_env()
        return cls(model=os.getenv('JOURNEYPLUS_AGENT_MODEL', initial.ai_model),
                   base_url=os.getenv('JOURNEYPLUS_AGENT_BASE_URL', initial.ai_base_url or ''),
                   api_key=os.getenv('JOURNEYPLUS_AGENT_API_KEY', initial.ai_api_key or ''),
                   context_window=int(os.getenv('JOURNEYPLUS_AGENT_CONTEXT_WINDOW', '0')),
                   protocol=os.getenv('JOURNEYPLUS_AGENT_PROTOCOL', 'auto'),
                   temperature=float(os.getenv('JOURNEYPLUS_AGENT_TEMPERATURE', '.2')),
                   thinking=os.getenv('JOURNEYPLUS_AGENT_THINKING', 'false').lower() == 'true',
                   network_enabled=os.getenv('JOURNEYPLUS_AGENT_NETWORK_ENABLED', 'false').lower() == 'true',
                   model_output_limit=int(os.getenv('JOURNEYPLUS_AGENT_MODEL_OUTPUT_LIMIT','0')),
                   explicit_cache=os.getenv('JOURNEYPLUS_AGENT_EXPLICIT_CACHE','false').lower() == 'true',
                   model_timing_enabled=os.getenv('JOURNEYPLUS_AGENT_MODEL_TIMING_ENABLED','true').lower() == 'true',
                   context_token_budget=int(os.getenv('JOURNEYPLUS_AGENT_CONTEXT_TOKEN_BUDGET','500000')))
