import json
import logging
from collections.abc import Collection
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path

import pytest
from typer.testing import CliRunner

from deadwax import (
    ConfigurationError,
    Dossier,
    EntityKind,
    Escalation,
    Identity,
    Query,
    SourcesConfig,
)
from deadwax.cli import app as app_module
from deadwax.cli.app import EXIT_NOTHING_MATCHED, EXIT_USAGE, app, select_runs
from deadwax.logs import RunOutcome, RunRecord, read_events, read_runs

runner = CliRunner()


@dataclass
class FakeLookup:
    """Stands in for deadwax.lookup and records how the command called it."""

    dossier: Dossier
    error: Exception | None = None
    calls: list[tuple[Query, SourcesConfig, Collection[str] | None, Collection[str]]] = field(
        default_factory=list,
    )

    async def __call__(
        self,
        query: Query,
        config: SourcesConfig,
        *,
        include: Collection[str] | None = None,
        exclude: Collection[str] = (),
    ) -> Dossier:
        self.calls.append((query, config, include, exclude))
        if self.error is not None:
            raise self.error
        return self.dossier


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, dossier: Dossier) -> FakeLookup:
    fake = FakeLookup(dossier)
    monkeypatch.setattr(app_module, "lookup", fake)
    return fake


def test_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"deadwax {version('deadwax')}"


def test_no_arguments_show_help() -> None:
    result = runner.invoke(app, [])

    assert "Usage" in result.output
    assert "sources" in result.output


def test_query_without_subcommand_runs_a_lookup(fake: FakeLookup) -> None:
    result = runner.invoke(app, ["--track", "Everything but the Girl - Missing"])

    assert result.exit_code == 0, result.output
    [(query, config, include, exclude)] = fake.calls
    assert (query.kind, query.artist, query.title) == (
        EntityKind.TRACK,
        "Everything but the Girl",
        "Missing",
    )
    assert config.cache.enabled
    assert (include, exclude) == (None, ())
    assert result.stdout.startswith("Everything but the Girl — Missing")


def test_options_reach_the_lookup(fake: FakeLookup, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "lookup",
            "https://open.spotify.com/album/1",
            "--album",
            "--sources",
            "musicbrainz, itunes,",
            "--exclude",
            "deezer",
            "--no-cache",
            "--timeout",
            "5",
        ],
    )

    assert result.exit_code == 0, result.output
    [(query, config, include, exclude)] = fake.calls
    assert query.kind is EntityKind.ALBUM
    assert (config.cache.enabled, config.adapter_timeout) == (False, 5)
    assert (include, exclude) == (["musicbrainz", "itunes"], ["deezer"])


