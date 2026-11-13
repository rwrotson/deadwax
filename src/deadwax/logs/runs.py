import asyncio
import contextlib
import json
import logging
import os
import platform
import secrets
import shutil
import sys
import threading
import time
from collections.abc import Mapping
from contextvars import ContextVar, Token
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from importlib.metadata import version
from pathlib import Path
from types import TracebackType
from typing import Self

import structlog
from pydantic import BaseModel, ValidationError

from deadwax import (
    TRACE_ATTRIBUTE,
    ConfigurationError,
    DeadwaxError,
    Dossier,
    ErrorKind,
    Query,
    TraceFilter,
)
from deadwax.logs.settings import RunLogSettings
from deadwax.logs.setup import add_trace_fields

INDEX_FILE = "runs.jsonl"
RUNS_DIR = "runs"

_LIBRARY = "deadwax"

# Records of other libraries, such as httpx, are journaled from this level on.
_FOREIGN_LEVEL = logging.WARNING

logger = logging.getLogger(__name__)

_current_run: ContextVar[str | None] = ContextVar("deadwax_current_run", default=None)


class RunOutcome(StrEnum):
    """How a run ended."""

    OK = "ok"
    NOTHING_MATCHED = "nothing_matched"
    USAGE_ERROR = "usage_error"
    CRASH = "crash"
    INTERRUPTED = "interrupted"


class RunNotFoundError(DeadwaxError, LookupError):
    """No journaled run, or more than one, has the given id."""


class RunError(BaseModel):
    """Error one source reported in a run."""

    source: str
    kind: ErrorKind
    reason: str


class RunRecord(BaseModel):
    """Summary of one run, as stored in the index of runs."""

    run_id: str
    started_at: datetime
    duration_ms: int
    command: str
    label: str | None = None
    argv: list[str] = []
    version: str
    outcome: RunOutcome
    exit_code: int | None = None
    query: str | None = None
    kind: str | None = None
    found: bool | None = None
    identity: str | None = None
    sources: dict[str, str] = {}
    errors: list[RunError] = []
    discrepancies: list[str] = []
    warnings: int = 0
    file: str


def _is_library(record: logging.LogRecord) -> bool:
    return record.name == _LIBRARY or record.name.startswith(f"{_LIBRARY}.")


def _formatter(run_id: str) -> logging.Formatter:
    def add_run_id(
        _logger: object,
        _method: str,
        event_dict: structlog.types.EventDict,
    ) -> structlog.types.EventDict:
        event_dict["run_id"] = run_id
        return event_dict

    return structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            add_trace_fields,
            add_run_id,
        ],
    )


class _RunSink(logging.FileHandler):
    """Write one run's records and note what its sources did."""

    def __init__(self, path: Path, run_id: str) -> None:
        super().__init__(path, encoding="utf-8")
        self.setFormatter(_formatter(run_id))
        self.sources: dict[str, str] = {}
        self.warnings = 0

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.WARNING:
            self.warnings += 1
        fields = getattr(record, TRACE_ATTRIBUTE, None)
        if record.msg == "adapter.end" and isinstance(fields, Mapping):
            source, errors = fields.get("source"), fields.get("errors")
            if isinstance(source, str):
                first = errors[0] if isinstance(errors, list) and errors else None
                self.sources[source] = (
                    first.get("kind", "error") if isinstance(first, dict) else "ok"
                )
        super().emit(record)


class _Router(logging.Handler):
    """Hand each record to the sink of the run in whose context it was logged."""

    def __init__(self, sinks: Mapping[str, _RunSink]) -> None:
        super().__init__(logging.DEBUG)
        self._sinks = sinks
        self.addFilter(TraceFilter())

    def emit(self, record: logging.LogRecord) -> None:
        run_id = _current_run.get()
        sink = self._sinks.get(run_id) if run_id is not None else None
        if sink is not None:
            sink.handle(record)


class _Forward(logging.Handler):
    """Pass library records on to the root logger at the level the application had set."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.threshold = logging.NOTSET

    def emit(self, record: logging.LogRecord) -> None:
        root = logging.getLogger()
        if record.levelno >= (self.threshold or root.getEffectiveLevel()):
            root.handle(record)


class _Journals:
    """Shared logging hooks of the open journals, installed while at least one is open.

    The library logger is lowered to DEBUG and stops propagating; `_Forward` gives the
    application's handlers only the records they would have received before.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.sinks: dict[str, _RunSink] = {}
        self.library = _Router(self.sinks)
        self.foreign = _Router(self.sinks)
        self.foreign.addFilter(
            lambda record: not _is_library(record) and record.levelno >= _FOREIGN_LEVEL,
        )
        self.forward = _Forward()
        self.saved = (logging.NOTSET, True)

    def add(self, run_id: str, sink: _RunSink) -> None:
        with self.lock:
            if not self.sinks:
                self._install()
            self.sinks[run_id] = sink

    def remove(self, run_id: str) -> None:
        with self.lock:
            if self.sinks.pop(run_id, None) is not None and not self.sinks:
                self._uninstall()

    def _install(self) -> None:
        library = logging.getLogger(_LIBRARY)
        self.saved = (library.level, library.propagate)
        self.forward.threshold = library.level
        library.setLevel(logging.DEBUG)
        library.addHandler(self.library)
        if library.propagate:
            library.addHandler(self.forward)
        library.propagate = False
        logging.getLogger().addHandler(self.foreign)

    def _uninstall(self) -> None:
        library = logging.getLogger(_LIBRARY)
        library.removeHandler(self.library)
        library.removeHandler(self.forward)
        library.setLevel(self.saved[0])
        library.propagate = self.saved[1]
        logging.getLogger().removeHandler(self.foreign)


