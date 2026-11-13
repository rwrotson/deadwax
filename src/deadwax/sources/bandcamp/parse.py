import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

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
    Tag,
    TagKind,
    Text,
    TextKind,
    Verdict,
    artist_similarity,
    compare,
    normalize_artist,
)
from deadwax.sources._html import (
    Document,
    JsonObject,
    attribute,
    attribute_json,
    json_ld,
    parse_html,
    text_of,
)
from deadwax.sources.bandcamp import models

logger = logging.getLogger(__name__)

SOURCE = "bandcamp"
LABEL_RELEASES_LIMIT = 12

# Artist similarity from which a track's and its album's artists count as the same.
SAME_ARTIST = 0.85

# Verbs of "<verb> by <names>" credit lines and the roles they name.
_CREDIT_ROLES = {
    "written": "writer",
    "composed": "composer",
    "produced": "producer",
    "co-produced": "co-producer",
    "mixed": "mix",
    "mastered": "mastering",
    "engineered": "engineer",
    "recorded": "recording",
    "arranged": "arranger",
    "remixed": "remixer",
    "performed": "performer",
    "lyrics": "lyricist",
    "artwork": "artwork",
    "art": "artwork",
    "cover art": "artwork",
    "design": "design",
    "layout": "design",
    "photography": "photography",
    "photo": "photography",
    "photos": "photography",
}
_CREDIT_LINE = re.compile(r"^(?P<verbs>[a-z][a-z &,/-]*?)\s+by\s+(?P<names>.+?)\.?$", re.IGNORECASE)
_NAME_SEPARATOR = re.compile(r"\s*(?:,|&|\band\b)\s*")
_VERB_SEPARATOR = re.compile(r"\s*(?:,|&|/|\band\b)\s*")
# Pages give dates in GMT.
_PAGE_DATE = "%d %b %Y %H:%M:%S GMT"


@dataclass(frozen=True, slots=True)
class Page:
    """What an album or track page holds."""

    url: str
    tralbum: models.Tralbum | None
    ld: JsonObject | None
    embed_artist: str | None = None
    recommendations: list[Relation] = field(default_factory=list)

    @property
    def found(self) -> bool:
        """Whether the page describes a release or track."""
        return self.tralbum is not None or self.ld is not None


@dataclass(frozen=True, slots=True)
class Record:
    """Release or track as read from a page or the mobile API."""

    kind: EntityKind
    artist: str
    title: str
    url: str
    id: int | None = None
    band_id: int | None = None
    date: str | None = None
    about: str | None = None
    credits: str | None = None
    isrc: str | None = None
    upc: str | None = None
    label: str | None = None
    seller: str | None = None
    seller_url: str | None = None
    album: Entity | None = None
    tags: tuple[str, ...] = ()
    comments: tuple[Text, ...] = ()
    recommendations: tuple[Relation, ...] = ()
    tracks: tuple[models.TrackInfo, ...] = ()


