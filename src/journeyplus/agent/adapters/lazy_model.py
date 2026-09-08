"""Delay provider construction until an explicitly enabled lifecycle starts."""


class LazyModel:
    def __init__(self, factory):
        self._factory = factory
        self._model = None

    async def initialize(self):
        self._model = self._factory()
        await self._model.initialize()

    @property
    def config(self):
        return getattr(self._model, 'config', None)

    @property
    def configuration_id(self):
        return getattr(self._model, 'configuration_id', 'not-initialized')

    def capabilities(self):
        return self._model.capabilities()

    def estimate_input(self, *args):
        return self._model.estimate_input(*args)

    def estimate_final_input(self, *args):
        return self._model.estimate_final_input(*args)

    async def stream(self, *args):
        async for event in self._model.stream(*args):
            yield event

    async def close(self):
        if self._model is not None:
            await self._model.close()
