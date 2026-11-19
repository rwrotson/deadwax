import asyncio

import pytest

from deadwax.core import adapter_time_left, pause_adapter_timeout
from deadwax.core.deadline import adapter_deadline

pytestmark = pytest.mark.asyncio


async def test_time_left_is_none_outside_a_deadline() -> None:
    assert adapter_time_left() is None


async def test_time_left_counts_down_inside_a_deadline() -> None:
    async with adapter_deadline(30):
        left = adapter_time_left()

    assert left is not None
    assert 0 < left <= 30
    assert adapter_time_left() is None


async def test_deadline_raises_timeout_when_exceeded() -> None:
    with pytest.raises(TimeoutError):
        async with adapter_deadline(0.01):
            await asyncio.sleep(1)


async def test_pause_without_a_deadline_runs_the_block() -> None:
    async with pause_adapter_timeout():
        await asyncio.sleep(0)

    assert adapter_time_left() is None


async def test_paused_wait_is_added_back_to_the_budget() -> None:
    async with adapter_deadline(0.03):
        async with pause_adapter_timeout():
            assert adapter_time_left() is None
            await asyncio.sleep(0.05)
        left = adapter_time_left()

    assert left is not None
    assert left > 0
