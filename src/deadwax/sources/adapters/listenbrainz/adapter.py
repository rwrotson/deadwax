import json

from deadwax.core import (
    Capability,
    EntityKind,
    IdKind,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Query,
    Relation,
    Scope,
    SourceGroup,
    Text,
)
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources.adapters.listenbrainz import models
from deadwax.sources.adapters.listenbrainz import parse as p

API = "https://api.listenbrainz.org/1"
LABS = "https://labs.api.listenbrainz.org"
CRITIQUEBRAINZ = "https://critiquebrainz.org/ws/1/review/"

# Datasets of the labs similarity endpoints; ListenBrainz lists them on its labs pages.
RECORDING_ALGORITHM = (
    "session_based_days_9000_session_300_contribution_5_threshold_15_limit_50_skip_30"
)
ARTIST_ALGORITHM = (
    "session_based_days_7500_session_300_contribution_5_threshold_10_limit_100_filter_True_skip_30"
)

SIMILAR_RECORDINGS = 20
SIMILAR_ARTISTS = 10
REVIEWS = "10"


class ListenBrainzAdapter(HttpAdapter):
    """Listen counts, similar recordings and artists, and CritiqueBrainz reviews by MBID."""

    name = "listenbrainz"
    pass_ = Pass.ENRICH
    group = SourceGroup.CATALOGUES
    capabilities = frozenset({Capability.TEXTS, Capability.RELATIONS, Capability.METRICS})

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Read what ListenBrainz knows about the MusicBrainz entity earlier sources found."""
        artist = context.id(IdKind.MUSICBRAINZ_ARTIST)
        group = context.id(IdKind.MUSICBRAINZ_RELEASE_GROUP)
        if (query.kind or context.identity.kind) is EntityKind.ALBUM:
            if group is None:
                raise NotFoundError("no MusicBrainz release group from earlier sources")
            return await self._album(group, artist)

        recording = context.id(IdKind.MUSICBRAINZ_RECORDING)
        if recording is None:
            raise NotFoundError("no MusicBrainz recording from earlier sources")
        return await self._track(recording, group, artist)

    async def _popularity(self, entity: str, mbid: str) -> list[models.Popularity]:
        body = json.dumps({f"{entity.replace('-', '_')}_mbids": [mbid]}).encode()
        response = await self.client.request(
            "POST",
            f"{API}/popularity/{entity}",
            headers={"content-type": "application/json"},
            body=body,
        )
        return models.popularity_list.validate_json(response.content)

    async def _similar_artists(self, artist: str | None) -> list[Relation]:
        if artist is None:
            return []
        response = await self.client.get(
            f"{LABS}/similar-artists/json",
            params={"artist_mbids": artist, "algorithm": ARTIST_ALGORITHM},
        )
        found = models.similar_artists.validate_json(response.content)
        return p.similar_artists(found, p.page("artist", artist), SIMILAR_ARTISTS)

    async def _reviews(self, entity_type: str, mbid: str | None, scope: Scope) -> list[Text]:
        if mbid is None:
            return []
        response = await self.client.get(
            CRITIQUEBRAINZ,
            params={"entity_id": mbid, "entity_type": entity_type, "limit": REVIEWS},
        )
        return p.reviews(models.ReviewList.model_validate_json(response.content).reviews, scope)

    async def _track(self, recording: str, group: str | None, artist: str | None) -> Partial:
        url = p.page("track", recording)
        popularity = await self._popularity("recording", recording)
        response = await self.client.get(
            f"{LABS}/similar-recordings/json",
            params={"recording_mbids": recording, "algorithm": RECORDING_ALGORITHM},
        )
        similar = models.similar_recordings.validate_json(response.content)
        return Partial(
            source=self.name,
            metrics=p.metrics(popularity, Scope.RECORDING, url),
            relations=p.similar_recordings(similar, url, SIMILAR_RECORDINGS)
            + await self._similar_artists(artist),
            texts=await self._reviews("recording", recording, Scope.RECORDING)
            + await self._reviews("release_group", group, Scope.RELEASE_GROUP),
        )

    async def _album(self, group: str, artist: str | None) -> Partial:
        url = p.page("album", group)
        popularity = await self._popularity("release-group", group)
        return Partial(
            source=self.name,
            metrics=p.metrics(popularity, Scope.RELEASE_GROUP, url),
            relations=await self._similar_artists(artist),
            texts=await self._reviews("release_group", group, Scope.RELEASE_GROUP),
        )