def page_url(url: str) -> str:
    """Drop the query and fragment, which carry only tracking parameters."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(query="", fragment=""))


def page_date(text: str | None) -> str | None:
    """Convert a page date such as '20 Jun 2016 00:00:00 GMT' to an ISO date."""
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, _PAGE_DATE).replace(tzinfo=UTC)
        return parsed.date().isoformat()
    except ValueError:
        logger.debug("unexpected Bandcamp date %r", text)
        return None


def unix_date(timestamp: int | None) -> str | None:
    """Convert a Unix time to an ISO date."""
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, UTC).date().isoformat()


def _name(value: object) -> str | None:
    if isinstance(value, dict):
        name = value.get("name")
        return name if isinstance(name, str) and name else None
    return None


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _keywords(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(k.strip() for k in value.split(",") if k.strip())
    if isinstance(value, list):
        return tuple(k.strip() for k in value if isinstance(k, str) and k.strip())
    return ()


def _tralbum(document: Document) -> models.Tralbum | None:
    raw = attribute_json(document, "data-tralbum")
    if raw is None:
        return None
    try:
        return models.Tralbum.model_validate(raw)
    except ValidationError:
        logger.debug("unexpected data-tralbum shape")
        return None


def recommendations(document: Document) -> list[Relation]:
    """Read the 'you may also like' block of a page as similar releases."""
    result = []
    for item in document.css("li.recommended-album"):
        title = attribute(item, "data-albumtitle")
        if title is None:
            continue
        href = attribute(item.css_first("a.album-link"), "href")
        album_id = attribute(item, "data-albumid")
        result.append(
            Relation(
                kind=RelationKind.SIMILAR,
                target=Entity(
                    type=EntityType.RELEASE,
                    name=title,
                    artist=attribute(item, "data-artist"),
                    url=page_url(href) if href else None,
                    ids={IdKind.BANDCAMP_ALBUM: album_id} if album_id else {},
                ),
                scope=Scope.RELEASE,
                sources=[],
            ),
        )
    return result


def read_page(content: bytes, url: str) -> Page:
    """Read the data attributes, JSON-LD, and recommendations of an album or track page."""
    document = parse_html(content)
    embed = attribute_json(document, "data-embed") or {}
    return Page(
        url=url,
        tralbum=_tralbum(document),
        ld=next(iter(json_ld(document, "MusicAlbum", "MusicRecording")), None),
        embed_artist=_string(embed.get("artist")),
        recommendations=recommendations(document),
    )


def _comments(ld: JsonObject) -> tuple[Text, ...]:
    result = []
    comments = ld.get("comment")
    for comment in comments if isinstance(comments, list) else []:
        if not isinstance(comment, dict):
            continue
        text = comment.get("text")
        parts = [text] if isinstance(text, str) else text if isinstance(text, list) else []
        body = "\n\n".join(p.strip() for p in parts if isinstance(p, str) and p.strip())
        if body:
            author = comment.get("author")
            result.append(
                Text(
                    kind=TextKind.USER,
                    body=body,
                    author=_name(author),
                    scope=Scope.RELEASE,
                    sources=[],
                ),
            )
    return tuple(result)


def _album_of(ld: JsonObject, url: str, tralbum: models.Tralbum | None) -> Entity | None:
    album = ld.get("inAlbum")
    name = _name(album)
    if name is None:
        return None
    album_url = tralbum.album_url if tralbum is not None else None
    return Entity(
        type=EntityType.RELEASE,
        name=name,
        artist=_name(album.get("byArtist")) if isinstance(album, dict) else None,
        url=urljoin(url, album_url) if album_url else None,
    )


def page_record(page: Page) -> Record | None:
    """Combine what the page's data attributes and JSON-LD say about the release or track."""
    if not page.found:
        return None
    tralbum, ld = page.tralbum, page.ld or {}
    current = tralbum.current if tralbum is not None else models.Current()
    title = current.title or _string(ld.get("name"))
    artist = (
        (tralbum.artist if tralbum is not None else None)
        or current.artist
        or page.embed_artist
        or _name(ld.get("byArtist"))
    )
    if not title or not artist:
        return None
    is_track = (
        (tralbum.item_type == "track")
        if tralbum is not None
        else (ld.get("@type") == "MusicRecording")
    )
    url = page_url(
        (tralbum.url if tralbum is not None else None) or _string(ld.get("@id")) or page.url,
    )
    publisher = ld.get("publisher")
    return Record(
        kind=EntityKind.TRACK if is_track else EntityKind.ALBUM,
        artist=artist,
        title=title,
        url=url,
        id=tralbum.id if tralbum is not None else None,
        band_id=current.band_id,
        date=page_date(current.release_date)
        or page_date(tralbum.album_release_date if tralbum is not None else None)
        or page_date(_string(ld.get("datePublished"))),
        about=current.about or _string(ld.get("description")),
        credits=current.credits or _string(ld.get("creditText")),
        isrc=current.isrc,
        upc=current.upc,
        seller=_name(publisher),
        seller_url=_string(publisher.get("@id")) if isinstance(publisher, dict) else None,
        album=_album_of(ld, url, tralbum) if is_track else None,
        tags=_keywords(ld.get("keywords")),
        comments=_comments(ld),
        recommendations=tuple(page.recommendations),
        tracks=tuple(tralbum.trackinfo) if tralbum is not None else (),
    )


def details_record(details: models.MobileDetails) -> Record:
    """Describe a release or track from the mobile API."""
    url = details.bandcamp_url or ""
    return Record(
        kind=EntityKind.TRACK if details.type == "t" else EntityKind.ALBUM,
        artist=details.tralbum_artist or details.band.name or "",
        title=details.title,
        url=page_url(url),
        id=details.id,
        band_id=details.band.band_id,
        date=unix_date(details.release_date),
        about=details.about,
        credits=details.credits,
        label=details.label,
        seller=details.band.name,
        seller_url=f"{urlsplit(url).scheme}://{urlsplit(url).netloc}" if url else None,
        tags=tuple(tag.name for tag in details.tags if not tag.isloc),
    )


