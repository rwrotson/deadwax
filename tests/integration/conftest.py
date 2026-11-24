import time
from collections.abc import Generator

import pytest

from tests.integration.live import LiveRun, MusicBrainzUnavailableError

_RUN = pytest.StashKey[LiveRun]()
_RETRY_DELAY = 30


@pytest.fixture
def live_run(request: pytest.FixtureRequest) -> LiveRun:
    return request.config.stash.setdefault(_RUN, LiveRun())


@pytest.fixture
def live_report(live_run: LiveRun) -> list[str]:
    return live_run.lines


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
    call: pytest.CallInfo[None],
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    run = item.config.stash.setdefault(_RUN, LiveRun())
    if report.when == "teardown" and report.failed and run.pending and run.pending[-1] is item:
        run.pending.pop()
    if (
        not run.retrying
        and report.when == "call"
        and report.failed
        and call.excinfo is not None
        and isinstance(call.excinfo.value, MusicBrainzUnavailableError)
    ):
        run.pending.append(item)
        report.outcome = "rerun"  # type: ignore[assignment]  # Pytest plugins can add outcomes.
        result = f"failed ({call.excinfo.value}), retry queued"
    else:
        result = report.outcome
        if report.failed and call.excinfo is not None:
            reason = str(call.excinfo.value).splitlines()
            if reason:
                result = f"{result} ({reason[0]})"
    if report.when == "call" or not report.passed:
        attempt = 2 if run.retrying else 1
        run.lines.append(f"{item.name}, attempt {attempt} ({report.when}): {result}")
    return report


def pytest_report_teststatus(report: pytest.TestReport) -> tuple[str, str, str] | None:
    if str(report.outcome) == "rerun":
        return "rerun", "R", "RETRY QUEUED"
    return None


@pytest.hookimpl(wrapper=True)
def pytest_runtestloop(session: pytest.Session) -> Generator[None, object, object]:
    result = yield
    run = session.config.stash.get(_RUN, None)
    if run is None or not run.pending:
        return result

    run.lines.append(f"Waited {_RETRY_DELAY}s before retrying {len(run.pending)} live lookups")
    time.sleep(_RETRY_DELAY)
    run.retrying = True
    for item in run.pending:
        item.ihook.pytest_runtest_protocol(item=item, nextitem=None)
        if session.shouldfail:
            raise session.Failed(session.shouldfail)
        if session.shouldstop:
            raise session.Interrupted(session.shouldstop)
    return result


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter,
    config: pytest.Config,
) -> None:
    run = config.stash.get(_RUN, None)
    if run is not None and run.lines:
        terminalreporter.write_sep("-", "live lookups")
        for line in run.lines:
            terminalreporter.write_line(line)
