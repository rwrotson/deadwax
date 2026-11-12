import random
from dataclasses import dataclass, field

import pytest

from deadwax.sources._http import HostLimiters, RateLimiter


@dataclass
class FakeTime:
    """Clock whose sleep advances time instantly and records each wait."""

    now: float = 1000.0
    sleeps: list[float] = field(default_factory=list)

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def fake_time() -> FakeTime:
    return FakeTime()


async def acquire_times(limiter: RateLimiter, time: FakeTime, count: int) -> list[float]:
    times = []
    for _ in range(count):
        await limiter.acquire()
        times.append(time.now)
    return times


@pytest.mark.asyncio
async def test_requests_are_spaced_by_the_rate(fake_time: FakeTime) -> None:
    limiter = RateLimiter(2.0, jitter=0, clock=fake_time.clock, sleep=fake_time.sleep)

    times = await acquire_times(limiter, fake_time, 3)

    assert times == [1000.0, 1000.5, 1001.0]


@pytest.mark.asyncio
async def test_burst_allows_back_to_back_requests(fake_time: FakeTime) -> None:
    limiter = RateLimiter(1.0, burst=2, jitter=0, clock=fake_time.clock, sleep=fake_time.sleep)

    times = await acquire_times(limiter, fake_time, 3)

    assert times == [1000.0, 1000.0, 1001.0]


@pytest.mark.asyncio
async def test_jitter_only_lengthens_waits(fake_time: FakeTime) -> None:
    limiter = RateLimiter(
        1.0,
        jitter=0.5,
        clock=fake_time.clock,
        sleep=fake_time.sleep,
        rng=random.Random(1),  # noqa: S311 -- seeded test jitter
    )

    await acquire_times(limiter, fake_time, 5)

    assert len(fake_time.sleeps) == 4
    assert all(1.0 <= wait <= 1.5 for wait in fake_time.sleeps)


@pytest.mark.asyncio
async def test_idle_time_refills_the_bucket(fake_time: FakeTime) -> None:
    limiter = RateLimiter(1.0, jitter=0, clock=fake_time.clock, sleep=fake_time.sleep)

    await limiter.acquire()
    fake_time.now += 10
    await limiter.acquire()

    assert fake_time.sleeps == []


@pytest.mark.parametrize(("rate", "burst"), [(0, 1), (1, 0.5)])
def test_invalid_limits_are_rejected(rate: float, burst: float) -> None:
    with pytest.raises(ValueError, match="rate must be positive"):
        RateLimiter(rate, burst=burst)


def test_hosts_share_one_limiter_created_with_the_first_rate(fake_time: FakeTime) -> None:
    limiters = HostLimiters(clock=fake_time.clock, sleep=fake_time.sleep)

    first = limiters.get("musicbrainz.org", 1.0)

    assert limiters.get("musicbrainz.org", 5.0) is first
    assert first.rate == 1.0
    assert limiters.get("api.discogs.com", 1.0) is not first
