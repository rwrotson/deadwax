import asyncio
import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from deadwax.core import (
    AdapterError,
    ConfigurationError,
    Discrepancy,
    Dossier,
    EntityKind,
    ErrorKind,
    Identity,
    Provenance,
    Sourced,
    text_query,
    trace,
    trace_scope,
)
from deadwax.logs import (
    RunJournal,
    RunLogSettings,
    RunNotFoundError,
    RunOutcome,
    find_run,
    prune_runs,
    read_events,
    read_runs,
    run_journal,
)

NOW = datetime(2026, 11, 13, tzinfo=UTC)
QUERY = text_query("Everything but the Girl - Missing", EntityKind.TRACK)

library = logging.getLogger("deadwax.tests")


def sourced(value: str) -> Sourced[str]:
    return Sourced(value=value, sources=[Provenance(source="itunes")])


def dossier(*, found: bool = True) -> Dossier:
    identity = Identity(
        kind=EntityKind.TRACK,
        artist=sourced("Everything but the Girl") if found else None,
        title=sourced("Missing") if found else None,
        discrepancies=[Discrepancy(field="date", values=[sourced("1994"), sourced("1995")])],
    )
    errors = [AdapterError(source="discogs", kind=ErrorKind.NO_MATCH, reason="other record")]
    return Dossier(query=QUERY, identity=identity, errors=errors, generated_at=NOW)


@pytest.fixture
def settings(tmp_path: Path) -> RunLogSettings:
    return RunLogSettings(dir=tmp_path / "journal")


def names(journal: RunJournal) -> list[object]:
    assert journal.path is not None
    return [event["event"] for event in read_events(journal.path)]


def test_a_run_writes_its_events_and_an_index_line(settings: RunLogSettings) -> None:
    with run_journal(settings, label="test", argv=["deadwax", "x"]) as run:
        with trace_scope(source="itunes"):
            trace(library, "adapter.end", outcome="ok", errors=[])
        trace(library, "adapter.end", source="discogs", errors=[{"kind": "not_found"}])
        logging.getLogger("httpx").info("request sent")
        logging.getLogger("httpx").warning("slow answer")
        run.event("query.parsed", artist="Everything but the Girl")
        run.record(dossier())

    assert run.path is not None
    events = read_events(run.path)
    assert [event["event"] for event in events] == [
        "run.start",
        "adapter.end",
        "adapter.end",
        "slow answer",
        "query.parsed",
        "run.end",
    ]
    assert events[0]["label"] == "test"
    assert events[1]["source"] == "itunes"
    assert events[1]["run_id"] == run.run_id
    assert events[3]["level"] == "warning"
    assert events[-1]["dossier"]["identity"]["title"]["value"] == "Missing"  # type: ignore[index]

    [record] = read_runs(settings.dir)  # type: ignore[arg-type]
    assert record.run_id == run.run_id
    assert record.outcome is RunOutcome.OK
    assert record.query == "Everything but the Girl - Missing"
    assert record.identity == "Everything but the Girl - Missing"
    assert (record.kind, record.found, record.warnings) == ("track", True, 1)
    assert record.sources == {"itunes": "ok", "discogs": "no_match"}
    assert record.discrepancies == ["date"]
    assert record.file == run.path.relative_to(settings.dir).as_posix()  # type: ignore[arg-type]


def test_a_dossier_without_identity_means_nothing_matched(settings: RunLogSettings) -> None:
    with run_journal(settings.model_copy(update={"dossier": False})) as run:
        run.record(dossier(found=False))

    [record] = read_runs(settings.dir)  # type: ignore[arg-type]
    assert record.outcome is RunOutcome.NOTHING_MATCHED
    assert record.identity is None
    assert run.path is not None
    assert "dossier" not in read_events(run.path)[-1]


def test_a_run_without_dossier_has_no_query(settings: RunLogSettings) -> None:
    with run_journal(settings, command="sources"):
        pass

    [record] = read_runs(settings.dir)  # type: ignore[arg-type]
    assert (record.command, record.outcome, record.query) == ("sources", RunOutcome.OK, None)


@pytest.mark.parametrize(
    ("error", "outcome"),
    [(RuntimeError("boom"), RunOutcome.CRASH), (KeyboardInterrupt(), RunOutcome.INTERRUPTED)],
)
def test_exceptions_end_the_run_and_propagate(
    settings: RunLogSettings,
    error: BaseException,
    outcome: RunOutcome,
) -> None:
    with pytest.raises(type(error)), run_journal(settings) as run:
        raise error

    [record] = read_runs(settings.dir)  # type: ignore[arg-type]
    assert record.outcome is outcome
    if outcome is RunOutcome.CRASH:
        assert run.path is not None
        crash = next(e for e in read_events(run.path) if e["event"] == "run.crash")
        assert "boom" in str(crash["exception"])


def test_a_stated_outcome_wins(settings: RunLogSettings) -> None:
    run = run_journal(settings)
    run.open()
    run.set_outcome(RunOutcome.USAGE_ERROR, 2)
    run.close(ValueError("bad"))

    [record] = read_runs(settings.dir)  # type: ignore[arg-type]
    assert (record.outcome, record.exit_code) == (RunOutcome.USAGE_ERROR, 2)


def test_logging_is_restored_and_later_records_are_not_journaled(
    settings: RunLogSettings,
) -> None:
    package = logging.getLogger("deadwax")
    before = (
        package.level,
        package.propagate,
        package.handlers[:],
        logging.getLogger().handlers[:],
    )

    with run_journal(settings) as run:
        assert package.level == logging.DEBUG
    trace(library, "after.close")

    assert (
        package.level,
        package.propagate,
        package.handlers,
        logging.getLogger().handlers,
    ) == before
    assert "after.close" not in names(run)


