"""Agent availability is local to its routes, never a product startup gate."""
import asyncio
import logging
from contextlib import asynccontextmanager

from journeyplus.agent.harness.execution import blocking_call


class AgentLifecycle:
    def __init__(self, runtime, store, *, initialize_model=True,
                 recovery_interval=5, maintenance_interval=60):
        self.runtime = runtime
        self.store = store
        self.initialize_model = initialize_model
        self.recovery_interval = recovery_interval
        self.maintenance_interval = maintenance_interval
        self.workers = {}
        self.status = 'DISABLED' if getattr(runtime.ports.model, 'disabled', False) else (
            'INITIALIZING' if initialize_model else 'READY')
        self.error = None

    def dispatch(self, run_id):
        if self.status != 'READY':
            return
        if run_id not in self.workers or self.workers[run_id].done():
            self.workers[run_id] = asyncio.create_task(self.runtime.run(run_id))

    async def initialize(self):
        model = self.runtime.ports.model
        try:
            if self.initialize_model:
                await model.initialize()
            config = getattr(model, 'config', None)
            if config:
                self.store.model_name = config.model
                self.runtime.budget_limits = {
                    'soft': {'input_tokens': config.input_token_soft},
                    'hard': {'input_tokens': config.input_token_limit},
                }
            self.status = 'READY'
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.status = 'UNAVAILABLE'
            self.error = type(error).__name__
            # Do not expose provider messages, URLs or credentials.
            logging.getLogger(__name__).warning('Agent initialization failed: %s', self.error)
            if hasattr(model, 'close'):
                await model.close()

    async def recover(self):
        while True:
            try:
                if self.status == 'READY':
                    for identity in await blocking_call(self.store.pending_run_ids):
                        self.dispatch(identity)
                for identity, task in list(self.workers.items()):
                    if task.done():
                        self.workers.pop(identity)
                        if not task.cancelled():
                            task.exception()
            except Exception as error:
                logging.getLogger(__name__).warning('Recovery scan failed: %s', type(error).__name__)
            await asyncio.sleep(self.recovery_interval)

    async def maintain(self):
        research = self.runtime.services.get('research')
        if research and research.enabled and research.search_backend:
            await research.search_backend.initialize()
        while True:
            try:
                callback = self.runtime.services.get('maintenance')
                if callback:
                    await blocking_call(callback)
            except Exception as error:
                logging.getLogger(__name__).warning('Agent maintenance failed: %s', type(error).__name__)
            await asyncio.sleep(self.maintenance_interval)

    @asynccontextmanager
    async def lifespan(self, app):
        tasks = [asyncio.create_task(self.recover()), asyncio.create_task(self.maintain())]
        if self.status != 'DISABLED':
            tasks.append(asyncio.create_task(self.initialize()))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for identity, task in list(self.workers.items()):
                if not task.done():
                    await self.runtime.cancel(identity)
            if self.workers:
                await asyncio.gather(*self.workers.values(), return_exceptions=True)
            model = self.runtime.ports.model
            if hasattr(model, 'close'):
                await model.close()
            research = self.runtime.services.get('research')
            if research:
                await research.close()
            close_read=self.runtime.services.get('close_read_connection')
            if close_read:await blocking_call(close_read)