def test_browser_flags_override_environment_for_one_lookup(
    fake: FakeLookup,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DEADWAX_HTTP__BROWSER_HEADLESS", "false")
    monkeypatch.setenv("DEADWAX_HTTP__ESCALATION", '["browser"]')
    monkeypatch.setenv("DEADWAX_HTTP__PATCHRIGHT_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("DEADWAX_DISCOGS__TOKEN", "example-token")
    monkeypatch.setenv("DEADWAX_BLEEP__RATE", "0.25")

    flagged = runner.invoke(
        app,
        ["--track", "a - b", "--headless", "--html-transport", "browser,nodriver"],
    )
    plain = runner.invoke(app, ["--track", "a - b"])

    assert flagged.exit_code == plain.exit_code == 0
    flagged_config = fake.calls[0][1]
    plain_config = fake.calls[1][1]
    assert flagged_config.http.browser_headless
    assert flagged_config.browser_headless("phonica")
    assert flagged_config.browser_headless("boomkat")
    assert flagged_config.browser_headless("norman")
    assert flagged_config.http.patchright_profile_dir == tmp_path / "profile"
    assert flagged_config.discogs.token is not None
    assert flagged_config.discogs.token.get_secret_value() == "example-token"
    assert flagged_config.bleep.rate == 0.25
    assert flagged_config.html_transports("beatport") == (
        Escalation.BROWSER,
        Escalation.NODRIVER,
    )
    assert flagged_config.html_transports("bleep") == (
        Escalation.BROWSER,
        Escalation.NODRIVER,
    )
    assert not plain_config.http.browser_headless
    assert not plain_config.browser_headless("boomkat")
    assert not plain_config.browser_headless("norman")
    assert plain_config.html_transports("beatport") == (Escalation.BROWSER, Escalation.HTTPX)


def test_headed_overrides_headless_environment(
    fake: FakeLookup,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEADWAX_HTTP__BROWSER_HEADLESS", "true")

    result = runner.invoke(app, ["--track", "a - b", "--headed"])

    assert result.exit_code == 0
    assert not fake.calls[0][1].http.browser_headless
    assert not fake.calls[0][1].browser_headless("phonica")


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (["--headless", "--headed"], "cannot be used together"),
        (["--html-transport", ""], "needs comma-separated"),
        (["--html-transport", "browser,patchright"], "duplicate transport"),
        (["--html-transport", "browser,unknown"], "unknown HTML transport"),
    ],
)
def test_invalid_browser_flags_are_usage_errors(
    fake: FakeLookup,
    options: list[str],
    message: str,
) -> None:
    result = runner.invoke(app, ["--track", "a - b", *options])

    assert result.exit_code == EXIT_USAGE
    assert message in result.output
    assert not fake.calls


@pytest.mark.parametrize("output", ["json", "markdown"])
def test_formats(fake: FakeLookup, dossier: Dossier, output: str) -> None:
    result = runner.invoke(app, ["--track", "a - b", "--format", output])

    assert result.exit_code == 0
    if output == "json":
        assert Dossier.model_validate_json(result.stdout) == dossier
    else:
        assert result.stdout.startswith("# Everything but the Girl — Missing")


def test_nothing_matched_exits_3(fake: FakeLookup, dossier: Dossier) -> None:
    fake.dossier = dossier.model_copy(update={"identity": Identity()})

    result = runner.invoke(app, ["--track", "a - b"])

    assert result.exit_code == EXIT_NOTHING_MATCHED
    assert "Nothing matched the query" in result.stdout


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--album", "--track", "a - b"], "mutually exclusive"),
        (["a - b"], "album or a track"),
        (["--track", "no separator"], "Artist - Title"),
        (["--album", "https://open.spotify.com/track/1"], "points to a track"),
        (["--track", "a - b", "--config", "missing.toml"], "configuration file not found"),
    ],
)
def test_usage_errors_exit_2(fake: FakeLookup, args: list[str], message: str) -> None:
    result = runner.invoke(app, args)

    assert result.exit_code == EXIT_USAGE
    assert message in result.stderr
    assert fake.calls == [] or "--config" not in args


def test_unknown_source_is_a_usage_error(fake: FakeLookup) -> None:
    fake.error = ConfigurationError("unknown sources: spotify")

    result = runner.invoke(app, ["--track", "a - b", "--sources", "spotify"])

    assert result.exit_code == EXIT_USAGE
    assert "unknown sources: spotify" in result.stderr


def test_unexpected_errors_exit_1(fake: FakeLookup) -> None:
    fake.error = RuntimeError("boom")

    result = runner.invoke(app, ["--track", "a - b"])

    assert result.exit_code == 1


