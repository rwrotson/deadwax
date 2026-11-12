import pytest

from deadwax.core import ConfigurationError, DeadwaxError, InvalidQueryError


@pytest.mark.parametrize("error", [InvalidQueryError, ConfigurationError])
def test_errors_share_the_library_base(error: type[DeadwaxError]) -> None:
    assert issubclass(error, DeadwaxError)


def test_invalid_query_is_a_value_error() -> None:
    assert issubclass(InvalidQueryError, ValueError)
