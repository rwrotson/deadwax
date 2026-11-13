import json
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel, ValidationError

from deadwax.core import (
    CandidateLabel,
    Credit,
    EntityKind,
    IdKind,
    Link,
    LinkTarget,
    Partial,
    Provenance,
    RecordCandidate,
    RecordKey,
    Scope,
    SourceError,
    Tag,
    TagKind,
    VersionInfo,
    classify_marker,
    recognize_url,
)
from deadwax.sources._base import SearchHit
from deadwax.sources._html import parse_html
from deadwax.sources.beatport import models

SOURCE = "beatport"
SERVICE = "beatport"
SITE = "https://www.beatport.com"


def next_data(content: bytes, url: str) -> object:
    """Decode the Next.js state embedded in a Beatport page."""
    script = parse_html(content).css_first("script#__NEXT_DATA__")
    if script is None:
        raise SourceError("the Beatport page has no __NEXT_DATA__ state", url=url)
    try:
        return json.loads(script.text())
    except ValueError:
        raise SourceError("the Beatport page state is not valid JSON", url=url) from None


def _objects(value: object) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from _objects(item)


def _is_track(item: dict[str, Any]) -> bool:
    return "mix_name" in item and ("id" in item or "track_id" in item)


def _is_release(item: dict[str, Any]) -> bool:
    return (
        "catalog_number" in item
        and "mix_name" not in item
        and ("id" in item or "release_id" in item)
        and ("name" in item or "release_name" in item)
    )


def _valid[T: BaseModel](model: type[T], items: Iterator[dict[str, Any]]) -> list[T]:
    """Validate the objects that look like the model; the state also holds unrelated shapes."""
    found: dict[object, tuple[int, T]] = {}
    for item in items:
        try:
            parsed = model.model_validate(item)
        except ValidationError:
            continue
        key = getattr(parsed, "id", None)

        # The fullest copy of an object wins: a track's own entry over its copy in a list.
        if key not in found or len(item) > found[key][0]:
            found[key] = (len(item), parsed)
    return [parsed for _, parsed in found.values()]


def tracks(state: object) -> list[models.Track]:
    """Tracks found anywhere in the page state."""
    return _valid(models.Track, (item for item in _objects(state) if _is_track(item)))


def releases(state: object) -> list[models.Release]:
    """Releases found anywhere in the page state."""
    return _valid(models.Release, (item for item in _objects(state) if _is_release(item)))


def artist_name(artists: list[models.Named]) -> str:
    """Credited artists joined the way the matching gate splits collaborations."""
    return " & ".join(artist.name for artist in artists)


def track_title(track: models.Track) -> str:
    """Title with the mix name in brackets, as the matching gate reads versions."""
    return f"{track.name} ({track.mix_name})" if track.mix_name else track.name


def track_url(track: models.Track) -> str:
    """Page of a track."""
    return f"{SITE}/track/{track.slug or 'track'}/{track.id}"


def release_url(release: models.Release) -> str:
    """Page of a release."""
    return f"{SITE}/release/{release.slug or 'release'}/{release.id}"


def track_hits(state: object) -> list[SearchHit]:
    """Track search results."""
    return [
        SearchHit(
            url=track_url(track),
            key=RecordKey(
                artist=artist_name(track.artists),
                title=track_title(track),
                kind=EntityKind.TRACK,
            ),
        )
        for track in tracks(state)
        if track.artists
    ]


def release_hits(state: object) -> list[SearchHit]:
    """Release search results."""
    return [
        SearchHit(
            url=release_url(release),
            key=RecordKey(
                artist=artist_name(release.artists),
                title=release.name,
                kind=EntityKind.ALBUM,
            ),
        )
        for release in releases(state)
        if release.artists
    ]


def mix_version(mix_name: str | None) -> VersionInfo | None:
    """Version a mix name denotes; None leaves it to the title."""
    if not mix_name:
        return None
    kind = classify_marker(mix_name)
    return VersionInfo(kind=kind, detail=mix_name.strip()) if kind is not None else None


def _date(publish_date: str | None, new_release_date: str | None) -> str | None:
    """The first date the record was on sale; Beatport gives 'YYYY-MM-DD'."""
    return publish_date or new_release_date


