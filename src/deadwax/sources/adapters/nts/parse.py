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

API = "https://www.nts.live/api/v2"


def as_object(value: object) -> dict[str, object]:
    """The value as a JSON object, or an empty one."""
    return value if isinstance(value, dict) else {}


def as_objects(value: object) -> list[dict[str, object]]:
    """The JSON objects of a list value."""
    return [as_object(item) for item in value] if isinstance(value, list) else []


def as_text(value: object) -> str | None:
    """The value as non-blank text, stripped."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def episode_url(item: dict[str, object]) -> str | None:
    """Absolute URL of an NTS episode."""
    value = as_text(item.get("url")) or as_text(item.get("path"))
    return urljoin("https://www.nts.live", value) if value else None


def hit_matches(hit: dict[str, object], key: RecordKey) -> bool:
    """Whether a search hit lists the record."""
    artists = as_objects(hit.get("artists"))
    artist = as_text(artists[0].get("name")) if artists else None
    title = as_text(hit.get("title"))
    if not artist or not title:
        return False
    return (
        compare(
            key,
            RecordKey(artist=artist, title=title, kind=EntityKind.TRACK),
        ).verdict
        is Verdict.MATCH
    )


def matching_positions(tracklist: list[dict[str, object]], key: RecordKey) -> list[int]:
    """Positions of the record in an episode tracklist."""
    return [
        index
        for index, track in enumerate(tracklist)
        if compare(
            key,
            RecordKey(
                artist=as_text(track.get("artist")) or "",
                title=as_text(track.get("title")) or "",
                kind=EntityKind.TRACK,
            ),
        ).verdict
        is Verdict.MATCH
    ]


def neighbours(
    tracklist: list[dict[str, object]],
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
            title = as_text(track.get("title"))
            if not title:
                continue
            result.append(
                Relation(
                    kind=RelationKind.CO_PLAYED,
                    target=Entity(
                        type=EntityType.RECORDING,
                        name=title,
                        artist=as_text(track.get("artist")),
                    ),
                    note="before" if neighbour < position else "after",
                    scope=Scope.RECORDING,
                    sources=source,
                ),
            )
    return result
