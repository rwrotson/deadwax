from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationError

from deadwax.core import (
    CandidateLabel,
    EntityKind,
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
    Text,
    TextKind,
    normalize_text,
)
from deadwax.sources._base import SearchHit, track_on_release
from deadwax.sources._html import Document, Node, attribute, parse_html, text_of
from deadwax.sources.hardwax import models

SOURCE = "hardwax"
SERVICE = "hardwax"
SITE = "https://hardwax.com"
PUBLICATION = "Hard Wax"

# Store sections that sort by format or catalogue, not by genre.
NOT_GENRES = frozenset({"cds", "downloads", "label catalog", "merchandise"})


@dataclass(frozen=True, slots=True)
class Release:
    """What a product page says about a release."""

    artist: str
    title: str
    label: str | None
    catalog_number: str | None
    text: str | None
    sections: list[str]
    tracks: list[tuple[str, str]]


def page_url(url: str) -> str:
    """Product page without the format focus, which changes the page's description."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def split_name(name: str) -> tuple[str, str] | None:
    """Split Hard Wax's 'Artist: Title'."""
    artist, separator, title = name.partition(": ")
    artist, title = artist.strip(), title.strip()
    return (artist, title) if separator and artist and title else None


def feed_tracks(content_html: str, artist: str) -> list[tuple[str, str]]:
    """Artist and title of each tracklist entry of a feed item."""
    tracks = []
    for node in parse_html(content_html).css("ol > li"):
        entry = text_of(node)
        if entry is not None:
            tracks.append(split_name(entry) or (artist, entry))
    return tracks


def search_hits(content: bytes, url: str) -> list[SearchHit]:
    """Releases of the search feed, and each of their tracks."""
    try:
        feed = models.Feed.model_validate_json(content)
    except ValidationError:
        raise SourceError("the Hard Wax search feed is not valid JSON Feed", url=url) from None
    hits = []
    for item in feed.items:
        named = split_name(item.title)
        if named is None:
            continue
        artist, title = named
        target = page_url(item.url)
        hits.append(
            SearchHit(url=target, key=RecordKey(artist=artist, title=title, kind=EntityKind.ALBUM)),
        )
        hits.extend(
            SearchHit(url=target, key=RecordKey(artist=a, title=t, kind=EntityKind.TRACK))
            for a, t in feed_tracks(item.content_html, artist)
        )
    return hits


def _meta(document: Document, name: str) -> str | None:
    value = attribute(document.css_first(f'meta[property="{name}"]'), "content")
    return " ".join(value.split()) if value else None


def _catalog_number(label_link: Node | None) -> str | None:
    """The catalogue number is the release link next to the label link."""
    parent = label_link.parent if label_link is not None else None
    links = parent.css("a") if parent is not None else []
    return next(
        (
            text_of(link)
            for link in links
            if not (attribute(link, "href") or "").startswith("/label/")
        ),
        None,
    )


def _tracks(block: Node) -> list[tuple[str, str]]:
    """Tracks of every format on the page, each once."""
    tracks: dict[tuple[str, str], tuple[str, str]] = {}
    for link in block.css('[id^="track-"] a[title]'):
        named = split_name(attribute(link, "title") or "")
        if named is not None:
            tracks.setdefault((normalize_text(named[0]), normalize_text(named[1])), named)
    return list(tracks.values())


def release(content: bytes, url: str) -> Release:
    """Read a product page."""
    document = parse_html(content)
    block = document.css_first('[id^="record-"]')
    named = split_name(text_of(block.css_first("h2")) or "") if block is not None else None
    if block is None or named is None:
        raise SourceError("the Hard Wax page names no release", url=url)
    label_link = block.css_first('a[href^="/label/"]')
    sections = [text_of(link) for link in block.css('a[href^="/section/"]')]
    return Release(
        artist=named[0],
        title=named[1],
        label=text_of(label_link),
        catalog_number=_catalog_number(label_link),
        text=_meta(document, "og:description") or text_of(block.css_first("h2 + p")),
        sections=[s for s in dict.fromkeys(sections) if s and s.casefold() not in NOT_GENRES],
        tracks=_tracks(block),
    )


def page_partial(content: bytes, url: str, key: RecordKey | None) -> Partial:
    """Shop text, sections, and label of a release, for the release or one of its tracks."""
    url = page_url(url)
    record = release(content, url)
    provenance = Provenance(source=SOURCE, url=url)
    labels = [
        CandidateLabel(name=name, catalog_number=record.catalog_number)
        for name in [record.label]
        if name
    ]
    candidate = RecordCandidate(
        kind=EntityKind.ALBUM,
        artist=record.artist,
        title=record.title,
        labels=labels,
        url=url,
    )
    relations = []
    if key is not None and key.kind is EntityKind.TRACK:
        candidate, relation = track_on_release(candidate, record.tracks, key, provenance)
        relations.append(relation)
    texts = [
        Text(
            kind=TextKind.SHOP,
            body=body,
            publication=PUBLICATION,
            scope=Scope.RELEASE,
            sources=[provenance],
        )
        for body in [record.text]
        if body
    ]
    return Partial(
        source=SOURCE,
        candidate=candidate,
        tags=[
            Tag(name=section, kind=TagKind.GENRE, scope=Scope.RELEASE, sources=[provenance])
            for section in record.sections
        ],
        texts=texts,
        relations=relations,
        links=[Link(service=SERVICE, url=url, target=LinkTarget.ALBUM, sources=[provenance])],
    )
