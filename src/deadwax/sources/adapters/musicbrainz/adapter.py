import logging
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from deadwax.core import (
    AdapterError,
    ArtistQuery,
    Capability,
    CatalogExpansion,
    EntityKind,
    EntityType,
    ErrorKind,
    IdKind,
    LabelQuery,
    LinkTarget,
    LookupContext,
    Lookups,
    NameKey,
    NotFoundError,
    Partial,
    Pass,
    Query,
    RecordCandidate,
    RecordKey,
    Relation,
    ReleaseTrack,
    Scope,
    SourceError,
    SourceGroup,
    TraceEvent,
    TrackQuery,
    VersionInfo,
    VersionKind,
    WorkPerformance,
    parse_title,
    trace,
)
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._search import TRACED_HITS, name_key, search_key
from deadwax.sources.adapters.musicbrainz import models
from deadwax.sources.adapters.musicbrainz import parse as p

API = "https://musicbrainz.org/ws/2/"
_RECORDING_INC = (
    "artist-credits+isrcs+releases+release-groups+tags+genres"
    "+artist-rels+recording-rels+work-rels+url-rels"
)
_GROUP_INC = "artist-credits+releases+tags+genres+url-rels+artist-rels"
_RELEASE_INC = "labels+release-groups+url-rels+artist-rels"
_ALBUM_RELEASE_INC = f"{_RELEASE_INC}+recordings+recording-level-rels"
_WORK_INC = "recording-rels+url-rels+artist-rels+artist-credits"
_URL_INC = "recording-rels+release-rels+release-group-rels"
_ARTIST_INC = "aliases+tags+genres+url-rels+artist-rels+label-rels"
_LABEL_INC = "aliases+tags+genres+url-rels+label-rels+artist-rels"
_NAME_URL_INC = "artist-rels+label-rels"
_NAME_SEARCH_LIMIT = "25"
_BROWSE_LIMIT = "100"
_SEARCH_LIMIT = "100"
_COVER_CANDIDATES = 3
_MAIN_RELEASES = "status:official AND primarytype:(album OR single OR ep)"

# Identifiers that name a MusicBrainz entity, or a URL only MusicBrainz maps without a key.
_RESOLVED_IDS = (
    IdKind.MUSICBRAINZ_RECORDING,
    IdKind.MUSICBRAINZ_RELEASE,
    IdKind.MUSICBRAINZ_RELEASE_GROUP,
    IdKind.MUSICBRAINZ_ARTIST,
    IdKind.MUSICBRAINZ_LABEL,
    IdKind.SPOTIFY,
)

# Identifier kind of each name kind's MusicBrainz entity.
_NAME_IDS = {
    EntityKind.ARTIST: IdKind.MUSICBRAINZ_ARTIST,
    EntityKind.LABEL: IdKind.MUSICBRAINZ_LABEL,
}

type Target = tuple[EntityKind, str]

logger = logging.getLogger(__name__)


def _trace_ranked(
    query: str,
    results: int,
    ranked: Sequence[models.Recording | models.ReleaseGroup],
) -> None:
    """Record how a search was narrowed to the entities that match the reference."""
    trace(
        logger,
        TraceEvent.SEARCH_RANKED,
        query=query,
        results=results,
        matched=[{"id": entity.id, "title": entity.title} for entity in ranked[:TRACED_HITS]],
        picked=ranked[0].id if ranked else None,
    )


@dataclass(frozen=True, slots=True)
class _TrackSources:
    recording: models.Recording
    release: models.Release | None
    group: models.ReleaseGroup | None
    work: models.Work | None
    errors: list[AdapterError]
    artist_relations: list[Relation]


