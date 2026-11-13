import random
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


def parse_retry_after(value: str | None, now: datetime) -> float | None:
    """Return the wait a Retry-After header asks for, in seconds, or None if it is unusable."""
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        moment = parsedate_to_datetime(value)
    except TypeError, ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0.0, (moment - now).total_seconds())


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded retries with exponential backoff and full jitter."""

    retries: int = 3
    base: float = 0.5
    cap: float = 30.0
    max_wait: float = 60.0

    def backoff(self, attempt: int, rng: random.Random) -> float:
        """Return a random delay before retry number `attempt` (counted from 0)."""
        return rng.uniform(0, min(self.cap, self.base * 2**attempt))

    def delay(
        self,
        attempt: int,
        retry_after: str | None,
        rng: random.Random,
        now: datetime,
    ) -> float:
        """Return the delay before a retry, preferring the server's Retry-After."""
        hinted = parse_retry_after(retry_after, now)
        return self.backoff(attempt, rng) if hinted is None else hinted
