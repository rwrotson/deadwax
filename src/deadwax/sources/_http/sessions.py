import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from deadwax.core import ConfigurationError, pause_adapter_timeout
from deadwax.sources._http.messages import Fetcher
from deadwax.sources.config import Escalation, HttpSettings

type FetcherFactory = Callable[[HttpSettings, str | None], Fetcher]

# Transports that launch a browser shared by the adapters of a client's lookups.
BROWSER_STEPS = frozenset({Escalation.BROWSER, Escalation.NODRIVER})


@dataclass(frozen=True, slots=True)
class BrowserLease:
    """A shared browser lent for one request, and whether it shows a window."""

    fetcher: Fetcher
    headed: bool


@dataclass(slots=True)
class _Session:
    """One browser and the requests currently using it."""

    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    fetcher: Fetcher | None = None
    headed: bool = False
    users: int = 0
    changing: bool = False
    broken: bool = False

    async def acquire(
        self,
        factory: FetcherFactory,
        settings: HttpSettings,
        proxy: str | None,
        *,
        headed: bool,
    ) -> Fetcher:
        async with self.condition:
            await self.condition.wait_for(lambda: not self.changing)
            if self.fetcher is not None and (self.headed or not headed):
                self.users += 1
                return self.fetcher
            self.changing = True
            await self.condition.wait_for(lambda: self.users == 0)
        try:
            await self.close()
            fetcher = factory(settings.model_copy(update={"browser_headless": not headed}), proxy)
        except BaseException:
            async with self.condition:
                self.changing = False
                self.condition.notify_all()
            raise
        async with self.condition:
            self.fetcher, self.headed, self.users = fetcher, headed, 1
            self.changing = False
            self.condition.notify_all()
        return fetcher

    async def release(self) -> None:
        async with self.condition:
            self.users -= 1
            if self.users == 0 and self.broken:
                self.broken = False
                await self.close()
            self.condition.notify_all()

    async def close(self) -> None:
        fetcher, self.fetcher = self.fetcher, None
        if fetcher is not None:
            await fetcher.aclose()


class BrowserSessions:
    """Browsers shared by the HTTP clients of one `Deadwax` client, across its lookups.

    A session opens headless or headed as first requested. A headed request upgrades a
    headless session once its pages finish; a headed session also serves headless requests.
    """

    def __init__(self) -> None:
        self._sessions: dict[tuple[Escalation, str | None, str], _Session] = {}

    @asynccontextmanager
    async def use(
        self,
        step: Escalation,
        factory: FetcherFactory,
        settings: HttpSettings,
        proxy: str | None,
        *,
        headed: bool,
    ) -> AsyncIterator[BrowserLease]:
        """Lend the browser of a transport, launch options, and proxy for one request."""
        key = (step, proxy, settings.model_dump_json(exclude={"browser_headless"}))
        session = self._sessions.setdefault(key, _Session())
        async with pause_adapter_timeout():
            fetcher = await session.acquire(factory, settings, proxy, headed=headed)
        try:
            yield BrowserLease(fetcher, headed=session.headed)
        except ConfigurationError:
            session.broken = True
            raise
        finally:
            await session.release()

    async def aclose(self) -> None:
        """Close every browser."""
        sessions, self._sessions = list(self._sessions.values()), {}
        for session in sessions:
            await session.close()
