import re

from deadwax.core import (
    CandidateLabel,
    EntityKind,
    IdKind,
    Link,
    LinkTarget,
    Metric,
    MetricKind,
    Partial,
    Provenance,
    RecordCandidate,
    RecordKey,
    Scope,
)
from deadwax.sources._base import SearchHit
from deadwax.sources.spotify import models

SOURCE = "spotify"
SERVICE = "spotify"
POPULARITY_SCALE = 100.0

# Copyright lines that already start with their mark.
_MARKED = re.compile(r"^\s*(?:℗|©|\([PpCc]\))")
_MARKS = {"P": "℗", "C": "©"}


def artist_name(artists: list[models.Artist]) -> str:
    """Credited artists joined the way the matching gate splits collaborations."""
    return ", ".join(artist.name for artist in artists)


def copyright_line(copyright_: models.Copyright) -> str:
    """Copyright text with its ℗ or © mark, which Spotify gives as a separate type."""
    text = copyright_.text.strip()
    mark = _MARKS.get(copyright_.type or "")
    if mark is None or _MARKED.match(text):
        return text
    return f"{mark} {text}"


def track_hits(results: models.SearchResults) -> list[SearchHit]:
    """Track search results as hits pointing at their API objects."""
    return [
        SearchHit(
            url=track.href,
            key=RecordKey(
                artist=artist_name(track.artists),
                title=track.name,
                kind=EntityKind.TRACK,
            ),
        )
        for track in results.tracks.items
        if track is not None and track.href
    ]


def album_hits(results: models.SearchResults) -> list[SearchHit]:
    """Album search results as hits pointing at their API objects."""
    return [
        SearchHit(
            url=album.href,
            key=RecordKey(
                artist=artist_name(album.artists),
                title=album.name,
                kind=EntityKind.ALBUM,
            ),
        )
        for album in results.albums.items
        if album is not None and album.href
    ]


def _artist_links(artists: list[models.Artist], sources: list[Provenance]) -> list[Link]:
    return [
        Link(service=SERVICE, url=url, target=LinkTarget.ARTIST, sources=sources)
        for artist in artists
        if (url := artist.external_urls.spotify)
    ]


def _album_facts(album: models.Album | None) -> dict[str, object]:
    if album is None:
        return {}
    return {
        "labels": [CandidateLabel(name=album.label)] if album.label else [],
        "copyrights": [copyright_line(line) for line in album.copyrights if line.text.strip()],
    }


def _popularity(value: int | None, scope: Scope, sources: list[Provenance]) -> list[Metric]:
    if value is None:
        return []
    return [
        Metric(
            kind=MetricKind.POPULARITY,
            value=value,
            scale=POPULARITY_SCALE,
            scope=scope,
            sources=sources,
        ),
    ]


def track_partial(track: models.Track, album: models.Album | None) -> Partial:
    """Describe a track with its codes, its album's label and copyrights, links and popularity.

    Copyrights and label belong to the album the track was read from.
    """
    url = track.external_urls.spotify
    sources = [Provenance(source=SOURCE, url=url)]

    links = []
    if url:
        links.append(
            Link(
                service=SERVICE,
                url=url,
                target=LinkTarget.TRACK,
                preview_url=track.preview_url or None,
                sources=sources,
            ),
        )
    if track.album is not None and (album_url := track.album.external_urls.spotify):
        links.append(Link(service=SERVICE, url=album_url, target=LinkTarget.ALBUM, sources=sources))
    links += _artist_links(track.artists, sources)

    candidate = RecordCandidate.model_validate(
        {
            "kind": EntityKind.TRACK,
            "artist": artist_name(track.artists),
            "title": track.name,
            "date": track.album.release_date if track.album is not None else None,
            "isrcs": [track.external_ids.isrc] if track.external_ids.isrc else [],
            "ids": {IdKind.SPOTIFY: track.id},
            "url": url,
            **_album_facts(album),
        },
    )
    return Partial(
        source=SOURCE,
        candidate=candidate,
        metrics=_popularity(track.popularity, Scope.RECORDING, sources),
        links=links,
    )


def album_partial(album: models.Album) -> Partial:
    """Describe an album with its barcode, label, copyrights, links and popularity."""
    url = album.external_urls.spotify
    sources = [Provenance(source=SOURCE, url=url)]

    links = []
    if url:
        links.append(Link(service=SERVICE, url=url, target=LinkTarget.ALBUM, sources=sources))
    links += _artist_links(album.artists, sources)

    candidate = RecordCandidate.model_validate(
        {
            "kind": EntityKind.ALBUM,
            "artist": artist_name(album.artists),
            "title": album.name,
            "date": album.release_date,
            "upcs": [album.external_ids.upc] if album.external_ids.upc else [],
            "ids": {IdKind.SPOTIFY: album.id},
            "url": url,
            **_album_facts(album),
        },
    )
    return Partial(
        source=SOURCE,
        candidate=candidate,
        metrics=_popularity(album.popularity, Scope.RELEASE, sources),
        links=links,
    )
