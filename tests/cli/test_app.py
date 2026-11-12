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
    Identity,
    Query,
    SourcesConfig,
)
from deadwax.cli import app as app_module
from deadwax.cli.app import EXIT_NOTHING_MATCHED, EXIT_USAGE, app

runner = CliRunner()


@dataclass
class FakeLookup:
    """Stands in for deadwax.lookup and records how the command called it."""

    dossier: Dossier
    error: Exception | None = None
    calls: list[tuple[Query, SourcesConfig, Collection[str] | None, Collection[str]]] = field(
        default_factory=list
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
    fake: FakeLookup, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "deadwax.toml"
    config.write_text("adapter_timeout = 12\n[odesli]\napi_key = 'from-file'\n")
    monkeypatch.setenv("DEADWAX_ITUNES__ENABLED", "false")

    result = runner.invoke(app, ["--track", "a - b", "--config", str(config)])

    assert result.exit_code == 0, result.output
    [(_, sources, _, _)] = fake.calls
    assert sources.adapter_timeout == 12
    assert sources.odesli.api_key is not None
    assert not sources.itunes.enabled


def test_sources_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEADWAX_ITUNES__ENABLED", "false")

    table = runner.invoke(app, ["sources"])
    as_json = runner.invoke(app, ["sources", "--format", "json"])

    assert table.exit_code == as_json.exit_code == 0
    assert "DEADWAX_ODESLI__API_KEY" in table.stdout
    statuses = {row["source"]: row["status"]["state"] for row in json.loads(as_json.stdout)}
    assert statuses == {
        "musicbrainz": "ready",
        "odesli": "missing_credential",
        "itunes": "disabled",
        "deezer": "ready",
    }


def test_settings_configure_logging(
    monkeypatch: pytest.MonkeyPatch, clean_root_logger: logging.Logger
) -> None:
    monkeypatch.setenv("DEADWAX_LOG__LEVEL", "ERROR")

    runner.invoke(app, ["sources"])

    assert clean_root_logger.level == logging.ERROR
    assert logging.getLogger("httpx").level == logging.WARNING


def test_verbose_enables_debug_logging(
    monkeypatch: pytest.MonkeyPatch, clean_root_logger: logging.Logger
) -> None:
    monkeypatch.setenv("DEADWAX_LOG__LEVEL", "ERROR")
    logging.getLogger("httpx").setLevel(logging.NOTSET)

    runner.invoke(app, ["sources", "--verbose"])

    assert clean_root_logger.level == logging.DEBUG
    assert logging.getLogger("httpx").level == logging.NOTSET


def test_invalid_configuration_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEADWAX_LOG__LEVEL", "LOUD")

    result = runner.invoke(app, ["sources"])

    assert result.exit_code == EXIT_USAGE
    assert result.stderr.startswith("Invalid configuration:")
