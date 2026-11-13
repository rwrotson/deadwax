import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from types import MappingProxyType

# Name of the record attribute that carries an event's structured fields.
TRACE_ATTRIBUTE = "deadwax"

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


def trace(logger: logging.Logger, event: str, /, **fields: object) -> None:
    """Log a structured debug event; fields must be JSON values and are skipped when unused."""
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(event, extra={TRACE_ATTRIBUTE: {**_scope.get(), **fields}}, stacklevel=2)


class TraceFilter(logging.Filter):
    """Attach the current trace scope to records logged without `trace`."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Add the scope fields under the `deadwax` record attribute; never drops a record."""
        if not hasattr(record, TRACE_ATTRIBUTE):
            setattr(record, TRACE_ATTRIBUTE, trace_fields())
        return True