def test_the_application_sees_only_records_at_its_own_level(
    settings: RunLogSettings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    with run_journal(settings) as run:
        trace(library, "debug.event")
        library.warning("warning.event")

    assert [r.getMessage() for r in caplog.records if r.name == library.name] == ["warning.event"]
    assert {"debug.event", "warning.event"} <= set(names(run))


@pytest.mark.asyncio
async def test_concurrent_runs_write_separate_files(settings: RunLogSettings) -> None:
    async def job(label: str) -> RunJournal:
        async with run_journal(settings, label=label) as run:
            for _ in range(3):
                trace(library, "job.step", job=label)
                await asyncio.sleep(0)
        return run

    first, second = await asyncio.gather(job("first"), job("second"))

    for run in (first, second):
        assert run.path is not None
        steps = [e["job"] for e in read_events(run.path) if e["event"] == "job.step"]
        assert steps == [run.label] * 3
    assert len(read_runs(settings.dir)) == 2  # type: ignore[arg-type]


def test_hooks_stay_until_the_last_journal_closes(settings: RunLogSettings) -> None:
    package = logging.getLogger("deadwax")
    level = package.level

    outer = run_journal(settings)
    outer.open()
    with run_journal(settings) as inner:
        trace(library, "inner.event")
    assert package.level == logging.DEBUG
    trace(library, "outer.event")
    outer.close()

    assert package.level == level
    assert "inner.event" in names(inner)
    assert "outer.event" in names(outer)
    assert "inner.event" not in names(outer)


def test_a_disabled_journal_writes_nothing(tmp_path: Path) -> None:
    with run_journal(RunLogSettings(enabled=False, dir=tmp_path)) as run:
        run.event("ignored")

    assert run.path is None
    assert run.close() is None
    assert list(tmp_path.iterdir()) == []


def test_an_enabled_journal_needs_a_directory() -> None:
    with pytest.raises(ConfigurationError, match="directory"):
        run_journal(RunLogSettings())


def test_an_unwritable_directory_disables_the_journal(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("")

    with run_journal(RunLogSettings(dir=blocker)) as run:
        pass

    assert run.path is None
    assert run.error is not None
    assert "cannot write the run journal" in caplog.text


def test_an_unwritable_index_keeps_the_run_file(
    settings: RunLogSettings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert settings.dir is not None
    (settings.dir / "runs.jsonl").mkdir(parents=True)

    with run_journal(settings) as run:
        pass

    assert run.path is not None
    assert run.path.is_file()
    assert "cannot add run" in caplog.text


def index_line(day: str) -> str:
    return json.dumps({"started_at": f"{day}T10:00:00Z"}) + "\n"


def test_prune_removes_expired_runs(tmp_path: Path) -> None:
    for day in ("2026-08-01", "2026-11-01"):
        (tmp_path / "runs" / day).mkdir(parents=True)
    index = tmp_path / "runs.jsonl"
    index.write_text(index_line("2026-08-01") + "broken\n" + index_line("2026-11-01"))

    prune_runs(tmp_path, 30, date(2026, 11, 13))

    assert [path.name for path in (tmp_path / "runs").iterdir()] == ["2026-11-01"]
    assert index.read_text() == "broken\n" + index_line("2026-11-01")


@pytest.mark.parametrize("retention", [0, 365])
def test_prune_keeps_runs_within_retention(tmp_path: Path, retention: int) -> None:
    (tmp_path / "runs" / "2026-08-01").mkdir(parents=True)
    index = tmp_path / "runs.jsonl"
    index.write_text(index_line("2026-08-01"))

    prune_runs(tmp_path, retention, date(2026, 11, 13))

    assert (tmp_path / "runs" / "2026-08-01").is_dir()
    assert index.read_text() == index_line("2026-08-01")


def test_prune_without_runs_does_nothing(tmp_path: Path) -> None:
    prune_runs(tmp_path, 30, date(2026, 11, 13))

    assert list(tmp_path.iterdir()) == []


def test_readers_skip_unreadable_lines(tmp_path: Path) -> None:
    assert read_runs(tmp_path) == []
    (tmp_path / "runs.jsonl").write_text("not json\n")
    assert read_runs(tmp_path) == []

    events = tmp_path / "events.jsonl"
    events.write_text('{"event": "a"}\nnot json\n[1]\n')
    assert read_events(events) == [{"event": "a"}]


def test_find_run_by_id_prefix_or_suffix(tmp_path: Path) -> None:
    day = tmp_path / "runs" / "2026-11-13"
    day.mkdir(parents=True)
    for run_id in ("20261113T100000Z-aaa111", "20261113T110000Z-bbb222", "20261113T1"):
        (day / f"{run_id}.jsonl").write_text("")

    assert find_run(tmp_path, "20261113T10").stem == "20261113T100000Z-aaa111"
    assert find_run(tmp_path, "bbb").stem == "20261113T110000Z-bbb222"
    assert find_run(tmp_path, "20261113T1").stem == "20261113T1"
    with pytest.raises(RunNotFoundError, match="names 3 runs"):
        find_run(tmp_path, "2026")
    with pytest.raises(RunNotFoundError, match="no run"):
        find_run(tmp_path, "zzz")
    with pytest.raises(RunNotFoundError, match="no run"):
        find_run(tmp_path, "")
