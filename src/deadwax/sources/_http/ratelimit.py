import asyncio
import random
import time
from collections.abc import Awaitable, Callable

type Clock = Callable[[], float]
type Sleep = Callable[[float], Awaitable[None]]


class RateLimiter:
    """Token bucket that spaces requests to one host, with random extra delay."""

    def __init__(  # noqa: PLR0913 -- clock, sleep and rng are injected for tests
        self,
        rate: float,
        *,
        burst: float = 1.0,
        jitter: float = 0.2,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        if rate <= 0 or burst < 1:
            raise ValueError("rate must be positive and burst at least 1")
        self.rate = rate
        self._burst = burst
        self._jitter = jitter
        self._clock = clock
        self._sleep = sleep
        self._rng = rng or random.Random()  # noqa: S311 -- jitter, not cryptography
        self._tokens = burst
        self._updated = clock()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self._burst, self._tokens + (now - self._updated) * self.rate)
        self._updated = now

    async def acquire(self) -> None:
        """Wait until a request may be sent."""
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                wait = (1 - self._tokens) / self.rate
                await self._sleep(wait * (1 + self._rng.uniform(0, self._jitter)))


class HostLimiters:
    """Rate limiters shared by all clients, one per host."""

    def __init__(
        self,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._rng = rng
        self._limiters: dict[str, RateLimiter] = {}

    def get(self, host: str, rate: float) -> RateLimiter:
        """Return the limiter of a host, created with the rate on first use."""
        limiter = self._limiters.get(host)
        if limiter is None:
            limiter = RateLimiter(rate, clock=self._clock, sleep=self._sleep, rng=self._rng)
            self._limiters[host] = limiter
        return limiter
