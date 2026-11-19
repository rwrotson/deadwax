import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from typer.core import TyperGroup

from deadwax import (
    Capability,
    ConfigurationError,
    Dossier,
    EntityKind,
    InvalidQueryError,
    PerSourceSettings,
    Request,
    TraceEvent,
    describe_sources,
    lookup,
    parse_query,
)
from deadwax.cli.render import OutputFormat, print_dossier, print_run, print_runs, print_sources
from deadwax.cli.settings import Settings, load_settings
from deadwax.logs import (
    RunJournal,
    RunNotFoundError,
    RunOutcome,
    RunRecord,
    find_run,
    read_events,
    read_runs,
    run_journal,
    setup_logging,
)

EXIT_USAGE = 2
EXIT_NOTHING_MATCHED = 3

# Root options handled by the group itself; anything else starts a lookup.
_ROOT_OPTIONS = frozenset({"--help", "-h", "--version"})

# Key of the command-line arguments, as typed, in the shared click context metadata.
_ARGV_KEY = "deadwax.argv"

_OUTCOMES = {
    0: RunOutcome.OK,
    EXIT_USAGE: RunOutcome.USAGE_ERROR,
    EXIT_NOTHING_MATCHED: RunOutcome.NOTHING_MATCHED,
}

# Outcomes that `runs --failed` lists.
_FAILED = frozenset(RunOutcome) - {RunOutcome.OK}

# Logger of the browser transports, whose warnings ask for a challenge solved by hand.
_BROWSER_LOGGER = "deadwax.sources._http"


class _LookupByDefault(TyperGroup):
    """Run `lookup` when the first argument is not a subcommand, so `deadwax QUERY` works."""

    # typer.Context subclasses the click Context Typer vendors in a private module.
    def parse_args(self, ctx: typer.Context, args: list[str]) -> list[str]:  # type: ignore[override]
        ctx.meta[_ARGV_KEY] = list(args)
        if args and args[0] not in self.commands and args[0] not in _ROOT_OPTIONS:
            args = ["lookup", *args]
        return super().parse_args(ctx, args)


class _BrowserNotice(logging.Handler):
    """Print browser transport warnings to stderr when other logs are hidden."""

    def emit(self, record: logging.LogRecord) -> None:
        typer.echo(record.getMessage(), err=True)


def _show_browser_notices(show: bool) -> None:
    browser_logger = logging.getLogger(_BROWSER_LOGGER)
    for handler in [h for h in browser_logger.handlers if isinstance(h, _BrowserNotice)]:
        browser_logger.removeHandler(handler)
    if show:
        browser_logger.addHandler(_BrowserNotice(logging.WARNING))


app = typer.Typer(
    cls=_LookupByDefault,
    help="Collect what open sources know about a track or album.\n\n"
    'Usage: deadwax --track "Artist - Title", deadwax URL, or deadwax sources.',
    add_completion=False,
    no_args_is_help=True,
)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"deadwax {version('deadwax')}")
        raise typer.Exit


