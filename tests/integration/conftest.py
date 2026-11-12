import pytest

_REPORT = pytest.StashKey[list[str]]()


@pytest.fixture
def live_report(request: pytest.FixtureRequest) -> list[str]:
    """Lines printed after the run, for reviewing what the live sources returned."""
    return request.config.stash.setdefault(_REPORT, [])


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    """Print what each live lookup found."""
    lines = config.stash.get(_REPORT, [])
    if lines:
        terminalreporter.write_sep("-", "live lookups")
        for line in lines:
            terminalreporter.write_line(line)
