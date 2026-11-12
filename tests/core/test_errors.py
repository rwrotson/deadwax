import pytest

from deadwax.core import (
    BlockedError,
    ConfigurationError,
    DeadwaxError,
    InvalidQueryError,
    NotFoundError,
    RateLimitedError,
    SourceError,
)


@pytest.mark.parametrize(
    "error", [InvalidQueryError, ConfigurationError, SourceError, BlockedError, NotFoundError]
)
def test_errors_share_the_library_base(error: type[DeadwaxError]) -> None:
    assert issubclass(error, DeadwaxError)


def test_invalid_query_is_a_value_error() -> None:
    assert issubclass(InvalidQueryError, ValueError)


@pytest.mark.parametrize("error", [BlockedError, RateLimitedError, NotFoundError])
def test_source_errors_keep_the_url(error: type[SourceError]) -> None:
    raised = error("refused", url="https://example.org/a")

    assert isinstance(raised, SourceError)
    assert raised.url == "https://example.org/a"
    assert str(raised) == "refused"