_journals = _Journals()


def _new_run_id(now: datetime) -> str:
    return f"{now:%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"


def _describe_query(query: Query) -> str:
    if query.artist and query.title:
        return f"{query.artist} - {query.title}"
    return query.url or ""


def _line_day(line: str) -> str:
    """Return the ISO day an index line was started on; unreadable lines are kept."""
    try:
        started = json.loads(line).get("started_at", "")
    except ValueError, AttributeError:
        return "9999"
    return started[:10] if isinstance(started, str) and started else "9999"


def prune_runs(root: Path, retention_days: int, today: date) -> None:
    """Delete runs started more than `retention_days` days before today; 0 keeps every run."""
    if retention_days == 0:
        return
    cutoff = (today - timedelta(days=retention_days)).isoformat()

    runs = root / RUNS_DIR
    if runs.is_dir():
        for day in runs.iterdir():
            if day.is_dir() and day.name < cutoff:
                shutil.rmtree(day, ignore_errors=True)

    index = root / INDEX_FILE
    if not index.is_file():
        return
    lines = index.read_text(encoding="utf-8").splitlines(keepends=True)
    if not lines or _line_day(lines[0]) >= cutoff:
        return
    kept = [line for line in lines if _line_day(line) >= cutoff]
    temporary = index.with_suffix(".tmp")
    temporary.write_text("".join(kept), encoding="utf-8")
    temporary.replace(index)


