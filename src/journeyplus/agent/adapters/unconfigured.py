"""A runnable local shell without a provider client or implicit model requests."""
from journeyplus.agent.harness.contracts import Capabilities, ModelUnavailable


class UnconfiguredModel:
    configuration_id = 'unconfigured-no-provider'
    protocol = 'native'

    def capabilities(self):
        return Capabilities(native_tools=True, streaming=True, context_window=32768, max_output=4096)

    async def initialize(self):
        pass

    async def stream(self, messages, definitions, limits, cancel_token):
        raise ModelUnavailable(code='MODEL_NOT_CONFIGURED')
        yield  # The port is an async iterator even when it cannot produce output.
