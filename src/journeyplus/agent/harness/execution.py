"""Bounded synchronous work, with cancellation drained before terminal receipts."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, copy_context
from functools import partial, wraps
from weakref import WeakKeyDictionary

_pool=ThreadPoolExecutor(max_workers=6,thread_name_prefix='agent-storage')
_limits=WeakKeyDictionary()
active_call=ContextVar('agent_active_call',default=None)


async def blocking_call(function,*args,**kwargs):
    loop=asyncio.get_running_loop()
    limiter=_limits.setdefault(loop,asyncio.Semaphore(6))
    async with limiter:
        future=loop.run_in_executor(_pool,copy_context().run,partial(function,*args,**kwargs))
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            # Python cannot kill an executing thread. Drain its transaction before
            # declaring a run terminal, so no late write follows a cancel receipt.
            while not future.done():
                try:await asyncio.shield(future)
                except asyncio.CancelledError:continue
                except Exception:break
            if future.done() and not future.cancelled():future.exception()
            raise


def blocking_tool(function):
    @wraps(function)
    async def execute(args,context):
        token=active_call.set(context)
        try:return await blocking_call(function,args,context)
        finally:active_call.reset(token)
    return execute
