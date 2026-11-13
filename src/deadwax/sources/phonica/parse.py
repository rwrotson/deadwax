import re
from typing import NamedTuple

from deadwax.core import (
    CandidateLabel,
    Entity,
    EntityKind,
    EntityType,
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
    Text,
    TextKind,
    normalize_text,
)
from deadwax.sources._base import SearchHit, track_on_release
from deadwax.sources._html import Node, attribute, parse_html, text_of

SOURCE = "phonica"
SERVICE = "phonica"
SITE = "https://www.phonicarecords.com"
PUBLICATION = "Phonica"

# The format Phonica appends to some titles, such as 'Colonial Patterns LP' or 'Antidawn CD'.
_FORMAT = re.compile(r"\s+(?:\d\s*x\s*)?\d?(?:LP|CD)$", re.IGNORECASE)

# Paragraph breaks of a description written without <p> elements.
_BREAKS = re.compile(r"(?:<br\s*/?>\s*){2,}", re.IGNORECASE)


def release_title(printed: str) -> str:
    """A product title without the format Phonica appends to it."""
    return _FORMAT.sub("", printed).strip() or printed


class _Product(NamedTuple):
    artist: str
    title: str
    url: str
    tracks: list[str]


def _products(nodes: list[Node]) -> list[_Product]:
    """Filled product cards; empty cards are page templates."""
    products = []
    for node in nodes:
        artist = text_of(node.css_first(".archive-artist"))
        title = text_of(node.css_first(".archive-title"))
        href = attribute(node.css_first("a.archive-product-link"), "href")
        if artist and title and href:
            tracks = [
                name for track in node.css(".archive-playlist span") if (name := text_of(track))
            ]
            products.append(_Product(artist, release_title(title), href, tracks))
    return products


def search_hits(content: bytes) -> list[SearchHit]:
    """Releases of a search page, and each of their tracks."""
    hits = []
    for product in _products(parse_html(content).css(".archive-products .product-place-holder")):
        hits.append(
            SearchHit(
                url=product.url,
                key=RecordKey(artist=product.artist, title=product.title, kind=EntityKind.ALBUM),
            ),
        )
        hits.extend(
            SearchHit(
                url=product.url,
                key=RecordKey(artist=product.artist, title=track, kind=EntityKind.TRACK),
            )
            for track in product.tracks
        )
    return hits


def _prose(node: Node) -> str:
    """Text of a node without spaces added around inline markup."""
    return " ".join(node.text(deep=True).split())


def _description(page: Node) -> str | None:
    """The shop text, its paragraphs kept apart."""
    node = page.css_first(".single-description")
    if node is None:
        return None
    paragraphs = [_prose(p) for p in node.css("p")] or [
        _prose(parse_html(chunk).body or node) for chunk in _BREAKS.split(node.html or "")
    ]
    return "\n\n".join(text for text in paragraphs if text) or None


def _also_bought(page: Node, provenance: Provenance) -> list[Relation]:
    """Releases that customers who bought this one also bought."""
    return [
        Relation(
            kind=RelationKind.SIMILAR,
            scope=Scope.RELEASE,
            target=Entity(
                type=EntityType.RELEASE,
                name=product.title,
                artist=product.artist,
                url=product.url,
            ),
            note="customers who bought this also bought",
            sources=[provenance],
        )
        for product in _products(page.css("#archive-grid-view-bought .product-place-holder"))
    ]


def page_partial(content: bytes, url: str, key: RecordKey | None) -> Partial:
    """Shop text, genres, label, and similar releases of a release or of one of its tracks."""
    document = parse_html(content)
    page = document.css_first("#page-single")
    artist = text_of(page.css_first(".single-artist")) if page is not None else None
    title = text_of(page.css_first(".single-title")) if page is not None else None
    if page is None or artist is None or title is None:
        raise SourceError("the Phonica page names no release", url=url)
    url = attribute(document.css_first('meta[property="og:url"]'), "content") or url
    provenance = Provenance(source=SOURCE, url=url)
    label = text_of(page.css_first(".single-label"))
    candidate = RecordCandidate(
        kind=EntityKind.ALBUM,
        artist=artist,
        title=release_title(title),
        labels=[CandidateLabel(name=label)] if label else [],
        url=url,
    )
    relations = _also_bought(page, provenance)
    if key is not None and key.kind is EntityKind.TRACK:
        tracks = [
            (artist, name) for node in page.css("#playlist td.trackname") if (name := text_of(node))
        ]
        candidate, relation = track_on_release(candidate, tracks, key, provenance)
        relations.insert(0, relation)

    tags: dict[str, Tag] = {}
    for node in page.css(".single-alerts-genre a"):
        if name := text_of(node):
            tag = Tag(name=name, kind=TagKind.GENRE, scope=Scope.RELEASE, sources=[provenance])
            tags.setdefault(normalize_text(name), tag)
    body = _description(page)
    return Partial(
        source=SOURCE,
        candidate=candidate,
        tags=list(tags.values()),
        texts=[
            Text(
                kind=TextKind.SHOP,
                body=body,
                publication=PUBLICATION,
                scope=Scope.RELEASE,
                sources=[provenance],
            ),
        ]
        if body
        else [],
        relations=relations,
        links=[Link(service=SERVICE, url=url, target=LinkTarget.ALBUM, sources=[provenance])],
    )
