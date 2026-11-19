import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from enum import StrEnum
from types import MappingProxyType

# Name of the record attribute that carries an event's structured fields.
TRACE_ATTRIBUTE = "deadwax"


class TraceEvent(StrEnum):
    """Name of a structured debug event in the run journal."""

    RUN_START = "run.start"
    RUN_SETTINGS = "run.settings"
    RUN_END = "run.end"
    RUN_CRASH = "run.crash"
    QUERY_PARSED = "query.parsed"
    LOOKUP_SELECTED = "lookup.selected"
    LOOKUP_RESOLVER = "lookup.resolver"
    LOOKUP_KIND_ADOPTED = "lookup.kind_adopted"
    PASS_START = "pass.start"  # noqa: S105 -- an event name, not a password
    ADAPTER_END = "adapter.end"
    MATCH_COMPARE = "match.compare"
    MERGE_REFERENCE = "merge.reference"
    MERGE_JUDGE = "merge.judge"
    HTTP_REQUEST = "http.request"
    HTTP_RETRY = "http.retry"
    HTTP_CHALLENGE = "http.challenge"
    HTTP_HEADED_FALLBACK = "http.headed_fallback"
    HTTP_PAGE_INCOMPLETE = "http.page_incomplete"
    HTTP_STEP_DROPPED = "http.step_dropped"
    HTTP_STEP_FAILED = "http.step_failed"
    SEARCH_PICK = "search.pick"
    SEARCH_RANKED = "search.ranked"
    PARSE_UNRECOGNIZED = "parse.unrecognized"
    WFMU_TRUNCATED = "wfmu.truncated"


_scope: ContextVar[Mapping[str, object]] = ContextVar(
    "deadwax_trace_scope",
    default=MappingProxyType({}),
)


def trace_fields() -> dict[str, object]:
    """Return the fields bound by the enclosing `trace_scope` blocks."""
    return dict(_scope.get())


@contextmanager
def trace_scope(**fields: object) -> Iterator[None]:
    """Add fields to every event emitted inside the block, including in tasks it starts."""
    token = _scope.set({**_scope.get(), **fields})
    try:
        yield
    finally:
        _scope.reset(token)


def trace(logger: logging.Logger, event: TraceEvent, /, **fields: object) -> None:
    """Log a structured debug event; fields must be JSON values and are skipped when unused."""
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(event.value, extra={TRACE_ATTRIBUTE: {**_scope.get(), **fields}}, stacklevel=2)


class TraceFilter(logging.Filter):
    """Attach the current trace scope to records logged without `trace`."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Add the scope fields under the `deadwax` record attribute; never drops a record."""
        if not hasattr(record, TRACE_ATTRIBUTE):
            setattr(record, TRACE_ATTRIBUTE, trace_fields())
        return True