def _tags(
    genres: list[models.Named],
    styles: list[models.Named],
    provenance: Provenance,
    scope: Scope,
) -> list[Tag]:
    named = [(genre.name, TagKind.GENRE) for genre in genres]
    named += [(style.name, TagKind.STYLE) for style in styles]
    return [Tag(name=name, kind=kind, scope=scope, sources=[provenance]) for name, kind in named]


def _remixers(remixers: list[models.Named], provenance: Provenance, scope: Scope) -> list[Credit]:
    return [
        Credit(role="remixer", name=remixer.name, scope=scope, sources=[provenance])
        for remixer in remixers
    ]


def _labels(name: str | None, catalog_number: str | None) -> list[CandidateLabel]:
    return [CandidateLabel(name=name, catalog_number=catalog_number)] if name else []


def track_partial(track: models.Track, url: str) -> Partial:
    """Identity, tempo, key, genres, and remixers of a track page."""
    provenance = Provenance(source=SOURCE, url=url)
    release = track.release
    label = track.label or (release.label if release is not None else None)
    candidate = RecordCandidate(
        kind=EntityKind.TRACK,
        artist=artist_name(track.artists),
        title=track_title(track),
        version=mix_version(track.mix_name),
        date=_date(track.publish_date, track.new_release_date),
        bpm=track.bpm or None,
        key=track.key.name if track.key is not None else None,
        labels=_labels(
            label.name if label is not None else None,
            release.catalog_number if release is not None else None,
        ),
        isrcs=[track.isrc] if track.isrc else [],
        ids={IdKind.BEATPORT_TRACK: str(track.id)},
        url=url,
    )
    return Partial(
        source=SOURCE,
        candidate=candidate,
        tags=_tags(track.genres, track.sub_genres, provenance, Scope.RECORDING),
        credits=_remixers(track.remixers, provenance, Scope.RECORDING),
        links=[Link(service=SERVICE, url=url, target=LinkTarget.TRACK, sources=[provenance])],
    )


def release_partial(
    release: models.Release,
    release_tracks: list[models.Track],
    url: str,
) -> Partial:
    """Identity, label, and the genres of a release page's tracks."""
    provenance = Provenance(source=SOURCE, url=url)
    genres = list({g.name: g for t in release_tracks for g in t.genres}.values())
    styles = list({s.name: s for t in release_tracks for s in t.sub_genres}.values())
    candidate = RecordCandidate(
        kind=EntityKind.ALBUM,
        artist=artist_name(release.artists),
        title=release.name,
        date=_date(release.publish_date, release.new_release_date),
        labels=_labels(release.label.name if release.label else None, release.catalog_number),
        upcs=[release.upc] if release.upc else [],
        ids={IdKind.BEATPORT_RELEASE: str(release.id)},
        url=url,
    )
    return Partial(
        source=SOURCE,
        candidate=candidate,
        tags=_tags(release.genres or genres, styles, provenance, Scope.RELEASE),
        credits=_remixers(release.remixers, provenance, Scope.RELEASE),
        links=[Link(service=SERVICE, url=url, target=LinkTarget.ALBUM, sources=[provenance])],
    )


def page_partial(content: bytes, url: str) -> Partial:
    """Read a track or release page, choosing the object whose ID the URL names."""
    state = next_data(content, url)
    kind, ids = recognize_url(url)
    if kind is EntityKind.ALBUM:
        wanted = ids.get(IdKind.BEATPORT_RELEASE)
        found = releases(state)
        release = next((r for r in found if str(r.id) == wanted), found[0] if found else None)
        if release is None:
            raise SourceError("the Beatport release page lists no release", url=url)
        on_release = [
            t for t in tracks(state) if t.release is None or t.release.id in {None, release.id}
        ]
        return release_partial(release, on_release, url)

    wanted = ids.get(IdKind.BEATPORT_TRACK)
    found_tracks = tracks(state)
    track = next((t for t in found_tracks if str(t.id) == wanted), None)
    if track is None:
        raise SourceError("the Beatport track page does not list its track", url=url)
    return track_partial(track, url)
