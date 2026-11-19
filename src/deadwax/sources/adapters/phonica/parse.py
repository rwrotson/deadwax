import json
import re
from typing import NamedTuple
from urllib.parse import quote

from pydantic import ValidationError

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
    parse_title,
)
from deadwax.sources._html import Node, attribute, parse_html, prose, text_of
from deadwax.sources._search import SearchHit, track_on_release
from deadwax.sources.adapters.phonica import models

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


def _products(nodes: list[Node]) -> list[_Product]:
    """Filled product cards; empty cards are page templates."""
    products = []
    for node in nodes:
        artist = text_of(node.css_first(".archive-artist"))
        title = text_of(node.css_first(".archive-title"))
        href = attribute(node.css_first("a.archive-product-link"), "href")
        if artist and title and href:
            products.append(_Product(artist, release_title(title), href))
    return products


def _unshortened(text: str) -> str:
    """Text without the '...' that ends names the search API shortens."""
    return text.removesuffix("...").rstrip() or text


def search_term(title: str) -> str:
    """Words the site's search can find of a title: its base before any ' / ' of a split."""
    return parse_title(title).base.split(" / ", maxsplit=1)[0].strip() or title


def search_url(term: str) -> str:
    """URL of the search API for one term; the site matches the term within a single field."""
    return f"{SITE}/api/product/json_category_search/{quote(term, safe='')}/0"


def search_form(term: str) -> dict[str, str]:
    """Form the site's own search sends with a request."""
    return {"id": "0", "href": f"/search/{term}/", "offset": "0"}


def _search_products(content: bytes, url: str) -> list[models.Product]:
    try:
        page = json.loads(content)
    except ValueError:
        raise SourceError("the Phonica search answered without JSON", url=url) from None
    products = []
    for name, value in page.items() if isinstance(page, dict) else []:
        if name.isdigit():
            try:
                products.append(models.Product.model_validate(value))
            except ValidationError:
                continue
    return products


def search_hits(content: bytes, url: str) -> list[SearchHit]:
    """Releases of a search API answer, and each of their tracks."""
    hits = []
    for product in _search_products(content, url):
        href = f"{SITE}/{product.slug.lstrip('/')}"
        artist = _unshortened(product.artist)
        title = release_title(_unshortened(product.album))
        hits.append(
            SearchHit(url=href, key=RecordKey(artist=artist, title=title, kind=EntityKind.ALBUM)),
        )
        hits.extend(
            SearchHit(url=href, key=RecordKey(artist=artist, title=name, kind=EntityKind.TRACK))
            for track in product.product_playlist
            if (name := " ".join((track.trackname or "").split()))
        )
    return hits


def _description(page: Node) -> str | None:
    """The shop text, its paragraphs kept apart."""
    node = page.css_first(".single-description")
    if node is None:
        return None
    paragraphs = [prose(p) for p in node.css("p")] or [
        prose(parse_html(chunk).body or node) for chunk in _BREAKS.split(node.html or "")
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