@app.callback()
def root(
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_show_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Collect what open sources know about a track or album."""


def _usage_error(message: str) -> typer.Exit:
    typer.echo(f"Error: {message}", err=True)
    return typer.Exit(EXIT_USAGE)


def _settings(config: Path | None, verbose: bool, **overrides: object) -> Settings:
    """Load settings and configure logging; configuration problems are usage errors."""
    try:
        settings = load_settings(config, **overrides)
    except ValidationError as error:
        typer.echo(f"Invalid configuration: {error}", err=True)
        raise typer.Exit(EXIT_USAGE) from error
    except ConfigurationError as error:
        raise _usage_error(str(error)) from error

    log = settings.log.model_copy(update={"level": "DEBUG"}) if verbose else settings.log
    setup_logging(log, console=verbose)
    _show_browser_notices(not verbose)
    if not verbose:
        # httpx logs every request at INFO; deadwax reports failures in the dossier instead.
        for name in ("httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.WARNING)
    return settings


@contextmanager
def _journal(ctx: typer.Context, settings: Settings, command: str) -> Iterator[RunJournal]:
    """Journal one command run; its exit code gives the outcome."""
    argv = list(ctx.meta.get(_ARGV_KEY, []))
    with run_journal(settings.run_log(), command=command, argv=argv) as journal:
        journal.event(TraceEvent.RUN_SETTINGS, settings=settings.model_dump(mode="json"))
        try:
            yield journal
        except typer.Exit as exit_:
            outcome = _OUTCOMES.get(exit_.exit_code, RunOutcome.CRASH)
            journal.set_outcome(outcome, exit_.exit_code)
            raise
        journal.set_outcome(RunOutcome.OK, 0)


def _facets(value: str | None) -> frozenset[Capability] | None:
    """Parse comma-separated facet names; an unknown name is an `InvalidQueryError`."""
    names = _names(value)
    if names is None:
        return None
    known = {facet.value: facet for facet in Capability}
    unknown = [name for name in names if name not in known]
    if unknown:
        raise InvalidQueryError(
            f"unknown facets: {', '.join(unknown)}; known: {', '.join(known)}",
        )
    return frozenset(known[name] for name in names)


def _names(value: str | None) -> list[str] | None:
    return [name.strip() for name in value.split(",") if name.strip()] if value else None


def _html_transports(value: str) -> tuple[str, ...]:
    """Split a complete, ordered list of HTML transports from a command option.

    The settings check the names, read 'patchright' as 'browser', and reject repeats.
    """
    names = tuple(name.strip().lower() for name in value.split(","))
    if not names or any(not name for name in names):
        raise _usage_error("--html-transport needs comma-separated transport names")
    return names


def _browser_overrides(
    headless: bool,
    headed: bool,
    html_transport: str | None,
) -> dict[str, object]:
    """Build one-run browser settings without changing saved configuration."""
    if headless and headed:
        raise _usage_error("--headless and --headed cannot be used together")
    overrides: dict[str, object] = {}
    http: dict[str, object] = {}
    source: dict[str, object] = {}
    if headless or headed:
        http["browser_headless"] = source["browser_headless"] = headless
    if html_transport is not None:
        steps = _html_transports(html_transport)
        http["escalation"] = tuple(step for step in steps if step != "httpx")
        source["html_transports"] = steps
    if source:
        overrides["sources"] = {name: dict(source) for name in PerSourceSettings.model_fields}
    if http:
        overrides["http"] = http
    return overrides


ConfigOption = Annotated[
    Path | None,
    typer.Option("--config", help="TOML settings file.", dir_okay=False, show_default=False),
]
VerboseOption = Annotated[
    bool,
    typer.Option("--verbose", "--debug", "-V", help="Log debug messages to stderr."),
]
FormatOption = Annotated[OutputFormat, typer.Option("--format", "-f", help="Output format.")]


@app.command("lookup")
def lookup_command(  # noqa: PLR0913 -- one parameter per command-line option
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="'Artist - Title' or a record page URL.")],
    *,
    album: Annotated[bool, typer.Option("--album", help="The query names an album.")] = False,
    track: Annotated[bool, typer.Option("--track", help="The query names a track.")] = False,
    sources: Annotated[
        str | None,
        typer.Option(
            "--sources",
            help=(
                "Only these sources or groups, comma-separated; 'all' selects every source; "
                "default: DEADWAX_DEFAULT_SOURCES."
            ),
        ),
    ] = None,
    exclude: Annotated[
        str | None,
        typer.Option("--exclude", help="Skip these sources or groups, comma-separated."),
    ] = None,
    facets: Annotated[
        str | None,
        typer.Option(
            "--facets",
            help=(
                "Only these kinds of facts, comma-separated: "
                f"{', '.join(facet.value for facet in Capability)}; default: all."
            ),
        ),
    ] = None,
    output: FormatOption = OutputFormat.PRETTY,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Bypass the cache.")] = False,
    timeout: Annotated[
        float | None,
        typer.Option("--timeout", min=0.001, help="Seconds per source."),
    ] = None,
    headless: Annotated[
        bool,
        typer.Option("--headless", help="Run Patchright and Nodriver without a window."),
    ] = False,
    headed: Annotated[
        bool,
        typer.Option("--headed", help="Show Patchright and Nodriver windows."),
    ] = False,
    html_transport: Annotated[
        str | None,
        typer.Option("--html-transport", help="HTML transports for this lookup, in order."),
    ] = None,
    config: ConfigOption = None,
    verbose: VerboseOption = False,
) -> None:
    """Look up a track or album (the default command)."""
    overrides: dict[str, object] = {}
    if no_cache:
        overrides["cache"] = {"enabled": False}
    if timeout is not None:
        overrides["adapter_timeout"] = timeout
    overrides.update(_browser_overrides(headless, headed, html_transport))
    settings = _settings(config, verbose, **overrides)

    with _journal(ctx, settings, "lookup") as journal:
        if album and track:
            raise _usage_error("--album and --track are mutually exclusive")
        kind = EntityKind.ALBUM if album else EntityKind.TRACK if track else None
        try:
            parsed = parse_query(query, kind)
            request = Request(query=parsed, facets=_facets(facets))
            journal.event(TraceEvent.QUERY_PARSED, query=parsed.model_dump(mode="json"))
            dossier: Dossier = asyncio.run(
                lookup(
                    request,
                    settings.lookup_config(),
                    include=_names(sources),
                    exclude=_names(exclude) or (),
                ),
            )
        except (InvalidQueryError, ConfigurationError) as error:
            raise _usage_error(str(error)) from error

        journal.record(dossier)
        print_dossier(dossier, output)
        if not dossier.found:
            raise typer.Exit(EXIT_NOTHING_MATCHED)


@app.command("sources")
def sources_command(
    ctx: typer.Context,
    output: FormatOption = OutputFormat.PRETTY,
    config: ConfigOption = None,
    verbose: VerboseOption = False,
) -> None:
    """List the sources, their groups, what they contribute, and whether they can run."""
    settings = _settings(config, verbose)
    with _journal(ctx, settings, "sources"):
        try:
            infos = describe_sources(settings.lookup_config())
        except ConfigurationError as error:
            raise _usage_error(str(error)) from error
        print_sources(infos, output)


def select_runs(  # noqa: PLR0913 -- one parameter per filter
    records: list[RunRecord],
    *,
    failed: bool = False,
    no_match: bool = False,
    source: str | None = None,
    kind: str | None = None,
    text: str | None = None,
) -> list[RunRecord]:
    """Return the runs that pass every given filter, newest first."""
    selected = []
    for record in reversed(records):
        statuses = record.sources
        if failed and record.outcome not in _FAILED:
            continue
        if no_match and record.found is not False and "no_match" not in statuses.values():
            continue
        if source is not None and statuses.get(source, "ok") == "ok":
            continue
        if kind is not None and kind not in statuses.values():
            continue
        searched = " ".join([record.query or "", record.identity or "", *record.argv])
        if text is not None and text.casefold() not in searched.casefold():
            continue
        selected.append(record)
    return selected


@app.command("runs")
def runs_command(  # noqa: PLR0913 -- one parameter per command-line option
    run_id: Annotated[
        str | None,
        typer.Argument(help="Show one run: the start of its id or of its random suffix."),
    ] = None,
    *,
    limit: Annotated[int, typer.Option("--limit", "-n", min=1, help="Runs listed.")] = 20,
    failed: Annotated[
        bool,
        typer.Option("--failed", help="Only runs that did not end with a match."),
    ] = False,
    no_match: Annotated[
        bool,
        typer.Option("--no-match", help="Only runs where a source's candidate was rejected."),
    ] = False,
    source: Annotated[
        str | None,
        typer.Option("--source", help="Only runs where this source did not answer 'ok'."),
    ] = None,
    kind: Annotated[
        str | None,
        typer.Option("--kind", help="Only runs with a source status such as blocked or timeout."),
    ] = None,
    query: Annotated[
        str | None,
        typer.Option("--query", "-q", help="Only runs whose query or identity contains this."),
    ] = None,
    full: Annotated[
        bool,
        typer.Option("--full", help="Also show the merges run between passes."),
    ] = False,
    output: FormatOption = OutputFormat.PRETTY,
    config: ConfigOption = None,
    verbose: VerboseOption = False,
) -> None:
    """List journaled runs, or show the events of one run."""
    root = _settings(config, verbose).run_log().dir
    assert root is not None  # noqa: S101 -- run_log() always sets the directory

    if run_id is not None:
        try:
            path = find_run(root, run_id)
        except RunNotFoundError as error:
            raise _usage_error(str(error)) from error
        print_run(read_events(path), output, full=full)
        return

    records = select_runs(
        read_runs(root),
        failed=failed,
        no_match=no_match,
        source=source,
        kind=kind,
        text=query,
    )
    print_runs(records[:limit], output, root)
