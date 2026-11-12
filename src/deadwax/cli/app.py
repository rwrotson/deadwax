from importlib.metadata import version
from typing import Annotated

import typer
from pydantic import ValidationError

from deadwax.cli.settings import load_settings
from deadwax.logs import setup_logging

app = typer.Typer(
    help="Collect what open sources know about a track or album.", add_completion=False
)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"deadwax {version('deadwax')}")
        raise typer.Exit


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    verbose: Annotated[bool, typer.Option("--verbose", "-V", help="Log debug messages.")] = False,
    _version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_show_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
) -> None:
    """Load DEADWAX_* settings and configure logging for one invocation."""
    try:
        settings = load_settings()
    except ValidationError as error:
        typer.echo(f"Invalid configuration: {error}", err=True)
        raise typer.Exit(2) from error

    log_settings = settings.log.model_copy(update={"level": "DEBUG"}) if verbose else settings.log
    setup_logging(log_settings)

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
