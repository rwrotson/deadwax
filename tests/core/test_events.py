import asyncio
import logging
import re
from collections.abc import Callable

import pytest

from deadwax.core import TraceEvent, TraceFilter, trace, trace_fields, trace_scope

type Traced = Callable[[str], list[dict[str, object]]]

logger = logging.getLogger("deadwax.tests")


def test_events_carry_their_fields_and_the_scope(traced: Traced) -> None:
    with trace_scope(source="itunes"), trace_scope(stage="final"):
        trace(logger, TraceEvent.SEARCH_PICK, score=0.5)
    trace(logger, TraceEvent.SEARCH_PICK, score=1)

    assert traced(TraceEvent.SEARCH_PICK) == [
        {"source": "itunes", "stage": "final", "score": 0.5},
        {"score": 1},
    ]


def test_event_fields_win_over_the_scope(traced: Traced) -> None:
    with trace_scope(source="itunes"):
        trace(logger, TraceEvent.SEARCH_PICK, source="deezer")

    assert traced(TraceEvent.SEARCH_PICK) == [{"source": "deezer"}]


def test_events_are_skipped_without_a_debug_listener(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="deadwax")

    trace(logger, TraceEvent.SEARCH_PICK)

    assert caplog.records == []


def test_scope_is_restored_after_the_block() -> None:
    with trace_scope(source="itunes"):
        assert trace_fields() == {"source": "itunes"}
    assert trace_fields() == {}


@pytest.mark.asyncio
async def test_tasks_inherit_the_scope() -> None:
    async def fields() -> dict[str, object]:
        return trace_fields()

    with trace_scope(source="itunes"):
        task = asyncio.create_task(fields())
    assert await task == {"source": "itunes"}


def test_filter_attaches_the_scope_to_plain_records() -> None:
    plain = logging.LogRecord("deadwax", logging.DEBUG, __file__, 1, "plain", None, None)
    traced_record = logging.LogRecord("deadwax", logging.DEBUG, __file__, 1, "event", None, None)
    traced_record.deadwax = {"score": 1}

    with trace_scope(source="itunes"):
        assert TraceFilter().filter(plain)
        assert TraceFilter().filter(traced_record)

    assert getattr(plain, "deadwax", None) == {"source": "itunes"}
    assert getattr(traced_record, "deadwax", None) == {"score": 1}


def test_event_names_are_dotted_lowercase() -> None:
    for event in TraceEvent:
        assert re.fullmatch(r"[a-z]+\.[a-z_]+", event.value), event


def test_records_carry_the_event_name_as_plain_text(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="deadwax")

    trace(logger, TraceEvent.HTTP_REQUEST)

    assert [type(record.msg) for record in caplog.records] == [str]
    assert caplog.records[0].getMessage() == "http.request"
