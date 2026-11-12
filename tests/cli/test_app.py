import logging
from importlib.metadata import version

import pytest
from typer.testing import CliRunner

from deadwax.cli.app import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"deadwax {version('deadwax')}"


def test_no_command_shows_help() -> None:
    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "Usage" in result.output


def test_settings_configure_logging(
    monkeypatch: pytest.MonkeyPatch, clean_root_logger: logging.Logger
) -> None:
    monkeypatch.setenv("DEADWAX_LOG__LEVEL", "ERROR")

    runner.invoke(app, [])

    assert clean_root_logger.level == logging.ERROR


def test_verbose_enables_debug_logging(
    monkeypatch: pytest.MonkeyPatch, clean_root_logger: logging.Logger
) -> None:
    monkeypatch.setenv("DEADWAX_LOG__LEVEL", "ERROR")

    runner.invoke(app, ["--verbose"])

    assert clean_root_logger.level == logging.DEBUG


def test_invalid_configuration_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEADWAX_LOG__LEVEL", "LOUD")

    result = runner.invoke(app, [])

    assert result.exit_code == 2
    assert result.stderr.startswith("Invalid configuration:")
