import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from deadwax.core import (
    CandidateLabel,
    Credit,
    Entity,
    EntityKind,
    EntityType,
    IdKind,
    Link,
    LinkTarget,
    Partial,
    Provenance,
    RecordCandidate,
    RecordKey,
    Relation,
    RelationKind,
    Scope,
    SourceError,
    Tag,
    TagKind,
    TraceEvent,
    VersionInfo,
    classify_marker,
    trace,
)
from deadwax.sources._html import parse_html
from deadwax.sources._search import SearchHit
from deadwax.sources.adapters.beatport import models

SOURCE = "beatport"
SERVICE = "beatport"
SITE = "https://www.beatport.com"
REMIXER = "remixer"

# Characters of an unreadable page state kept in the journal.
_SNIPPET_CHARS = 200

logger = logging.getLogger(__name__)

type PageProps = dict[str, Any]


def page_props(content: bytes, url: str) -> PageProps:
    """Decode the Next.js page properties embedded in a Beatport page."""
    script = parse_html(content).css_first("script#__NEXT_DATA__")
    if script is None:
        raise SourceError("the Beatport page has no __NEXT_DATA__ state", url=url)
    text = script.text()
    try:
        state = json.loads(text)
    except ValueError:
        trace(
            logger,
            TraceEvent.PARSE_UNRECOGNIZED,
            url=url,
            length=len(text),
            head=text[:_SNIPPET_CHARS],
            tail=text[-_SNIPPET_CHARS:],
        )
        raise SourceError("the Beatport page state is not valid JSON", url=url) from None
    props = state.get("props", {}).get("pageProps") if isinstance(state, dict) else None
    if not isinstance(props, dict):
        raise SourceError("the Beatport page state has no page properties", url=url)
    return props


def query_data(props: PageProps, name: str) -> Any:  # noqa: ANN401 -- JSON of any shape
    """Data of the prefetched query whose key starts with `name`, if the page has it."""
    queries = props.get("dehydratedState", {}).get("queries", [])
    for query in queries if isinstance(queries, list) else []:
        key = query.get("queryKey") if isinstance(query, dict) else None
        if isinstance(key, list) and key and key[0] == name:
            return query.get("state", {}).get("data")
    return None


def slug(name: str) -> str:
    """URL slug Beatport derives from a name."""
    return re.sub(r"[^a-z0-9]+", "-", name.casefold().replace("'", "")).strip("-") or "-"


def track_url(track: models.Track) -> str:
    """Page of a track; its slug comes from the name without the mix name."""
    return f"{SITE}/track/{slug(track.name)}/{track.id}"


def release_url(release: models.Release) -> str:
    """Page of a release."""
    return f"{SITE}/release/{release.slug or slug(release.name)}/{release.id}"


def chart_url(chart: models.Chart) -> str:
    """Page of a DJ chart."""
    return f"{SITE}/chart/{chart.slug or slug(chart.name)}/{chart.id}"


def _is_remixer(artist: models.Artist) -> bool:
    return (artist.type or "").casefold() == REMIXER


def artist_name(artists: list[models.Artist]) -> str:
    """Credited artists without remixers, joined the way the matching gate splits them."""
    credited = [artist for artist in artists if not _is_remixer(artist)] or artists
    return " & ".join(artist.name for artist in credited)


def track_title(track: models.Track) -> str:
    """Title with the mix name in brackets, as the matching gate reads versions."""
    return f"{track.name} ({track.mix_name})" if track.mix_name else track.name


def mix_version(mix_name: str | None) -> VersionInfo | None:
    """Version a mix name denotes; None leaves it to the title."""
    if not mix_name:
        return None
    kind = classify_marker(mix_name)
    return VersionInfo(kind=kind, detail=mix_name.strip()) if kind is not None else None


def _day(*dates: str | None) -> str | None:
    """First given date as 'YYYY-MM-DD'; Beatport appends a time to some."""
    return next((date[:10] for date in dates if date), None)


def track_hits(props: PageProps) -> list[SearchHit]:
    """Results of a track search page."""
    try:
        results = models.TrackSearch.model_validate(query_data(props, "search-tracks") or {})
    except ValidationError:
        return []
    return [
        SearchHit(
            url=track_url(track),
            key=RecordKey(
                artist=artist_name(track.artists),
                title=track_title(track),
                kind=EntityKind.TRACK,
            ),
        )
        for track in results.data
        if track.artists
    ]


def release_hits(props: PageProps) -> list[SearchHit]:
    """Results of a release search page."""
    try:
        results = models.ReleaseSearch.model_validate(query_data(props, "search-releases") or {})
    except ValidationError:
        return []
    return [
        SearchHit(
            url=release_url(release),
            key=RecordKey(
                artist=artist_name(release.artists),
                title=release.name,
                kind=EntityKind.ALBUM,
            ),
        )
        for release in results.data
        if release.artists
    ]