class RunJournal:
    """Journal of one run; use it as a context manager around one lookup."""

    def __init__(
        self,
        settings: RunLogSettings,
        *,
        command: str = "lookup",
        label: str | None = None,
        argv: list[str] | None = None,
    ) -> None:
        if settings.enabled and settings.dir is None:
            raise ConfigurationError("the run journal needs a directory: set RunLogSettings.dir")
        self.settings = settings
        self.command = command
        self.label = label
        self.argv = argv or []
        self.started_at = datetime.now(UTC)
        self.run_id = _new_run_id(self.started_at)
        self.path: Path | None = None
        self.error: str | None = None

        self._clock = time.monotonic()
        self._dossier: Dossier | None = None
        self._outcome: tuple[RunOutcome, int | None] | None = None
        self._sink: _RunSink | None = None
        self._token: Token[str | None] | None = None

    def event(self, name: str, /, **fields: object) -> None:
        """Write an event of the caller's own to the run; fields must be JSON values."""
        if self._sink is not None:
            logger.debug(name, extra={TRACE_ATTRIBUTE: fields}, stacklevel=2)

    def record(self, dossier: Dossier) -> None:
        """Keep the run's dossier for its summary and its last event."""
        self._dossier = dossier

    def set_outcome(self, outcome: RunOutcome, exit_code: int | None = None) -> None:
        """State how the run ended instead of inferring it, as a command does with exit codes."""
        self._outcome = (outcome, exit_code)

    def open(self) -> None:
        """Start writing the run; a directory that cannot be written disables the journal."""
        if not self.settings.enabled or self._sink is not None:
            return
        root = self.settings.dir
        assert root is not None  # noqa: S101 -- checked in __init__
        path = root / RUNS_DIR / self.started_at.date().isoformat() / f"{self.run_id}.jsonl"
        try:
            prune_runs(root, self.settings.retention_days, self.started_at.date())
            path.parent.mkdir(parents=True, exist_ok=True)
            sink = _RunSink(path, self.run_id)
        except OSError as error:
            self.error = f"cannot write the run journal in {root}: {error}"
            logger.warning(self.error)
            return

        self.path, self._sink = path, sink
        _journals.add(self.run_id, sink)
        self._token = _current_run.set(self.run_id)
        self.event(
            "run.start",
            command=self.command,
            label=self.label,
            argv=self.argv,
            version=version("deadwax"),
            python=sys.version.split()[0],
            platform=platform.platform(),
            pid=os.getpid(),
        )

    def close(self, error: BaseException | None = None) -> RunRecord | None:
        """Finish the run, append it to the index, and return its summary."""
        sink, root = self._sink, self.settings.dir
        if sink is None or root is None:
            return None

        outcome, exit_code = self._final_outcome(error)
        if outcome is RunOutcome.CRASH and error is not None:
            logger.debug("run.crash", exc_info=error, extra={TRACE_ATTRIBUTE: {}})
        summary = self._summary(sink, root, outcome, exit_code)
        fields: dict[str, object] = {"summary": summary.model_dump(mode="json")}
        if self.settings.dossier and self._dossier is not None:
            fields["dossier"] = self._dossier.model_dump(mode="json")
        self.event("run.end", **fields)

        _journals.remove(self.run_id)
        if self._token is not None:
            # A journal closed in another context than it was opened in leaves that one alone.
            with contextlib.suppress(ValueError):
                _current_run.reset(self._token)
        sink.close()
        self._sink = None
        try:
            with (root / INDEX_FILE).open("a", encoding="utf-8") as index:
                index.write(summary.model_dump_json() + "\n")
        except OSError as failure:
            logger.warning("cannot add run %s to the index: %s", self.run_id, failure)
        return summary

    def _final_outcome(self, error: BaseException | None) -> tuple[RunOutcome, int | None]:
        if self._outcome is not None:
            return self._outcome
        if isinstance(error, (KeyboardInterrupt, asyncio.CancelledError)):
            return RunOutcome.INTERRUPTED, None
        if error is not None:
            return RunOutcome.CRASH, None
        if self._dossier is not None and not self._dossier.found:
            return RunOutcome.NOTHING_MATCHED, None
        return RunOutcome.OK, None

    def _summary(
        self,
        sink: _RunSink,
        root: Path,
        outcome: RunOutcome,
        exit_code: int | None,
    ) -> RunRecord:
        assert self.path is not None  # noqa: S101 -- set together with the sink
        record = RunRecord(
            run_id=self.run_id,
            started_at=self.started_at,
            duration_ms=round((time.monotonic() - self._clock) * 1000),
            command=self.command,
            label=self.label,
            argv=self.argv,
            version=version("deadwax"),
            outcome=outcome,
            exit_code=exit_code,
            sources=dict(sink.sources),
            warnings=sink.warnings,
            file=self.path.relative_to(root).as_posix(),
        )
        dossier = self._dossier
        if dossier is None:
            return record

        identity = dossier.identity
        for error in dossier.errors:
            record.sources[error.source] = str(error.kind)
        record.errors = [
            RunError(source=error.source, kind=error.kind, reason=error.reason)
            for error in dossier.errors
        ]
        record.query = _describe_query(dossier.query)
        kind = identity.kind or dossier.query.kind
        record.kind = None if kind is None else str(kind)
        record.found = dossier.found
        if identity.artist is not None and identity.title is not None:
            record.identity = f"{identity.artist.value} - {identity.title.value}"
        record.discrepancies = [discrepancy.field for discrepancy in identity.discrepancies]
        return record

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close(exc)

    async def __aenter__(self) -> Self:
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close(exc)


def run_journal(
    settings: RunLogSettings,
    *,
    command: str = "lookup",
    label: str | None = None,
    argv: list[str] | None = None,
) -> RunJournal:
    """Create the journal of one run; it writes nothing until entered or opened.

    Raises `ConfigurationError` when the journal is enabled without a directory.
    """
    return RunJournal(settings, command=command, label=label, argv=argv)


def read_runs(root: Path) -> list[RunRecord]:
    """Return the indexed runs, oldest first; unreadable lines are skipped."""
    index = root / INDEX_FILE
    if not index.is_file():
        return []
    records = []
    for line in index.read_text(encoding="utf-8").splitlines():
        try:
            records.append(RunRecord.model_validate_json(line))
        except ValidationError:
            logger.debug("unreadable run index line: %.80s", line)
    return records


def find_run(root: Path, run_id: str) -> Path:
    """Return the event file of the run whose id, or random suffix, starts with `run_id`."""
    files = sorted((root / RUNS_DIR).glob("*/*.jsonl"))
    exact = [path for path in files if path.stem == run_id]
    matches = exact or [
        path
        for path in files
        if path.stem.startswith(run_id) or path.stem.partition("-")[2].startswith(run_id)
    ]
    if not run_id or not matches:
        raise RunNotFoundError(f"no run {run_id!r} in {root}")
    if len(matches) > 1:
        names = ", ".join(path.stem for path in matches[:5])
        raise RunNotFoundError(f"{run_id!r} names {len(matches)} runs: {names}")
    return matches[0]


def read_events(path: Path) -> list[dict[str, object]]:
    """Return the events of one run's file; unreadable lines are skipped."""
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events
