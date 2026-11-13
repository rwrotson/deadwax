from dataclasses import dataclass

from deadwax.core import (
    Capability,
    EntityKind,
    IdKind,
    LinkTarget,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Query,
    RecordCandidate,
    RecordKey,
    Relation,
    Scope,
    SourceGroup,
    parse_title,
)
from deadwax.sources._base import HttpAdapter, search_key
from deadwax.sources.musicbrainz import models
from deadwax.sources.musicbrainz import parse as p

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
_SEARCH_LIMIT = "100"
_MAIN_RELEASES = "status:official AND primarytype:(album OR single OR ep)"

# Identifiers that name a MusicBrainz entity, or a URL only MusicBrainz maps without a key.
_RESOLVED_IDS = (
    IdKind.MUSICBRAINZ_RECORDING,
    IdKind.MUSICBRAINZ_RELEASE,
    IdKind.MUSICBRAINZ_RELEASE_GROUP,
    IdKind.SPOTIFY,
)

type Target = tuple[EntityKind, str]


@dataclass(frozen=True, slots=True)
class _TrackSources:
    recording: models.Recording
    release: models.Release | None
    group: models.ReleaseGroup | None
    work: models.Work | None
    is_cover: bool
    members: list[Relation]


class MusicBrainzAdapter(HttpAdapter):
    """Identity, credits, tags, relations and links from the MusicBrainz web service."""

    name = "musicbrainz"
    pass_ = Pass.IDENTITY
    group = SourceGroup.CORE
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

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Find the recording or release group and collect what MusicBrainz knows about it."""
        target = await self._find_by_ids(query)
        if target is None:
            target = await self._find_by_text(query, context)
        if target is None:
            raise NotFoundError("no matching record in MusicBrainz")

        kind, mbid = target
        if kind is EntityKind.TRACK:
            return self._track_partial(await self._track_sources(mbid))
        return await self._album(mbid)

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
        for isrc in context.identity.isrcs:
            if (found := await self._by_isrc(isrc.value, reference)) is not None:
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
                if ranked:
                    return EntityKind.TRACK, ranked[0].id
        return None

    async def _search_album(self, reference: RecordKey) -> Target | None:
        title, artist = p.phrase(reference.title), p.phrase(reference.artist)
        found = await self._get(
            models.ReleaseGroupSearch,
            "release-group",
            query=f"releasegroup:{title} AND artist:{artist}",
            limit=_SEARCH_LIMIT,
        )
        ranked = p.rank_release_groups(reference, found.release_groups)
        return (EntityKind.ALBUM, ranked[0].id) if ranked else None

    async def _members(self, artist_credit: list[models.ArtistCredit]) -> list[Relation]:
        if not artist_credit:
            return []
        artist = await self._get(
            models.Artist,
            f"artist/{artist_credit[0].artist.id}",
            inc="artist-rels",
        )
        return p.member_relations(artist)

    async def _track_sources(self, mbid: str) -> _TrackSources:
        recording = await self._get(models.Recording, f"recording/{mbid}", inc=_RECORDING_INC)
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
        if performance is not None and performance.work is not None:
            work = await self._get(models.Work, f"work/{performance.work.id}", inc=_WORK_INC)

        return _TrackSources(
            recording=recording,
            release=release,
            group=group,
            work=work,
            is_cover=performance is not None and "cover" in performance.attributes,
            members=await self._members(recording.artist_credit),
        )

    def _track_partial(self, found: _TrackSources) -> Partial:
        recording, release, group, work = found.recording, found.release, found.group, found.work
        url = p.page("recording", recording.id)
        people = p.artist_credits(recording.relations, Scope.RECORDING, url)
        tags = p.tags(recording.tags, recording.genres, Scope.RECORDING, url)
        links = p.links(recording.relations, LinkTarget.TRACK, url)

        relations = [
            *p.recording_relations(recording.relations, Scope.RECORDING, url),
            *p.appearances(recording.releases, None, url),
            *found.members,
        ]

        if release is not None:
            relations += p.label_relations(release)
        if work is not None:
            people += p.artist_credits(work.relations, Scope.WORK, p.page("work", work.id))
            version = p.recording_version(recording.title, recording.disambiguation)
            relations += p.work_relations(work, recording.id, version, found.is_cover)
        if group is not None:
            group_url = p.page("release-group", group.id)
            tags += p.tags(group.tags, group.genres, Scope.RELEASE_GROUP, group_url)
            links += p.links(group.relations, LinkTarget.ALBUM, group_url)

        return Partial(
            source=self.name,
            candidate=_track_candidate(found),
            tags=tags,
            credits=people,
            relations=relations,
            links=links,
        )

    async def _album(self, group_id: str) -> Partial:
        group = await self._get(models.ReleaseGroup, f"release-group/{group_id}", inc=_GROUP_INC)
        url = p.page("release-group", group_id)
        main = p.first_release(group.releases)
        release = None
        if main is not None:
            release = await self._get(models.Release, f"release/{main.id}", inc=_ALBUM_RELEASE_INC)

        people = p.artist_credits(group.relations, Scope.RELEASE_GROUP, url)
        relations = await self._members(group.artist_credit)
        links = p.links(group.relations, LinkTarget.ALBUM, url)
        if release is not None:
            release_url = p.page("release", release.id)
            people += p.artist_credits(release.relations, Scope.RELEASE, release_url)
            people += p.track_credits(release)
            relations += p.label_relations(release)
            links += p.links(release.relations, LinkTarget.ALBUM, release_url)

        return Partial(
            source=self.name,
            candidate=_album_candidate(group, release),
            tags=p.tags(group.tags, group.genres, Scope.RELEASE_GROUP, url),
            credits=people,
            relations=relations,
            links=links,
        )


def _track_candidate(found: _TrackSources) -> RecordCandidate:
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

    return RecordCandidate(
        kind=EntityKind.TRACK,
        artist=p.credit_name(recording.artist_credit),
        title=recording.title,
        version=p.recording_version(recording.title, recording.disambiguation),
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
