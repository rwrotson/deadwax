import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Collection, Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from deadwax.core.adapter import Adapter, LookupContext, Pass, SourceGroup, SourceState
from deadwax.core.errors import (
    BlockedError,
    ConfigurationError,
    NotFoundError,
    RateLimitedError,
    SourceError,
)
from deadwax.core.events import trace, trace_scope
from deadwax.core.merge import merge
from deadwax.core.models import AdapterError, Dossier, ErrorKind, Partial
from deadwax.core.query import Query

logger = logging.getLogger(__name__)

_ERROR_KINDS: tuple[tuple[type[SourceError], ErrorKind], ...] = (
    (BlockedError, ErrorKind.BLOCKED),
    (RateLimitedError, ErrorKind.RATE_LIMITED),
    (NotFoundError, ErrorKind.NOT_FOUND),
)


def _now() -> datetime:
    return datetime.now(UTC)


def _failure(adapter: Adapter, kind: ErrorKind, reason: str, url: str | None = None) -> Partial:
    error = AdapterError(source=adapter.name, kind=kind, reason=reason, url=url)
    return Partial(source=adapter.name, errors=[error])


def _milliseconds(start: float) -> int:
    return round((time.monotonic() - start) * 1000)


def _outcome(partial: Partial) -> dict[str, object]:
    """Describe an adapter's result for the `adapter.end` event."""
    candidate = partial.candidate
    return {
        "outcome": "error" if partial.errors else "ok",
        "errors": [error.model_dump(mode="json", exclude={"source"}) for error in partial.errors],
        "candidate": None if candidate is None else candidate.model_dump(mode="json"),
        "facts": {
            "tags": len(partial.tags),
            "credits": len(partial.credits),
            "texts": len(partial.texts),
            "relations": len(partial.relations),
            "metrics": len(partial.metrics),
            "links": len(partial.links),
        },
    }


async def _call(
    adapter: Adapter,
    query: Query,
    context: LookupContext,
    seconds: float,
    slots: asyncio.Semaphore | None,
) -> Partial:
    """Run one adapter; every failure except cancellation becomes an error in its partial.

    The timeout starts once the adapter has a slot, so waiting for one costs it nothing.
    """
    queued = time.monotonic()
    with trace_scope(source=adapter.name):
        async with slots or contextlib.nullcontext():
            started = time.monotonic()
            partial = await _timed(adapter, query, context, seconds)
        trace(
            logger,
            "adapter.end",
            duration_ms=_milliseconds(started),
            slot_wait_ms=round((started - queued) * 1000),
            **_outcome(partial),
        )
        return partial


async def _timed(adapter: Adapter, query: Query, context: LookupContext, seconds: float) -> Partial:
    try:
        async with asyncio.timeout(seconds):
            return await adapter.lookup(query, context)
    except TimeoutError:
        return _failure(adapter, ErrorKind.TIMEOUT, f"no answer within {seconds:g} s")
    except SourceError as error:
        kind = next((k for cls, k in _ERROR_KINDS if isinstance(error, cls)), ErrorKind.FAILED)
        return _failure(adapter, kind, str(error), error.url)
    except Exception as error:
        logger.warning("%s failed", adapter.name, exc_info=True)
        return _failure(adapter, ErrorKind.FAILED, f"{type(error).__name__}: {error}")


