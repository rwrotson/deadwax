import random
from datetime import UTC, datetime

import pytest

from deadwax.sources._http import RetryPolicy, parse_retry_after

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("120", 120.0),
        (" 3 ", 3.0),
        ("Thu, 12 Nov 2026 12:00:30 GMT", 30.0),
        ("Thu, 12 Nov 2026 12:00:30 -0000", 30.0),
        ("Thu, 12 Nov 2026 11:59:00 GMT", 0.0),
        ("soon", None),
        ("-5", None),
    ],
)
def test_retry_after_seconds_and_dates(value: str | None, expected: float | None) -> None:
    assert parse_retry_after(value, NOW) == expected


def test_backoff_has_full_jitter_under_a_cap() -> None:
    policy = RetryPolicy(base=1.0, cap=4.0)
    rng = random.Random(7)  # noqa: S311 -- seeded test jitter

    delays = [policy.backoff(attempt, rng) for attempt in range(6) for _ in range(20)]

    assert all(0 <= delay <= 4.0 for delay in delays)
    assert max(delays[:20]) <= 1.0


def test_server_hint_wins_over_backoff() -> None:
    policy = RetryPolicy(base=100.0)
    rng = random.Random(0)  # noqa: S311 -- seeded test jitter

    assert policy.delay(0, "2", rng, NOW) == 2.0
    assert policy.delay(0, None, rng, NOW) <= 100.0
