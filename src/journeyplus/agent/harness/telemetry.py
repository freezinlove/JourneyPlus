"""Request-local diagnostics, never included in model messages or tool results."""
from contextvars import ContextVar

model_timing: ContextVar[dict | None] = ContextVar('model_timing', default=None)