class LookupOptions(BaseModel):
    """Which adapters run and how long each may take."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter_timeout: float = Field(default=30.0, gt=0, description="Seconds per adapter")
    adapter_timeouts: dict[str, float] = Field(
        default_factory=dict,
        description="Per-adapter overrides of the timeout",
    )
    include: frozenset[str] | None = Field(
        default=None,
        description="Source and group names to run; all when unset",
    )
    exclude: frozenset[str] = Field(
        default=frozenset(),
        description="Source and group names not to run",
    )
    concurrency: int | None = Field(
        default=None,
        ge=1,
        description="Adapters run at once; unlimited when unset",
    )

    def timeout_for(self, source: str) -> float:
        """Return the timeout of one adapter."""
        return self.adapter_timeouts.get(source, self.adapter_timeout)


def expand_names(names: Collection[str], adapters: Sequence[Adapter]) -> frozenset[str]:
    """Turn source and group names into the names of the adapters they denote."""
    sources = [adapter.name for adapter in adapters]
    groups = [group.value for group in SourceGroup]
    unknown = sorted(set(names) - {*sources, *groups})
    if unknown:
        raise ConfigurationError(
            f"unknown sources: {', '.join(unknown)}; "
            f"known: {', '.join(sources)}; groups: {', '.join(groups)}",
        )
    return frozenset(
        adapter.name for adapter in adapters if {adapter.name, adapter.group.value} & set(names)
    )


def _select(
    adapters: Sequence[Adapter],
    options: LookupOptions,
) -> tuple[list[Adapter], list[AdapterError]]:
    include = expand_names(options.include, adapters) if options.include is not None else None
    exclude = expand_names(options.exclude, adapters)

    ready: list[Adapter] = []
    skipped: list[AdapterError] = []
    for adapter in adapters:
        if adapter.name in exclude or (include is not None and adapter.name not in include):
            continue
        status = adapter.status()
        if status.state is SourceState.READY:
            ready.append(adapter)
        elif status.state is not SourceState.DISABLED:
            reason = status.detail or status.state.value
            skipped.append(AdapterError(source=adapter.name, kind=ErrorKind.SKIPPED, reason=reason))

    trace(
        logger,
        "lookup.selected",
        include=None if options.include is None else sorted(options.include),
        exclude=sorted(options.exclude),
        ready=[adapter.name for adapter in ready],
        skipped={error.source: error.reason for error in skipped},
        not_selected=sorted(
            adapter.name
            for adapter in adapters
            if adapter not in ready and adapter.name not in {e.source for e in skipped}
        ),
    )
    return ready, skipped


class _Run:
    def __init__(self, query: Query, options: LookupOptions, now: Callable[[], datetime]) -> None:
        self.query = query
        self.options = options
        self.now = now
        self.partials: list[Partial] = []
        self.slots = asyncio.Semaphore(options.concurrency) if options.concurrency else None

    def context(self) -> LookupContext:
        with trace_scope(stage="context"):
            dossier = merge(self.query, self.partials, generated_at=self.now())
        return LookupContext(query=self.query, identity=dossier.identity, links=dossier.links)

    async def run(self, adapters: Sequence[Adapter], pass_: str) -> None:
        if not adapters:
            return
        with trace_scope(**{"pass": pass_}):
            await self._run(adapters)

    async def _run(self, adapters: Sequence[Adapter]) -> None:
        context = self.context()
        identity = context.identity
        trace(
            logger,
            "pass.start",
            sources=[adapter.name for adapter in adapters],
            query=self.query.model_dump(mode="json"),
            identity={
                "kind": identity.kind,
                "artist": None if identity.artist is None else identity.artist.value,
                "title": None if identity.title is None else identity.title.value,
                "version": identity.version.model_dump(mode="json"),
                "external_ids": len(identity.external_ids),
            },
            links=len(context.links),
        )
        async with asyncio.TaskGroup() as group:
            tasks = [
                group.create_task(
                    _call(
                        adapter,
                        self.query,
                        context,
                        self.options.timeout_for(adapter.name),
                        self.slots,
                    ),
                )
                for adapter in adapters
            ]
        self.partials.extend(task.result() for task in tasks)

    def adopt_kind(self) -> None:
        """Give a URL query the kind found by its resolver, so later adapters know what to find."""
        if self.query.kind is not None:
            return
        candidate = self.partials[0].candidate
        if candidate is not None and candidate.kind is not None:
            self.query = self.query.model_copy(update={"kind": candidate.kind})
            trace(logger, "lookup.kind_adopted", kind=candidate.kind)


async def run(
    query: Query,
    adapters: Sequence[Adapter],
    options: LookupOptions | None = None,
    *,
    now: Callable[[], datetime] = _now,
) -> Dossier:
    """Look the query up with adapters pass by pass and merge their results into a dossier."""
    options = options or LookupOptions()
    ready, skipped = _select(adapters, options)
    lookup = _Run(query, options, now)

    resolver = None
    if query.url is not None:
        resolver = next((adapter for adapter in ready if adapter.resolves(query)), None)
        trace(logger, "lookup.resolver", source=None if resolver is None else resolver.name)
    if resolver is not None:
        await lookup.run([resolver], "resolve")
        lookup.adopt_kind()

    remaining = [adapter for adapter in ready if adapter is not resolver]
    for pass_ in Pass:
        await lookup.run([adapter for adapter in remaining if adapter.pass_ is pass_], pass_)
    with trace_scope(stage="final"):
        return merge(query, lookup.partials, skipped, generated_at=now())
