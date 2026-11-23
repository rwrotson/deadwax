from collections.abc import Iterable
from email.utils import parsedate_to_datetime
from itertools import chain

from deadwax.core import (
    Entity,
    EntityType,
    IdKind,
    Metric,
    MetricKind,
    Provenance,
    Rating,
    Relation,
    RelationKind,
    Scope,
    SimilarityObservation,
    Text,
    TextKind,
)
from deadwax.sources.adapters.listenbrainz import models

SOURCE = "listenbrainz"
CRITIQUEBRAINZ = "CritiqueBrainz"
RATING_SCALE = 5.0
MUSICBRAINZ = "https://musicbrainz.org"
LISTENBRAINZ = "https://listenbrainz.org"


def page(entity: str, mbid: str) -> str:
    """ListenBrainz page of a MusicBrainz entity, such as 'track' or 'album'."""
    return f"{LISTENBRAINZ}/{entity}/{mbid}/"


def metrics(found: Iterable[models.Popularity], scope: Scope, url: str) -> list[Metric]:
    """Listen and listener counts; missing or zero counts are dropped."""
    sources = [Provenance(source=SOURCE, url=url)]
    result = []
    for popularity in found:
        counts = (
            (MetricKind.LISTENS, popularity.total_listen_count),
            (MetricKind.LISTENERS, popularity.total_user_count),
        )
        result += [
            Metric(kind=kind, value=count, scope=scope, sources=sources)
            for kind, count in counts
            if count
        ]
    return result


def similar_recordings(
    found: Iterable[models.SimilarRecording],
    url: str,
    limit: int,
) -> list[Relation]:
    """Recordings listened to in the same sessions, best first."""
    sources = [Provenance(source=SOURCE, url=url)]
    return [
        Relation(
            kind=RelationKind.SIMILAR,
            target=Entity(
                type=EntityType.RECORDING,
                name=recording.recording_name,
                artist=recording.artist_credit_name or None,
                url=f"{MUSICBRAINZ}/recording/{recording.recording_mbid}",
                ids={IdKind.MUSICBRAINZ_RECORDING: recording.recording_mbid},
            ),
            scope=Scope.RECORDING,
            sources=sources,
            similarity_observations=[
                SimilarityObservation(provenance=sources[0], score=recording.score, rank=rank),
            ],
        )
        for rank, recording in enumerate(list(found)[:limit], start=1)
    ]


def similar_artists(
    found: Iterable[models.SimilarArtist],
    url: str,
    limit: int,
) -> list[Relation]:
    """Artists listened to in the same sessions, best first."""
    sources = [Provenance(source=SOURCE, url=url)]
    return [
        Relation(
            kind=RelationKind.SIMILAR,
            target=Entity(
                type=EntityType.ARTIST,
                name=artist.name,
                url=f"{MUSICBRAINZ}/artist/{artist.artist_mbid}",
                ids={IdKind.MUSICBRAINZ_ARTIST: artist.artist_mbid},
            ),
            scope=Scope.ARTIST,
            sources=sources,
            similarity_observations=[
                SimilarityObservation(provenance=sources[0], score=artist.score, rank=rank),
            ],
        )
        for rank, artist in enumerate(list(found)[:limit], start=1)
    ]


def radio_seeds(
    found: dict[str, list[models.RadioRecording]],
    artist: str,
) -> list[tuple[int, models.RadioRecording]]:
    """Ranked LB Radio recordings with the seed artist filtered out."""
    return [
        (rank, item)
        for rank, item in enumerate(chain.from_iterable(found.values()), start=1)
        if item.similar_artist_mbid != artist
    ]


def radio_recordings(
    found: Iterable[tuple[int, models.RadioRecording]],
    names: dict[str, models.RecordingMetadata],
    url: str,
) -> list[Relation]:
    """Recordings by similar artists whose titles the metadata endpoint resolved."""
    sources = [Provenance(source=SOURCE, url=url)]
    result = []
    for rank, item in found:
        entry = names.get(item.recording_mbid)
        title = entry.recording.name if entry and entry.recording else None
        if not title:
            continue
        credit = entry.artist.name if entry and entry.artist else None
        result.append(
            Relation(
                kind=RelationKind.SIMILAR_ARTIST_RECORDING,
                target=Entity(
                    type=EntityType.RECORDING,
                    name=title,
                    artist=credit or item.similar_artist_name or None,
                    url=f"{MUSICBRAINZ}/recording/{item.recording_mbid}",
                    ids={IdKind.MUSICBRAINZ_RECORDING: item.recording_mbid},
                ),
                scope=Scope.ARTIST,
                sources=sources,
                similarity_observations=[
                    SimilarityObservation(provenance=sources[0], rank=rank),
                ],
            ),
        )
    return result


def published(value: str | None) -> str | None:
    """Convert 'Fri, 26 Sep 2014 16:31:32 GMT' to an ISO date."""
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except TypeError, ValueError:
        return None


def reviews(found: Iterable[models.Review], scope: Scope) -> list[Text]:
    """Reviews with a body; a republished review keeps its publication."""
    result = []
    for review in found:
        body = "\n".join(line.rstrip() for line in (review.text or "").splitlines()).strip()
        if not body:
            continue
        rating = Rating(value=review.rating, scale=RATING_SCALE) if review.rating else None
        result.append(
            Text(
                kind=TextKind.REVIEW if review.source else TextKind.USER,
                body=body,
                author=review.user.display_name if review.user else None,
                publication=review.source or CRITIQUEBRAINZ,
                date=published(review.published_on),
                rating=rating,
                language=review.language,
                scope=scope,
                sources=[
                    Provenance(
                        source=SOURCE,
                        url=f"https://critiquebrainz.org/review/{review.id}",
                    ),
                ],
            ),
        )
    return result