class MusicBrainzAdapter(HttpAdapter):
    """Identity, credits, tags, relations and links from the MusicBrainz web service."""

    name = "musicbrainz"
    pass_ = Pass.IDENTITY
    group = SourceGroup.CORE
    service = "musicbrainz"
    capabilities = frozenset(
        {
            Capability.IDENTITY,
            Capability.LINKS,
            Capability.TAGS,
            Capability.CREDITS,
            Capability.RELATIONS,
        },
    )

    def resolves(self, query: Query) -> bool:
        """MusicBrainz pages, and Spotify URLs, which only MusicBrainz maps without a key."""
        return any(kind in query.ids for kind in _RESOLVED_IDS)

    async def _get[M: models.ApiModel](self, model: type[M], path: str, **params: str) -> M:
        response = await self.client.get(f"{API}{path}", params={**params, "fmt": "json"})
        return model.model_validate_json(response.content)

    @property
    def lookups(self) -> Lookups:
        """Recordings, release groups, artists, and labels; an identifier or URL tells which."""
        return Lookups(
            track=self.find,
            album=self.find,
            artist=self.find_artist,
            label=self.find_label,
            unresolved=self.find,
        )

    async def release_tracklist(
        self, release_id: str, limit: int
    ) -> CatalogExpansion[ReleaseTrack]:
        """Read the tracklist of the requested release edition."""
        release = await self._get(
            models.Release,
            f"release/{release_id}",
            inc="recordings+artist-credits+isrcs",
        )
        return p.release_tracklist(release, limit)

    async def work_performances(
        self, work_id: str, limit: int
    ) -> CatalogExpansion[WorkPerformance]:
        """Read the recording relationships of the requested work."""
        work = await self._get(models.Work, f"work/{work_id}", inc="recording-rels+artist-credits")
        return p.work_performances(work, limit)

    async def find_artist(self, query: ArtistQuery, context: LookupContext) -> Partial:
        """Find the artist and collect their tags, aliases, relations, releases, and links."""
        mbid = await self._name_target(query, context)
        artist = await self._get(models.Artist, f"artist/{mbid}", inc=_ARTIST_INC)
        url = p.page("artist", artist.id)
        relations = [
            *p.artist_relations(artist),
            *p.artist_labels(artist),
            *p.aliases(artist, EntityType.ARTIST, Scope.ARTIST, url),
        ]
        if context.wants(Capability.RELATIONS):
            groups = await self._get(
                models.ReleaseGroupBrowse,
                "release-group",
                artist=artist.id,
                type="album|ep",
                limit=_BROWSE_LIMIT,
                **{"release-group-status": "website-default"},
            )
            relations += p.releases(groups.release_groups, artist)
        return Partial(
            source=self.name,
            candidate=p.artist_candidate(artist),
            tags=p.tags(artist.tags, artist.genres, Scope.ARTIST, url),
            relations=relations,
            links=p.links(artist.relations, LinkTarget.ARTIST, url),
        )

    async def find_label(self, query: LabelQuery, context: LookupContext) -> Partial:
        """Find the label and collect its tags, aliases, owners, imprints, artists, and links."""
        mbid = await self._name_target(query, context)
        label = await self._get(models.Label, f"label/{mbid}", inc=_LABEL_INC)
        url = p.page("label", label.id)
        return Partial(
            source=self.name,
            candidate=p.label_candidate(label),
            tags=p.tags(label.tags, label.genres, Scope.LABEL, url),
            relations=[
                *p.label_hierarchy(label),
                *p.label_artists(label),
                *p.aliases(label, EntityType.LABEL, Scope.LABEL, url),
            ],
            links=p.links(label.relations, LinkTarget.LABEL, url),
        )

    async def _name_target(self, query: ArtistQuery | LabelQuery, context: LookupContext) -> str:
        """Return the MBID from the query or earlier passes, the query URL, or a name search."""
        if (mbid := context.id(_NAME_IDS[query.kind])) is not None:
            return mbid
        if query.url is not None and (mbid := await self._name_by_url(query)) is not None:
            return mbid
        key = name_key(query, context)
        if key is None:
            raise NotFoundError("neither the query nor earlier sources name the record")
        mbid = await self._search_name(key)
        if mbid is None:
            raise NotFoundError(f"no matching {query.kind} in MusicBrainz")
        return mbid

    async def _name_by_url(self, query: ArtistQuery | LabelQuery) -> str | None:
        try:
            entity = await self._get(
                models.UrlEntity,
                "url",
                resource=query.url or "",
                inc=_NAME_URL_INC,
            )
        except NotFoundError:
            return None
        for relation in entity.relations:
            if query.kind is EntityKind.ARTIST and relation.artist is not None:
                return relation.artist.id
            if query.kind is EntityKind.LABEL and relation.label is not None:
                return relation.label.id
        return None

    async def _search_name(self, key: NameKey) -> str | None:
        entity = "artist" if key.kind is EntityKind.ARTIST else "label"
        query = f"{entity}:{p.phrase(key.name)}"
        found: Sequence[models.Artist | models.Label]
        if key.kind is EntityKind.ARTIST:
            search = await self._get(
                models.ArtistSearch,
                entity,
                query=query,
                limit=_NAME_SEARCH_LIMIT,
            )
            found = search.artists
        else:
            labels = await self._get(
                models.LabelSearch,
                entity,
                query=query,
                limit=_NAME_SEARCH_LIMIT,
            )
            found = labels.labels
        ranked = p.rank_names(key, found, _NAME_IDS[key.kind])
        trace(
            logger,
            TraceEvent.SEARCH_RANKED,
            query=query,
            results=len(found),
            matched=[{"id": entity.id, "name": entity.name} for entity in ranked[:TRACED_HITS]],
            picked=ranked[0].id if ranked else None,
        )
        return ranked[0].id if ranked else None

    async def find(self, query: Query, context: LookupContext) -> Partial:
        """Find the recording or release group and collect what MusicBrainz knows about it."""
        cover = (
            isinstance(query, TrackQuery)
            and query.title is not None
            and parse_title(query.title).version.kind is VersionKind.COVER
        )
        target = await self._find_by_ids(query)
        if target is None:
            target = await self._find_by_text(query, context)
        if target is None:
            reference = search_key(query, context)
            if cover and reference is not None:
                recording = await self._search_cover(reference)
                if recording is not None:
                    return self._track_partial(
                        await self._track_sources(recording, context), cover=True
                    )
            raise NotFoundError("no matching record in MusicBrainz")

        kind, mbid = target
        if kind is EntityKind.TRACK:
            recording = await self._get(models.Recording, f"recording/{mbid}", inc=_RECORDING_INC)
            return self._track_partial(await self._track_sources(recording, context), cover=cover)
        return await self._album(mbid, context)

    async def _find_by_ids(self, query: Query) -> Target | None:
        if recording := query.ids.get(IdKind.MUSICBRAINZ_RECORDING):
            return EntityKind.TRACK, recording
        if group := query.ids.get(IdKind.MUSICBRAINZ_RELEASE_GROUP):
            return EntityKind.ALBUM, group
        if release := query.ids.get(IdKind.MUSICBRAINZ_RELEASE):
            return await self._group_of(release)
        if query.url is not None:
            return await self._by_url(query.url)
        return None

    async def _find_by_text(self, query: Query, context: LookupContext) -> Target | None:
        reference = search_key(query, context)
        if reference is None:
            return None
        if reference.kind is EntityKind.ALBUM:
            return await self._search_album(reference)
        for isrc in context.isrcs():
            if (found := await self._by_isrc(isrc, reference)) is not None:
                return found
        return await self._search_track(reference)

    async def _group_of(self, release_id: str) -> Target | None:
        release = await self._get(models.Release, f"release/{release_id}", inc="release-groups")
        if release.release_group is None:
            return None
        return EntityKind.ALBUM, release.release_group.id

    async def _by_url(self, url: str) -> Target | None:
        try:
            entity = await self._get(models.UrlEntity, "url", resource=url, inc=_URL_INC)
        except NotFoundError:
            return None
        for relation in entity.relations:
            if relation.recording is not None:
                return EntityKind.TRACK, relation.recording.id
            if relation.release_group is not None:
                return EntityKind.ALBUM, relation.release_group.id
        release = next((r.release for r in entity.relations if r.release is not None), None)
        return await self._group_of(release.id) if release is not None else None

    async def _by_isrc(self, isrc: str, reference: RecordKey) -> Target | None:
        try:
            found = await self._get(
                models.RecordingSearch,
                f"isrc/{isrc}",
                inc="artist-credits+releases",
            )
        except NotFoundError:
            return None
        ranked = p.rank_recordings(reference, found.recordings)
        _trace_ranked(f"isrc:{isrc}", len(found.recordings), ranked)
        return (EntityKind.TRACK, ranked[0].id) if ranked else None

    async def _search_recordings(self, query: str) -> models.RecordingSearch:
        return await self._get(
            models.RecordingSearch,
            "recording",
            query=query,
            limit=_SEARCH_LIMIT,
        )

    async def _search_track(self, reference: RecordKey) -> Target | None:
        artist = p.phrase(reference.artist)
        titles = dict.fromkeys([reference.title, parse_title(reference.title).base])
        for title in titles:
            # Official album, EP and single releases first: a plain search returns hundreds of
            # live and bootleg recordings with the same score before the original.
            plain = f"recording:{p.phrase(title)} AND artist:{artist}"
            for query in (f"{plain} AND {_MAIN_RELEASES}", plain):
                found = await self._search_recordings(query)
                ranked = p.rank_recordings(reference, found.recordings)
                _trace_ranked(query, len(found.recordings), ranked)
                if ranked:
                    return EntityKind.TRACK, ranked[0].id
        return None

    async def _search_cover(self, reference: RecordKey) -> models.Recording | None:
        base = RecordKey(reference.artist, parse_title(reference.title).base, reference.kind)
        query = f"recording:{p.phrase(base.title)} AND artist:{p.phrase(base.artist)}"
        found = await self._search_recordings(query)
        for match in p.rank_recordings(base, found.recordings)[:_COVER_CANDIDATES]:
            try:
                recording = await self._get(
                    models.Recording,
                    f"recording/{match.id}",
                    inc=_RECORDING_INC,
                )
            except NotFoundError:
                continue
            if p.rank_recordings(base, [recording]) and p.cover_relations(recording):
                return recording
        return None

    async def _search_album(self, reference: RecordKey) -> Target | None:
        title, artist = p.phrase(reference.title), p.phrase(reference.artist)
        query = f"releasegroup:{title} AND artist:{artist}"
        found = await self._get(
            models.ReleaseGroupSearch,
            "release-group",
            query=query,
            limit=_SEARCH_LIMIT,
        )
        ranked = p.rank_release_groups(reference, found.release_groups)
        _trace_ranked(query, len(found.release_groups), ranked)
        return (EntityKind.ALBUM, ranked[0].id) if ranked else None

    async def _artist_relations(
        self,
        artist_credit: list[models.ArtistCredit],
        context: LookupContext,
    ) -> list[Relation]:
        if not artist_credit or not context.wants(Capability.RELATIONS):
            return []
        artist = await self._get(
            models.Artist,
            f"artist/{artist_credit[0].artist.id}",
            inc="artist-rels",
        )
        return p.artist_relations(artist)

    async def _track_sources(
        self,
        recording: models.Recording,
        context: LookupContext,
    ) -> _TrackSources:
        main = p.first_release(recording.releases)
        release = group = work = None
        if main is not None:
            release = await self._get(models.Release, f"release/{main.id}", inc=_RELEASE_INC)
            if main.release_group is not None:
                group_path = f"release-group/{main.release_group.id}"
                group = await self._get(models.ReleaseGroup, group_path, inc=_GROUP_INC)

        performance = next(
            (r for r in recording.relations if r.type == "performance" and r.work is not None),
            None,
        )
        errors: list[AdapterError] = []
        if performance is not None and performance.work is not None:
            path = f"work/{performance.work.id}"
            try:
                work = await self._get(models.Work, path, inc=_WORK_INC)
            except (SourceError, ValidationError) as error:
                if not p.cover_relations(recording):
                    raise
                errors.append(
                    AdapterError(
                        source=self.name,
                        kind=ErrorKind.FAILED,
                        reason=str(error),
                        url=p.page("work", performance.work.id),
                    ),
                )

        return _TrackSources(
            recording=recording,
            release=release,
            group=group,
            work=work,
            errors=errors,
            artist_relations=await self._artist_relations(recording.artist_credit, context),
        )

    def _track_partial(self, found: _TrackSources, *, cover: bool) -> Partial:
        recording, release, group, work = found.recording, found.release, found.group, found.work
        url = p.page("recording", recording.id)
        people = p.artist_credits(recording.relations, Scope.RECORDING, url)
        tags = p.tags(recording.tags, recording.genres, Scope.RECORDING, url)
        links = p.links(recording.relations, LinkTarget.TRACK, url)
        review_links = p.review_links(recording.relations, url)

        covers = p.cover_relations(recording)
        relations = [
            *covers,
            *p.recording_relations(recording.relations, Scope.RECORDING, url),
            *p.appearances(recording.releases, None, url),
            *found.artist_relations,
        ]

        if release is not None:
            relations += p.label_relations(release)
        if work is not None:
            people += p.artist_credits(work.relations, Scope.WORK, p.page("work", work.id))
            version = p.recording_version(recording.title, recording.disambiguation)
            if not covers:
                relations += p.work_relations(work, recording.id, version, is_cover=False)
        if group is not None:
            group_url = p.page("release-group", group.id)
            tags += p.tags(group.tags, group.genres, Scope.RELEASE_GROUP, group_url)
            links += p.links(group.relations, LinkTarget.ALBUM, group_url)
            review_links += p.review_links(group.relations, group_url)

        return Partial(
            source=self.name,
            candidate=_track_candidate(found, cover=cover and bool(covers)),
            errors=found.errors,
            tags=tags,
            credits=people,
            relations=relations,
            links=links,
            review_links=review_links,
        )

    async def _album(self, group_id: str, context: LookupContext) -> Partial:
        group = await self._get(models.ReleaseGroup, f"release-group/{group_id}", inc=_GROUP_INC)
        url = p.page("release-group", group_id)
        main = p.first_release(group.releases)
        release = None
        if main is not None:
            release = await self._get(models.Release, f"release/{main.id}", inc=_ALBUM_RELEASE_INC)

        people = p.artist_credits(group.relations, Scope.RELEASE_GROUP, url)
        relations = await self._artist_relations(group.artist_credit, context)
        links = p.links(group.relations, LinkTarget.ALBUM, url)
        review_links = p.review_links(group.relations, url)
        if release is not None:
            release_url = p.page("release", release.id)
            people += p.artist_credits(release.relations, Scope.RELEASE, release_url)
            people += p.track_credits(release)
            relations += p.label_relations(release)
            links += p.links(release.relations, LinkTarget.ALBUM, release_url)
            review_links += p.review_links(release.relations, release_url)

        return Partial(
            source=self.name,
            candidate=_album_candidate(group, release),
            tags=p.tags(group.tags, group.genres, Scope.RELEASE_GROUP, url),
            credits=people,
            relations=relations,
            links=links,
            review_links=review_links,
        )