def with_details(record: Record, details: models.MobileDetails) -> Record:
    """Add the label, and tags without locations, that only the mobile API gives."""
    tags = tuple(tag.name for tag in details.tags if not tag.isloc) or record.tags
    return _replace(record, label=details.label or record.label, tags=tags)


def _replace(record: Record, **changes: Any) -> Record:  # noqa: ANN401 -- dataclass fields
    fields = {name: getattr(record, name) for name in Record.__slots__}
    return Record(**(fields | changes))


def credit_lines(text: str | None, scope: Scope, sources: list[Provenance]) -> list[Credit]:
    """Read 'Mastered by X' style lines; other lines stay only in the credits text."""
    result: list[Credit] = []
    for line in (text or "").splitlines():
        match = _CREDIT_LINE.match(line.strip())
        if match is None:
            continue
        verbs = [v.lower() for v in _VERB_SEPARATOR.split(match["verbs"]) if v]
        roles = [_CREDIT_ROLES.get(verb) for verb in verbs]
        if not roles or None in roles:
            continue
        names = [n.strip() for n in _NAME_SEPARATOR.split(match["names"]) if n.strip()]
        result.extend(
            Credit(role=role, name=name, scope=scope, sources=sources)
            for role in roles
            if role is not None
            for name in names
        )
    return result


def _sourced[T: (Text, Relation)](facts: Iterable[T], sources: list[Provenance]) -> list[T]:
    return [fact.model_copy(update={"sources": sources}) for fact in facts]


def on_compilation(record: Record) -> bool:
    """Whether a track page belongs to an album of another artist, such as a compilation."""
    album = record.album
    if record.kind is not EntityKind.TRACK or album is None or not album.artist:
        return False
    return artist_similarity(album.artist, record.artist) < SAME_ARTIST


def own_facts(record: Record) -> Record:
    """Drop what a compilation's track page says about the compilation rather than the track.

    Tags, recommendations, fan texts, date, label, and seller of such a page describe the
    compilation; the track keeps its identity, links, own credits, and notes.
    """
    if not on_compilation(record):
        return record
    return _replace(
        record,
        tags=(),
        comments=(),
        recommendations=(),
        date=None,
        label=None,
        seller=None,
        seller_url=None,
    )


def partial(record: Record, label_releases: Sequence[Relation] = ()) -> Partial:
    """Describe the release or track with its tags, texts, credits, relations, and links."""
    record = own_facts(record)
    sources = [Provenance(source=SOURCE, url=record.url)]
    scope = Scope.RECORDING if record.kind is EntityKind.TRACK else Scope.RELEASE
    id_kind = IdKind.BANDCAMP_TRACK if record.kind is EntityKind.TRACK else IdKind.BANDCAMP_ALBUM
    texts = [
        Text(
            kind=TextKind.LABEL,
            title=title,
            body=body.replace("\r\n", "\n").strip(),
            scope=scope,
            sources=sources,
        )
        for title, body in (("About", record.about), ("Credits", record.credits))
        if body and body.strip()
    ]
    texts += [t.model_copy(update={"scope": scope}) for t in _sourced(record.comments, sources)]
    relations = _sourced(record.recommendations, sources) + list(label_releases)
    if record.label:
        relations.append(
            Relation(
                kind=RelationKind.LABEL,
                target=Entity(type=EntityType.LABEL, name=record.label),
                scope=Scope.RELEASE,
                sources=sources,
            ),
        )
    if record.album is not None:
        kind = RelationKind.COMPILATION if on_compilation(record) else RelationKind.APPEARS_ON
        relations.append(Relation(kind=kind, target=record.album, scope=scope, sources=sources))
    links = [
        Link(
            service=SOURCE,
            url=record.url,
            target=LinkTarget.TRACK if record.kind is EntityKind.TRACK else LinkTarget.ALBUM,
            sources=sources,
        ),
    ]
    if record.album is not None and record.album.url:
        links.append(
            Link(service=SOURCE, url=record.album.url, target=LinkTarget.ALBUM, sources=sources),
        )
    if record.seller_url:
        links.append(
            Link(service=SOURCE, url=record.seller_url, target=LinkTarget.ARTIST, sources=sources),
        )
    return Partial(
        source=SOURCE,
        candidate=RecordCandidate(
            kind=record.kind,
            artist=record.artist,
            title=record.title,
            date=record.date,
            labels=[CandidateLabel(name=record.label)] if record.label else [],
            isrcs=[record.isrc] if record.isrc else [],
            upcs=[record.upc] if record.upc else [],
            ids={id_kind: str(record.id)} if record.id is not None else {},
            url=record.url,
        ),
        tags=[
            Tag(name=name, kind=TagKind.TAG, scope=scope, sources=sources) for name in record.tags
        ],
        credits=credit_lines(record.credits, scope, sources),
        texts=texts,
        relations=relations,
        links=links,
    )


