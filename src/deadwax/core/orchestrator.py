import asyncio
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from deadwax.core.adapter import Adapter, LookupContext, Pass, SourceState
from deadwax.core.errors import (
    BlockedError,
    ConfigurationError,
    NotFoundError,
    RateLimitedError,
    SourceError,
)
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


async def _call(adapter: Adapter, query: Query, context: LookupContext, seconds: float) -> Partial:
    """Run one adapter; every failure except cancellation becomes an error in its partial."""
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
        description="Adapters to run; all when unset",
    )
    exclude: frozenset[str] = Field(default=frozenset(), description="Adapters not to run")

    def timeout_for(self, source: str) -> float:
        """Return the timeout of one adapter."""
        return self.adapter_timeouts.get(source, self.adapter_timeout)


def _select(
    adapters: Sequence[Adapter],
    options: LookupOptions,
) -> tuple[list[Adapter], list[AdapterError]]:
    names = [adapter.name for adapter in adapters]
    unknown = sorted({*(options.include or ()), *options.exclude} - set(names))
    if unknown:
        raise ConfigurationError(
            f"unknown sources: {', '.join(unknown)}; known: {', '.join(names)}",
        )

    ready: list[Adapter] = []
    skipped: list[AdapterError] = []
    for adapter in adapters:
        if adapter.name in options.exclude or (
            options.include is not None and adapter.name not in options.include
        ):
            continue
        status = adapter.status()
        if status.state is SourceState.READY:
            ready.append(adapter)
        elif status.state is not SourceState.DISABLED:
            reason = status.detail or status.state.value
            skipped.append(AdapterError(source=adapter.name, kind=ErrorKind.SKIPPED, reason=reason))
    return ready, skipped


class _Run:
    def __init__(self, query: Query, options: LookupOptions, now: Callable[[], datetime]) -> None:
        self.query = query
        self.options = options
        self.now = now
        self.partials: list[Partial] = []

    def context(self) -> LookupContext:
        dossier = merge(self.query, self.partials, generated_at=self.now())
        return LookupContext(query=self.query, identity=dossier.identity, links=dossier.links)

    async def run(self, adapters: Sequence[Adapter]) -> None:
        if not adapters:
            return
        context = self.context()
        async with asyncio.TaskGroup() as group:
            tasks = [
                group.create_task(
                    _call(adapter, self.query, context, self.options.timeout_for(adapter.name)),
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
    if resolver is not None:
        await lookup.run([resolver])
        lookup.adopt_kind()

    remaining = [adapter for adapter in ready if adapter is not resolver]
    await lookup.run([adapter for adapter in remaining if adapter.pass_ is Pass.IDENTITY])
    await lookup.run([adapter for adapter in remaining if adapter.pass_ is Pass.ENRICH])
    await lookup.run([adapter for adapter in remaining if adapter.pass_ is Pass.LINKS])
    return merge(query, lookup.partials, skipped, generated_at=now())
