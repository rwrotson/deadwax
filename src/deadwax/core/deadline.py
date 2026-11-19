import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextvars import ContextVar

_adapter_deadline: ContextVar[asyncio.Timeout | None] = ContextVar(
    "deadwax_adapter_deadline",
    default=None,
)


@contextlib.asynccontextmanager
async def adapter_deadline(seconds: float) -> AsyncIterator[None]:
    """Limit the enclosed adapter call to a time budget that the adapter can read and pause."""
    async with asyncio.timeout(seconds) as timeout:
        token = _adapter_deadline.set(timeout)
        try:
            yield
        finally:
            _adapter_deadline.reset(token)


def adapter_time_left() -> float | None:
    """Return the seconds left before the current adapter times out, or None without a limit."""
    timeout = _adapter_deadline.get()
    if timeout is None or (deadline := timeout.when()) is None:
        return None
    return max(deadline - asyncio.get_running_loop().time(), 0.0)


@contextlib.asynccontextmanager
async def pause_adapter_timeout() -> AsyncIterator[None]:
    """Exclude a shared-resource queue wait from the current adapter timeout."""
    timeout = _adapter_deadline.get()
    if timeout is None or (deadline := timeout.when()) is None:
        yield
        return
    started = asyncio.get_running_loop().time()
    timeout.reschedule(None)
    try:
        yield
    finally:
        timeout.reschedule(deadline + asyncio.get_running_loop().time() - started)
