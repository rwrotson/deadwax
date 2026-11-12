import logging
from collections.abc import Mapping

import httpx

from deadwax.core import (
    AdapterError,
    BlockedError,
    Capability,
    ConfigurationError,
    EntityKind,
    ErrorKind,
    IdKind,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Query,
    RecordKey,
    Relation,
    Requirement,
    Scope,
    SourceError,
    SourceStatus,
    Text,
)
from deadwax.sources._base import HttpAdapter, search_key
from deadwax.sources._http import ClientSpec, HttpClient, HttpResources, Profile
from deadwax.sources.config import SourcesConfig
from deadwax.sources.discogs import models
from deadwax.sources.discogs import parse as p

logger = logging.getLogger(__name__)

API = "https://api.discogs.com/"
PAGE_SIZE = "25"

# Discogs allows 25 requests a minute without a token and 60 with one.
ANONYMOUS_RATE = 25 / 60

# httpx's own User-Agent: on 2026-11-12 Discogs refused every User-Agent naming deadwax.
DEFAULT_USER_AGENT = f"python-httpx/{httpx.__version__}"

SKIPPED_SEARCH = "search needs discogs.token, and earlier sources found no Discogs ID"


class DiscogsAdapter(HttpAdapter):
    """Genres, styles, credits, notes, versions, labels, members, and reviews from Discogs."""

    name = "discogs"
    pass_ = Pass.ENRICH
    capabilities = frozenset(
        {
            Capability.IDENTITY,
            Capability.LINKS,
            Capability.TAGS,
            Capability.CREDITS,
            Capability.TEXTS,
            Capability.RELATIONS,
        }
    )
    requires = (Requirement(setting="discogs.token", purpose="search and compilations"),)
    default_user_agent = DEFAULT_USER_AGENT

    def __init__(self, config: SourcesConfig, resources: HttpResources) -> None:
        super().__init__(config, resources)
        self._page_client: HttpClient | None = None

    @property
    def token(self) -> str | None:
        """Personal access token, if configured."""
        token = self.config.discogs.token
        return token.get_secret_value() if token is not None else None

    def status(self) -> SourceStatus:
        """Ready without a token too, as lookups by ID work; the detail notes what is missing."""
        status = super().status()
        if status.ready and self.token is None:
            return status.model_copy(update={"detail": "no discogs.token: no search"})
        return status

    def headers(self) -> Mapping[str, str]:
        """Authorize with the token when one is set; it is sent as a header, never cached."""
        return {"authorization": f"Discogs token={self.token}"} if self.token else {}

    def resolves(self, query: Query) -> bool:
        """Discogs master and release pages."""
        return IdKind.DISCOGS_MASTER in query.ids or IdKind.DISCOGS_RELEASE in query.ids

    @property
    def client(self) -> HttpClient:
        """API client; slower without a token, as Discogs allows fewer anonymous requests."""
        if self._client is None:
            config = self.config
            if self.token is None and config.discogs.rate is None:
                settings = config.discogs.model_copy(update={"rate": ANONYMOUS_RATE})
                config = config.model_copy(update={"discogs": settings})
            self._client = HttpClient(self.client_spec(Profile.API), config, self.resources)
        return self._client

    @property
    def page_client(self) -> HttpClient:
        """Client for release pages, with browser headers and the escalation ladder."""
        if self._page_client is None:
            user_agent = self.settings.user_agent
            headers = {"user-agent": user_agent} if user_agent else {}
            spec = ClientSpec(self.name, Profile.BROWSER, headers)
            self._page_client = HttpClient(spec, self.config, self.resources)
        return self._page_client

    async def aclose(self) -> None:
        """Close both clients."""
        await super().aclose()
        if self._page_client is not None:
            await self._page_client.aclose()
            self._page_client = None

    async def _get[M: models.ApiModel](self, model: type[M], path: str, **params: str) -> M:
        response = await self.client.get(f"{API}{path}", params=params or None)
        return model.model_validate_json(response.content)

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Read the master and its main release, then versions, artist, label, and reviews."""
        key = search_key(query, context)
        kind = query.kind or (key.kind if key is not None else None) or EntityKind.ALBUM
        target = await self._target(query, context, key)
        if target is None:
            error = AdapterError(source=self.name, kind=ErrorKind.SKIPPED, reason=SKIPPED_SEARCH)
            return Partial(source=self.name, errors=[error])
        master_id, release_id = target
        master = await self._get(models.Master, f"masters/{master_id}") if master_id else None
        if release_id is None and master is not None and master.main_release is not None:
            release_id = str(master.main_release)
        if release_id is None:
            raise NotFoundError("the Discogs master names no main release")
        release = await self._get(models.Release, f"releases/{release_id}")
        if master is None and release.master_id:
            master = await self._get(models.Master, f"masters/{release.master_id}")
        return await self._partial(release, master, kind, key)

    async def _target(
        self, query: Query, context: LookupContext, key: RecordKey | None
    ) -> tuple[str | None, str | None] | None:
        """Return master and release IDs from the query, earlier passes, or a search.

        None means a search was needed but no token is set.
        """
        release_id = context.id(IdKind.DISCOGS_RELEASE)
        # A release URL names one version; its master is read only for the group's facts.
        master_id = (
            None if IdKind.DISCOGS_RELEASE in query.ids else context.id(IdKind.DISCOGS_MASTER)
        )
        if master_id is not None or release_id is not None:
            return master_id, release_id
        if key is None:
            raise NotFoundError("neither the query nor earlier sources name the record")
        if self.token is None:
            return None
        found = await self._search(key)
        if found is None:
            raise NotFoundError("no matching Discogs release")
        return found

    async def _search(self, key: RecordKey) -> tuple[str | None, str | None] | None:
        """Find a master, or for a track a release containing it; needs the token."""
        params = {"artist": key.artist, "per_page": PAGE_SIZE}
        if key.kind is EntityKind.TRACK:
            params |= {"track": key.title, "type": "release"}
        else:
            params |= {"release_title": key.title, "type": "master"}
        found = p.pick_result(
            key, (await self._get(models.Search, "database/search", **params)).results
        )
        if found is None:
            return None
        if found.type == "master":
            return str(found.id), None
        return (str(found.master_id) if found.master_id else None), str(found.id)

    async def _partial(
        self,
        release: models.Release,
        master: models.Master | None,
        kind: EntityKind,
        key: RecordKey | None,
    ) -> Partial:
        release_url = p.page("release", release.id)
        group_url = p.page("master", master.id) if master is not None else release_url
        group_scope = Scope.RELEASE_GROUP if master is not None else Scope.RELEASE
        texts = p.notes(release.notes, "Release notes", Scope.RELEASE, release_url)
        if master is not None:
            texts = p.notes(master.notes, "Master notes", Scope.RELEASE_GROUP, group_url) + texts
        tags = p.tags(
            master.genres if master is not None else release.genres,
            master.styles if master is not None else release.styles,
            group_scope,
            group_url,
        )
        relations = p.label_relations(release)
        if kind is EntityKind.TRACK:
            track = p.find_track(release, key) if key is not None else None
            if track is None:
                raise NotFoundError("the track is not on the Discogs release", url=release_url)
            candidate = p.track_candidate(release, master, track)
            people = p.release_credits(release, track)
            relations += await self._compilations(track, release, master)
            relations.append(p.appears_on(release, master))
        else:
            candidate = p.album_candidate(release, master)
            people = p.release_credits(release)
        relations += await self._versions(master, release)
        relations += await self._artist(release)
        relations += await self._label_releases(release, candidate.title)
        reviews, errors = await self._reviews(release)
        return Partial(
            source=self.name,
            candidate=candidate,
            tags=tags,
            credits=people,
            texts=texts + reviews,
            relations=relations,
            links=p.links(release, master),
            errors=errors,
        )

    async def _versions(
        self, master: models.Master | None, release: models.Release
    ) -> list[Relation]:
        if master is None:
            return []
        versions = await self._get(
            models.Versions, f"masters/{master.id}/versions", per_page=PAGE_SIZE
        )
        return p.version_relations(versions.versions, release.id)

    async def _artist(self, release: models.Release) -> list[Relation]:
        artist_id = next((a.id for a in release.artists if a.id is not None), None)
        if artist_id is None:
            return []
        return p.artist_relations(await self._get(models.Artist, f"artists/{artist_id}"))

    async def _label_releases(self, release: models.Release, title: str) -> list[Relation]:
        label = next((label for label in p.real_labels(release) if label.id is not None), None)
        if label is None or label.id is None:
            return []
        found = await self._get(
            models.LabelReleases, f"labels/{label.id}/releases", per_page=PAGE_SIZE
        )
        return p.label_release_relations(found.releases, p.clean_name(label.name), label.id, title)

    async def _compilations(
        self, track: models.Track, release: models.Release, master: models.Master | None
    ) -> list[Relation]:
        """Search compilations with the track; the search needs the token."""
        if self.token is None:
            return []
        artist = p.credit_name(track.artists or release.artists)
        found = await self._get(
            models.Search,
            "database/search",
            artist=artist,
            track=track.title,
            format="Compilation",
            type="release",
            per_page=PAGE_SIZE,
        )
        exclude = {release.id, *([master.id] if master is not None else [])}
        return p.compilation_relations(found.results, exclude)

    async def _reviews(self, release: models.Release) -> tuple[list[Text], list[AdapterError]]:
        """Read reviews from the release page; a refused page costs only the reviews."""
        url = p.page("release", release.id)
        try:
            response = await self.page_client.get(url)
        except BlockedError as error:
            reason = f"reviews: {error}"
            return [], [
                AdapterError(source=self.name, kind=ErrorKind.BLOCKED, reason=reason, url=url)
            ]
        except NotFoundError:
            return [], []
        # A missing escalation browser raises ConfigurationError; it costs only the reviews.
        except (SourceError, ConfigurationError) as error:
            reason = f"reviews: {error}"
            return [], [
                AdapterError(source=self.name, kind=ErrorKind.FAILED, reason=reason, url=url)
            ]
        return p.reviews(response.content, response.url), []