def test_config_file_and_environment_reach_the_sources(
    fake: FakeLookup,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "deadwax.toml"
    config.write_text("adapter_timeout = 12\n[lastfm]\napi_key = 'from-file'\n")
    monkeypatch.setenv("DEADWAX_ITUNES__ENABLED", "false")

    result = runner.invoke(app, ["--track", "a - b", "--config", str(config)])

    assert result.exit_code == 0, result.output
    [(_, sources, _, _)] = fake.calls
    assert sources.adapter_timeout == 12
    assert sources.lastfm.api_key is not None
    assert not sources.itunes.enabled


def test_sources_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEADWAX_ITUNES__ENABLED", "false")
    monkeypatch.setenv("COLUMNS", "200")

    table = runner.invoke(app, ["sources"])
    as_json = runner.invoke(app, ["sources", "--format", "json"])

    assert table.exit_code == as_json.exit_code == 0
    statuses = {row["source"]: row["status"]["state"] for row in json.loads(as_json.stdout)}
    assert statuses == {
        "phonica": "ready",
        "boomkat": "ready",
        "norman": "ready",
        "spotify": "missing_credential",
        "musicbrainz": "ready",
        "odesli": "ready",
        "itunes": "disabled",
        "deezer": "ready",
        "discogs": "ready",
        "bandcamp": "ready",
        "lastfm": "missing_credential",
        "wikipedia": "ready",
        "listenbrainz": "ready",
        "secondhandsongs": "ready",
        "kexp": "ready",
        "youtube": "missing_credential",
        "soundcloud": "missing_credential",
        "beatport": "ready",
        "hardwax": "ready",
        "soundohm": "ready",
        "juno": "ready",
        "forcedexposure": "ready",
        "bleep": "ready",
        "genius": "missing_credential",
        "allmusic": "ready",
        "albumoftheyear": "ready",
        "pressreviews": "ready",
        "residentadvisor": "ready",
        "nts": "ready",
        "wfmu": "ready",
        "rateyourmusic": "ready",
        "whosampled": "ready",
        "tracklists": "ready",
    }
    assert "DEADWAX_DISCOGS__TOKEN" in table.stdout
    assert "DEADWAX_LASTFM__API_KEY" in table.stdout
    assert {(row["group"], row["default"]) for row in json.loads(as_json.stdout)} == {
        ("core", True),
        ("catalogues", True),
        ("catalogues", False),
        ("press", False),
        ("radio", True),
        ("radio", False),
        ("streaming", True),
        ("streaming", False),
        ("shops", False),
        ("samples", False),
    }


def test_sources_command_marks_the_default_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEADWAX_DEFAULT_SOURCES", "musicbrainz,deezer")

    result = runner.invoke(app, ["sources", "--format", "json"])

    assert result.exit_code == 0
    defaults = [row["source"] for row in json.loads(result.stdout) if row["default"]]
    assert defaults == ["musicbrainz", "deezer"]


def test_unknown_default_source_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEADWAX_DEFAULT_SOURCES", "core,nonsense")

    result = runner.invoke(app, ["sources"])

    assert result.exit_code == EXIT_USAGE
    assert "unknown sources: nonsense" in result.stderr
    assert "groups: core, shops" in result.stderr


def test_settings_configure_logging(
    monkeypatch: pytest.MonkeyPatch,
    clean_root_logger: logging.Logger,
) -> None:
    monkeypatch.setenv("DEADWAX_LOG__LEVEL", "ERROR")

    runner.invoke(app, ["sources"])

    assert clean_root_logger.level == logging.ERROR
    assert logging.getLogger("httpx").level == logging.WARNING
    assert not any(
        isinstance(handler, logging.StreamHandler)
        and type(handler).__name__ == "_AppConsoleHandler"
        for handler in clean_root_logger.handlers
    )


def test_verbose_enables_debug_logging(
    monkeypatch: pytest.MonkeyPatch,
    clean_root_logger: logging.Logger,
) -> None:
    monkeypatch.setenv("DEADWAX_LOG__LEVEL", "ERROR")
    logging.getLogger("httpx").setLevel(logging.NOTSET)

    runner.invoke(app, ["sources", "--debug"])

    assert clean_root_logger.level == logging.DEBUG
    assert logging.getLogger("httpx").level == logging.NOTSET


def test_invalid_configuration_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEADWAX_LOG__LEVEL", "LOUD")

    result = runner.invoke(app, ["sources"])

    assert result.exit_code == EXIT_USAGE
    assert result.stderr.startswith("Invalid configuration:")


def journal(tmp_path: Path) -> Path:
    return tmp_path / "user-logs"


def only_run(tmp_path: Path) -> RunRecord:
    [record] = read_runs(journal(tmp_path))
    return record


def test_a_lookup_is_journaled(
    fake: FakeLookup,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEADWAX_LASTFM__API_KEY", "secret-key")

    result = runner.invoke(app, ["--track", "Everything but the Girl - Missing"])

    assert result.exit_code == 0, result.output
    record = only_run(tmp_path)
    assert record.argv == ["--track", "Everything but the Girl - Missing"]
    assert (record.command, record.outcome, record.exit_code) == ("lookup", RunOutcome.OK, 0)
    assert record.query == "Everything but the Girl - Missing"
    assert record.sources == {"deezer": "blocked"}
    events = {event["event"]: event for event in read_events(journal(tmp_path) / record.file)}
    assert events["query.parsed"]["query"]["artist"] == "Everything but the Girl"  # type: ignore[index]
    settings = json.dumps(events["run.settings"])
    assert "secret-key" not in settings
    assert "**********" in settings
    assert "dossier" in events["run.end"]


@pytest.mark.parametrize(
    ("args", "outcome", "exit_code"),
    [
        (["--track", "a - b"], RunOutcome.NOTHING_MATCHED, EXIT_NOTHING_MATCHED),
        (["--album", "--track", "a - b"], RunOutcome.USAGE_ERROR, EXIT_USAGE),
        (["--track", "no separator"], RunOutcome.USAGE_ERROR, EXIT_USAGE),
    ],
)
def test_exit_codes_give_the_outcome(
    fake: FakeLookup,
    tmp_path: Path,
    args: list[str],
    outcome: RunOutcome,
    exit_code: int,
) -> None:
    fake.dossier = fake.dossier.model_copy(update={"identity": Identity()})

    result = runner.invoke(app, args)

    assert result.exit_code == exit_code
    assert (only_run(tmp_path).outcome, only_run(tmp_path).exit_code) == (outcome, exit_code)


def test_a_crash_is_journaled(fake: FakeLookup, tmp_path: Path) -> None:
    fake.error = RuntimeError("boom")

    runner.invoke(app, ["--track", "a - b"])

    record = only_run(tmp_path)
    assert record.outcome is RunOutcome.CRASH
    events = read_events(journal(tmp_path) / record.file)
    assert "boom" in str(next(e for e in events if e["event"] == "run.crash")["exception"])


def test_the_journal_can_be_disabled(
    fake: FakeLookup,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEADWAX_RUNS__ENABLED", "false")

    runner.invoke(app, ["--track", "a - b"])

    assert not journal(tmp_path).exists()


def test_the_journal_directory_can_be_set(
    fake: FakeLookup,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEADWAX_RUNS__DIR", str(tmp_path / "elsewhere"))

    runner.invoke(app, ["--track", "a - b"])

    assert len(read_runs(tmp_path / "elsewhere")) == 1
    assert not journal(tmp_path).exists()


def test_the_sources_command_is_journaled(tmp_path: Path) -> None:
    runner.invoke(app, ["sources"])

    assert only_run(tmp_path).command == "sources"


def test_runs_lists_and_shows_runs(
    fake: FakeLookup,
    dossier: Dossier,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLUMNS", "300")
    runner.invoke(app, ["--track", "Everything but the Girl - Missing"])
    fake.dossier = dossier.model_copy(update={"identity": Identity()})
    runner.invoke(app, ["--track", "Nobody - Nothing"])

    listed = runner.invoke(app, ["runs"])
    failed = runner.invoke(app, ["runs", "--failed", "--format", "json"])
    shown = runner.invoke(app, ["runs", json.loads(failed.stdout)[0]["run_id"][-6:]])

    assert listed.exit_code == 0, listed.output
    assert "nothing_matched" in listed.stdout
    assert "deezer:blocked" in listed.stdout
    assert [run["outcome"] for run in json.loads(failed.stdout)] == ["nothing_matched"]
    assert shown.exit_code == 0, shown.output
    assert "query: Nobody - Nothing (track)" in shown.stdout
    assert "nothing_matched" in shown.stdout


@pytest.mark.parametrize("run_id", ["missing", "2"])
def test_runs_rejects_unknown_or_ambiguous_ids(fake: FakeLookup, run_id: str) -> None:
    runner.invoke(app, ["--track", "a - b"])
    runner.invoke(app, ["--track", "a - b"])

    result = runner.invoke(app, ["runs", run_id])

    assert result.exit_code == EXIT_USAGE
    assert "run" in result.stderr


def test_runs_without_a_journal(tmp_path: Path) -> None:
    result = runner.invoke(app, ["runs"])

    assert result.exit_code == 0
    assert "No runs journaled" in result.stdout


def record(**fields: object) -> RunRecord:
    values: dict[str, object] = {
        "run_id": "20261113T100000Z-aaa111",
        "started_at": "2026-11-13T10:00:00Z",
        "duration_ms": 1000,
        "command": "lookup",
        "version": "1",
        "outcome": "ok",
        "file": "runs/x.jsonl",
    }
    return RunRecord.model_validate(values | fields)


def test_select_runs_applies_every_filter() -> None:
    ok = record(query="A - B", sources={"itunes": "ok"}, found=True)
    blocked = record(query="C - D", sources={"deezer": "blocked"}, found=True)
    rejected = record(query="E - F", sources={"discogs": "no_match"}, found=True)
    unmatched = record(query="G - H", outcome="nothing_matched", found=False)
    records = [ok, blocked, rejected, unmatched]

    assert select_runs(records) == [unmatched, rejected, blocked, ok]
    assert select_runs(records, failed=True) == [unmatched]
    assert select_runs(records, no_match=True) == [unmatched, rejected]
    assert select_runs(records, source="deezer") == [blocked]
    assert select_runs(records, source="itunes") == []
    assert select_runs(records, kind="blocked") == [blocked]
    assert select_runs(records, text="e - f") == [rejected]
