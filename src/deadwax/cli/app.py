import asyncio
import logging
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from typer.core import TyperGroup

from deadwax import (
    ConfigurationError,
    Dossier,
    EntityKind,
    InvalidQueryError,
    describe_sources,
    lookup,
    parse_query,
)
from deadwax.cli.render import OutputFormat, print_dossier, print_sources
from deadwax.cli.settings import Settings, load_settings
from deadwax.logs import setup_logging

EXIT_USAGE = 2
EXIT_NOTHING_MATCHED = 3

# Root options handled by the group itself; anything else starts a lookup.
_ROOT_OPTIONS = frozenset({"--help", "-h", "--version"})


class _LookupByDefault(TyperGroup):
    """Run `lookup` when the first argument is not a subcommand, so `deadwax QUERY` works."""

    # typer.Context subclasses the click Context Typer vendors in a private module.
    def parse_args(self, ctx: typer.Context, args: list[str]) -> list[str]:  # type: ignore[override]
        if args and args[0] not in self.commands and args[0] not in _ROOT_OPTIONS:
            args = ["lookup", *args]
        return super().parse_args(ctx, args)


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
    setup_logging(log)
    if not verbose:
        # httpx logs every request at INFO; deadwax reports failures in the dossier instead.
        for name in ("httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.WARNING)
    return settings


def _names(value: str | None) -> list[str] | None:
    return [name.strip() for name in value.split(",") if name.strip()] if value else None


ConfigOption = Annotated[
    Path | None,
    typer.Option("--config", help="TOML settings file.", dir_okay=False, show_default=False),
]
VerboseOption = Annotated[bool, typer.Option("--verbose", "-V", help="Log debug messages.")]
FormatOption = Annotated[OutputFormat, typer.Option("--format", "-f", help="Output format.")]


@app.command("lookup")
def lookup_command(  # noqa: PLR0913 -- one parameter per command-line option
    query: Annotated[str, typer.Argument(help="'Artist - Title' or a record page URL.")],
    *,
    album: Annotated[bool, typer.Option("--album", help="The query names an album.")] = False,
    track: Annotated[bool, typer.Option("--track", help="The query names a track.")] = False,
    sources: Annotated[
        str | None,
        typer.Option("--sources", help="Only these sources, comma-separated."),
    ] = None,
    exclude: Annotated[
        str | None,
        typer.Option("--exclude", help="Skip these sources, comma-separated."),
    ] = None,
    output: FormatOption = OutputFormat.PRETTY,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Bypass the cache.")] = False,
    timeout: Annotated[
        float | None,
        typer.Option("--timeout", min=0.001, help="Seconds per source."),
    ] = None,
    config: ConfigOption = None,
    verbose: VerboseOption = False,
) -> None:
    """Look up a track or album (the default command)."""
    if album and track:
        raise _usage_error("--album and --track are mutually exclusive")

    kind = EntityKind.ALBUM if album else EntityKind.TRACK if track else None
    overrides: dict[str, object] = {}
    if no_cache:
        overrides["cache"] = {"enabled": False}
    if timeout is not None:
        overrides["adapter_timeout"] = timeout
    settings = _settings(config, verbose, **overrides)

    try:
        parsed = parse_query(query, kind)
        dossier: Dossier = asyncio.run(
            lookup(
                parsed,
                settings.sources_config(),
                include=_names(sources),
                exclude=_names(exclude) or (),
            ),
        )
    except (InvalidQueryError, ConfigurationError) as error:
        raise _usage_error(str(error)) from error

    print_dossier(dossier, output)
    if not dossier.found:
        raise typer.Exit(EXIT_NOTHING_MATCHED)


@app.command("sources")
def sources_command(
    output: FormatOption = OutputFormat.PRETTY,
    config: ConfigOption = None,
    verbose: VerboseOption = False,
) -> None:
    """List the sources, what they contribute, and whether they can run."""
    settings = _settings(config, verbose)
    print_sources(describe_sources(settings.sources_config()), output)