def matches(reference: RecordKey, artist: str | None, title: str, kind: EntityKind) -> bool:
    """Whether a search result or track is the queried record."""
    return compare(reference, RecordKey(artist or "", title, kind)).verdict is Verdict.MATCH


def pick_result(
    reference: RecordKey,
    results: Iterable[models.SearchResult],
) -> models.SearchResult | None:
    """Return the first search result of the right type that matches the query."""
    wanted = "t" if reference.kind is EntityKind.TRACK else "a"
    kind = reference.kind or EntityKind.ALBUM
    return next(
        (
            result
            for result in results
            if result.type == wanted
            and result.item_url_path
            and matches(reference, result.band_name, result.name, kind)
        ),
        None,
    )


def track_url(record: Record, reference: RecordKey) -> str | None:
    """Return the page of the queried track on an album page."""
    for track in record.tracks:
        artist = track.artist or record.artist
        if track.title_link and matches(reference, artist, track.title, EntityKind.TRACK):
            return urljoin(record.url, track.title_link)
    return None


def html_search(content: bytes) -> list[models.SearchResult]:
    """Read the results of the HTML search page, the fallback of the search endpoint."""
    result = []
    for position, item in enumerate(parse_html(content).css("li.searchresult")):
        kind = (text_of(item.css_first(".itemtype")) or "").lower()
        title = text_of(item.css_first(".heading a"))
        href = attribute(item.css_first(".itemurl a"), "href") or attribute(
            item.css_first(".heading a"),
            "href",
        )
        subhead = text_of(item.css_first(".subhead")) or ""
        artist = re.sub(r"^(?:from .+? )?by\s+", "", subhead, flags=re.IGNORECASE).strip()
        if kind not in {"album", "track"} or not title or not href:
            continue
        result.append(
            models.SearchResult(
                type=kind[0],
                id=position,
                name=title,
                band_name=artist or None,
                item_url_path=page_url(href),
            ),
        )
    return result


def same_name(left: str | None, right: str | None) -> bool:
    """Whether two account or label names are the same."""
    return bool(left and right) and normalize_artist(left or "") == normalize_artist(right or "")


def label_releases(
    content: bytes,
    base_url: str,
    label: str,
    exclude: int | None,
) -> list[Relation]:
    """Read other releases from the grid of a label's music page."""
    sources = [Provenance(source=SOURCE, url=base_url)]
    result = []
    for item in parse_html(content).css("li.music-grid-item"):
        item_id = attribute(item, "data-item-id") or ""
        kind, _, number = item_id.partition("-")
        href = attribute(item.css_first("a"), "href")
        title_node = item.css_first("p.title")
        override = item.css_first(".artist-override")
        artist = text_of(override)
        title = text_of(title_node)
        if title and artist and title.endswith(artist):
            title = title.removesuffix(artist).strip()
        if not title or not href or (exclude is not None and number == str(exclude)):
            continue
        ids = {IdKind.BANDCAMP_ALBUM: number} if kind == "album" and number else {}
        result.append(
            Relation(
                kind=RelationKind.LABEL_RELEASE,
                target=Entity(
                    type=EntityType.RELEASE,
                    name=title,
                    artist=artist or label,
                    url=urljoin(base_url, href),
                    ids=ids,
                ),
                note=label,
                scope=Scope.LABEL,
                sources=sources,
            ),
        )
        if len(result) >= LABEL_RELEASES_LIMIT:
            break
    return result
