try:
    from .runs import (
        RunError,
        RunJournal,
        RunNotFoundError,
        RunOutcome,
        RunRecord,
        find_run,
        prune_runs,
        read_events,
        read_runs,
        run_journal,
    )
    from .settings import LogSettings, RunLogSettings
    from .setup import add_trace_fields, setup_logging
except ModuleNotFoundError as error:
    if error.name != "structlog":
        raise
    raise ModuleNotFoundError(
        "deadwax.logs requires the 'logs' extra; install 'deadwax[logs]'",
        name=error.name,
    ) from error

__all__ = [
    "LogSettings",
    "RunError",
    "RunJournal",
    "RunLogSettings",
    "RunNotFoundError",
    "RunOutcome",
    "RunRecord",
    "add_trace_fields",
    "find_run",
    "prune_runs",
    "read_events",
    "read_runs",
    "run_journal",
    "setup_logging",
]
