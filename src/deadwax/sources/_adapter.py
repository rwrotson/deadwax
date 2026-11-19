from abc import ABC, abstractmethod
from collections.abc import Mapping

from deadwax.core import (
    Capability,
    LookupContext,
    Partial,
    Pass,
    Query,
    Requirement,
    SourceAccess,
    SourceGroup,
    SourceState,
    SourceStatus,
)
from deadwax.sources._http import ClientSpec, HttpClient, HttpResources, Profile
from deadwax.sources.config import SourcesConfig, SourceSettings


class HttpAdapter(ABC):
    """Base for adapters that talk to one source through an `HttpClient`."""

    name: str
    group: SourceGroup
    pass_: Pass
    capabilities: frozenset[Capability]
    requires: tuple[Requirement, ...] = ()
    profile: Profile = Profile.API
    additional_profiles: tuple[Profile, ...] = ()
    # User-Agent replacing the profile's one unless the source's settings name another.
    default_user_agent: str | None = None
    secret_params: frozenset[str] = frozenset()
    required_marker: bytes | None = None

    def __init__(self, config: SourcesConfig, resources: HttpResources) -> None:
        self.config = config
        self.resources = resources
        self._client: HttpClient | None = None

    @property
    def settings(self) -> SourceSettings:
        """Settings of this source."""
        settings: SourceSettings = getattr(self.config, self.name)
        return settings

    @property
    def _reads_html(self) -> bool:
        return Profile.BROWSER in (self.profile, *self.additional_profiles)

    def access(self) -> SourceAccess:
        """Describe the configured routes to this source in their attempt order."""
        html = self._reads_html
        return SourceAccess(
            api=Profile.API in (self.profile, *self.additional_profiles),
            html_transports=(
                [
                    "patchright" if step.value == "browser" else step.value
                    for step in self.config.html_transports(self.name)
                ]
                if html
                else []
            ),
            browser_headless=self.config.browser_headless(self.name) if html else None,
            headed_fallback=html and self.config.http.headed_fallback,
        )

    def missing_credential(self) -> str | None:
        """Describe a missing credential the adapter cannot run without, if any."""
        return None

    def status(self) -> SourceStatus:
        """Report whether the adapter is enabled and has what it needs."""
        if not self.settings.enabled:
            return SourceStatus(source=self.name, state=SourceState.DISABLED)
        if self._reads_html and not self.config.html_transports(self.name):
            return SourceStatus(
                source=self.name,
                state=SourceState.DISABLED,
                detail="no permitted HTML transports",
            )
        missing = self.missing_credential()
        if missing is not None:
            return SourceStatus(
                source=self.name,
                state=SourceState.MISSING_CREDENTIAL,
                detail=missing,
            )
        return SourceStatus(source=self.name, state=SourceState.READY)

    def resolves(self, query: Query) -> bool:  # noqa: ARG002 -- the protocol's signature
        """Whether this adapter reads the page behind the query URL; none by default."""
        return False

    def headers(self) -> Mapping[str, str]:
        """Extra headers for every request, such as authorization."""
        return {}

    def user_agent(self) -> str | None:
        """User-Agent replacing the profile's one, if any."""
        return self.settings.user_agent or self.default_user_agent

    def client_spec(self, profile: Profile) -> ClientSpec:
        """Describe a client of this adapter with the given profile."""
        headers = dict(self.headers())
        if (user_agent := self.user_agent()) is not None:
            headers["user-agent"] = user_agent
        return ClientSpec(self.name, profile, headers, self.secret_params, self.required_marker)

    @property
    def client(self) -> HttpClient:
        """HTTP client of this adapter, created on first use."""
        if self._client is None:
            self._client = HttpClient(self.client_spec(self.profile), self.config, self.resources)
        return self._client

    @abstractmethod
    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Find the record and return what the source knows about it."""

    async def aclose(self) -> None:
        """Close the HTTP client if it was opened."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
