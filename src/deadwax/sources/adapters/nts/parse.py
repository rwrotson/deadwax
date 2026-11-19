from urllib.parse import urljoin

from deadwax.core import (
    Entity,
    EntityKind,
    EntityType,
    Provenance,
    RecordKey,
    Relation,
    RelationKind,
    Scope,
    Verdict,
    compare,
)
from deadwax.sources.adapters.nts.models import Article, Hit, Track

API = "https://www.nts.live/api/v2"


def episode_url(article: Article) -> str | None:
    """Absolute URL of an NTS episode."""
    value = article.url or article.path
    return urljoin("https://www.nts.live", value) if value else None


def hit_matches(hit: Hit, key: RecordKey) -> bool:
    """Whether a search hit lists the record."""
    artist = hit.artists[0].name if hit.artists else None
    title = hit.title
    if not artist or not title:
        return False
    return (
        compare(
            key,
            RecordKey(artist=artist, title=title, kind=EntityKind.TRACK),
        ).verdict
        is Verdict.MATCH
    )


def matching_positions(tracklist: list[Track], key: RecordKey) -> list[int]:
    """Positions of the record in an episode tracklist."""
    return [
        index
        for index, track in enumerate(tracklist)
        if compare(
            key,
            RecordKey(
                artist=track.artist or "",
                title=track.title or "",
                kind=EntityKind.TRACK,
            ),
        ).verdict
        is Verdict.MATCH
    ]


def neighbours(
    tracklist: list[Track],
    positions: list[int],
    source: list[Provenance],
) -> list[Relation]:
    """Tracks played right before and after the record, as relations."""
    result = []
    for position in positions:
        for neighbour in (position - 1, position + 1):
            if not 0 <= neighbour < len(tracklist):
                continue
            track = tracklist[neighbour]
            title = track.title
            if not title:
                continue
            result.append(
                Relation(
                    kind=RelationKind.CO_PLAYED,
                    target=Entity(
                        type=EntityType.RECORDING,
                        name=title,
                        artist=track.artist,
                    ),
                    note="before" if neighbour < position else "after",
                    scope=Scope.RECORDING,
                    sources=source,
                ),
            )
    return result