def _track_candidate(found: _TrackSources, *, cover: bool) -> RecordCandidate:
    """Describe a recording; release IDs are its first release's, the Wikidata ID the song's."""
    recording = found.recording
    ids: dict[IdKind, str] = {IdKind.MUSICBRAINZ_RECORDING: recording.id}
    if recording.artist_credit:
        ids[IdKind.MUSICBRAINZ_ARTIST] = recording.artist_credit[0].artist.id
    if found.release is not None:
        ids[IdKind.MUSICBRAINZ_RELEASE] = found.release.id
    if found.group is not None:
        ids[IdKind.MUSICBRAINZ_RELEASE_GROUP] = found.group.id
        album_ids = p.url_ids(found.group.relations)
        ids.update({k: v for k, v in album_ids.items() if k is not IdKind.WIKIDATA})
    if found.work is not None:
        ids[IdKind.MUSICBRAINZ_WORK] = found.work.id
        ids.update(p.url_ids(found.work.relations))

    version = p.recording_version(recording.title, recording.disambiguation)
    if cover and version.kind is VersionKind.ORIGINAL:
        version = VersionInfo(kind=VersionKind.COVER)
    return RecordCandidate(
        kind=EntityKind.TRACK,
        artist=p.credit_name(recording.artist_credit),
        title=recording.title,
        version=version,
        date=recording.first_release_date,
        labels=p.labels(found.release) if found.release is not None else [],
        isrcs=recording.isrcs,
        ids=ids,
        url=p.page("recording", recording.id),
    )


def _album_candidate(group: models.ReleaseGroup, release: models.Release | None) -> RecordCandidate:
    """Describe a release group with the labels and barcode of its first release."""
    ids: dict[IdKind, str] = {
        IdKind.MUSICBRAINZ_RELEASE_GROUP: group.id,
        **p.url_ids(group.relations),
    }
    if group.artist_credit:
        ids[IdKind.MUSICBRAINZ_ARTIST] = group.artist_credit[0].artist.id
    if release is not None:
        ids[IdKind.MUSICBRAINZ_RELEASE] = release.id

    return RecordCandidate(
        kind=EntityKind.ALBUM,
        artist=p.credit_name(group.artist_credit),
        title=group.title,
        date=group.first_release_date,
        labels=p.labels(release) if release is not None else [],
        upcs=[release.barcode] if release is not None and release.barcode else [],
        ids=ids,
        url=p.page("release-group", group.id),
    )
