import logging
import subprocess
import sys

import deadwax


def test_package_logger_has_null_handler() -> None:
    handlers = logging.getLogger("deadwax").handlers
    assert any(isinstance(handler, logging.NullHandler) for handler in handlers)


def test_public_api_names_exist() -> None:
    assert all(hasattr(deadwax, name) for name in deadwax.__all__)


def test_import_leaves_global_logging_unconfigured() -> None:
    code = (
        "import logging, structlog, deadwax; "
        "print(len(logging.getLogger().handlers), structlog.is_configured())"
    )

    # Run in a fresh interpreter: this process already configured logging in other tests.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.split() == ["0", "False"]


OPTIONAL_PACKAGES = (
    "structlog",
    "pydantic_settings",
    "typer",
    "rich",
    "platformdirs",
    "curl_cffi",
    "playwright",
)


def test_import_does_not_load_optional_dependencies() -> None:
    code = f"import sys, deadwax; print(*(name in sys.modules for name in {OPTIONAL_PACKAGES!r}))"

    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.split() == ["False"] * len(OPTIONAL_PACKAGES)


def test_logs_package_reports_missing_extra() -> None:
    # A None entry in sys.modules makes the import fail as if the package were not installed.
    code = (
        "import sys; sys.modules['structlog'] = None\n"
        "try:\n    import deadwax.logs\n"
        "except ModuleNotFoundError as error:\n    print(error.name, error)"
    )

    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.startswith("structlog ")
    assert "deadwax[logs]" in result.stdout


def test_logs_package_does_not_load_the_sources_layer() -> None:
    code = (
        "import sys, deadwax.logs; print('deadwax.sources' in sys.modules, 'httpx' in sys.modules)"
    )

    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.split() == ["False", "False"]