def _track_tags(track: models.Track, provenance: Provenance) -> list[Tag]:
    genres = track.genre if isinstance(track.genre, list) else [track.genre] if track.genre else []
    named = [(genre.name, TagKind.GENRE) for genre in genres]
    if isinstance(track.genre, models.Genre) and track.genre.sub_genre is not None:
        named.append((track.genre.sub_genre.name, TagKind.STYLE))
    return [
        Tag(name=name, kind=kind, scope=Scope.RECORDING, sources=[provenance])
        for name, kind in named
        if name
    ]


def _remixers(remixers: list[models.Artist], provenance: Provenance, scope: Scope) -> list[Credit]:
    return [
        Credit(role=REMIXER, name=remixer.name, scope=scope, sources=[provenance])
        for remixer in remixers
    ]


def chart_owner(chart: models.Chart) -> str | None:
    """DJ who published a chart."""
    if chart.artist is not None:
        return chart.artist.name
    return chart.person.owner_name if chart.person is not None else None


def _chart_relations(charts: models.Charts, provenance: Provenance) -> list[Relation]:
    return [
        Relation(
            kind=RelationKind.CHARTED_BY,
            scope=Scope.RECORDING,
            target=Entity(
                type=EntityType.CHART,
                name=chart.name,
                artist=chart_owner(chart),
                date=_day(chart.publish_date),
                url=chart_url(chart),
            ),
            sources=[provenance],
        )
        for chart in charts.results
    ]


def _labels(label: models.Named | None, catalog_number: str | None) -> list[CandidateLabel]:
    if label is None or not label.name:
        return []
    return [CandidateLabel(name=label.name, catalog_number=catalog_number)]


def track_partial(track: models.Track, charts: models.Charts, url: str) -> Partial:
    """Identity, tempo, key, genres, remixers, and charts of a track page."""
    provenance = Provenance(source=SOURCE, url=url)
    release = track.release or models.ReleaseRef()
    candidate = RecordCandidate(
        kind=EntityKind.TRACK,
        artist=artist_name(track.artists),
        title=track_title(track),
        version=mix_version(track.mix_name),
        date=_day(release.release_date, track.publish_date, track.release_date),
        bpm=track.bpm or None,
        key=track.key or None,
        labels=_labels(track.label, release.catalog_number or track.catalog_number),
        isrcs=[track.isrc] if track.isrc else [],
        ids={IdKind.BEATPORT_TRACK: str(track.id)},
        url=url,
    )
    remixers = [artist for artist in track.artists if _is_remixer(artist)]
    return Partial(
        source=SOURCE,
        candidate=candidate,
        tags=_track_tags(track, provenance),
        credits=_remixers(remixers, provenance, Scope.RECORDING),
        relations=_chart_relations(charts, provenance),
        links=[Link(service=SERVICE, url=url, target=LinkTarget.TRACK, sources=[provenance])],
    )


def release_partial(release: models.Release, url: str) -> Partial:
    """Identity, label, and remixers of a release page."""
    provenance = Provenance(source=SOURCE, url=url)
    candidate = RecordCandidate(
        kind=EntityKind.ALBUM,
        artist=artist_name(release.artists),
        title=release.name,
        date=_day(release.new_release_date, release.publish_date, release.release_date),
        labels=_labels(release.label, release.catalog_number),
        upcs=[release.upc] if release.upc else [],
        ids={IdKind.BEATPORT_RELEASE: str(release.id)},
        url=url,
    )
    return Partial(
        source=SOURCE,
        candidate=candidate,
        tags=[
            Tag(name=genre.name, kind=TagKind.GENRE, scope=Scope.RELEASE, sources=[provenance])
            for genre in release.genre
            if genre.name
        ],
        credits=_remixers(release.remixers, provenance, Scope.RELEASE),
        links=[Link(service=SERVICE, url=url, target=LinkTarget.ALBUM, sources=[provenance])],
    )


def page_partial(content: bytes, url: str) -> Partial:
    """Read a track or release page."""
    props = page_props(content, url)
    try:
        if isinstance(props.get("release"), dict):
            return release_partial(models.Release.model_validate(props["release"]), url)
        if isinstance(props.get("track"), dict):
            track = models.Track.model_validate(props["track"])
            charts = models.Charts.model_validate(
                query_data(props, f"track-{track.id}-charts") or {},
            )
            return track_partial(track, charts, url)
    except ValidationError as error:
        message = f"unexpected Beatport page state ({error.error_count()} invalid fields)"
        raise SourceError(message, url=url) from None
    raise SourceError("the Beatport page is neither a track nor a release", url=url)
