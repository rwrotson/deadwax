from datetime import datetime

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
)
from deadwax.sources._base import SearchHit
from deadwax.sources._html import attribute, parse_html, text_of

SOURCE = "forcedexposure"


def search_hits(content: bytes) -> list[SearchHit]:
    """Read product rows of Forced Exposure search results."""
    hits = []
    for row in parse_html(content).css("#search_results tr.search_resultfields"):
        artist = text_of(row.css_first("td.artist a"))
        link = row.css_first('a[title="View Product Details"]')
        title, href = text_of(link), attribute(link, "href")
        if artist and title and href:
            hits.append(
                SearchHit(
                    url=href,
                    key=RecordKey(artist=artist, title=title, kind=EntityKind.ALBUM),
                ),
            )
    return hits


def page_partial(content: bytes, url: str) -> Partial:
    """Read label copy and release metadata from a product page."""
    document = parse_html(content)
    info = document.css_first(".product-right")
    artist = text_of(info.css_first(".meta-value.artist")) if info is not None else None
    title = text_of(info.css_first(".meta-value.title")) if info is not None else None
    if info is None or not artist or not title:
        raise SourceError("the Forced Exposure page names no release", url=url)
    fields = {
        (text_of(name) or "").casefold(): text_of(value)
        for name, value in zip(info.css(".meta-label"), info.css(".meta-value"), strict=False)
    }
    label = fields.get("label")
    catalog = fields.get("catalog #")
    genre = fields.get("genre")
    printed_date = fields.get("release date")
    try:
        date = datetime.strptime(printed_date or "", "%m/%d/%Y").date().isoformat()  # noqa: DTZ007 -- calendar date
    except ValueError:
        date = None
    url = attribute(document.css_first('link[rel="canonical"]'), "href") or url
    provenance = Provenance(source=SOURCE, url=url)
    candidate = RecordCandidate(
        kind=EntityKind.ALBUM,
        artist=artist,
        title=title,
        date=date,
        labels=[CandidateLabel(name=label, catalog_number=catalog)] if label else [],
        url=url,
    )
    body = text_of(info.css_first(".prod-desc"))
    relations = []
    for link in document.css('.recommended .product_image a[href^="/Catalog/"]'):
        image = link.css_first("img")
        name = attribute(image, "alt")
        href = attribute(link, "href")
        if name and href and ": " in name:
            related_artist, related_title = name.split(": ", 1)
            relations.append(
                Relation(
                    kind=RelationKind.SIMILAR,
                    scope=Scope.RELEASE,
                    target=Entity(
                        type=EntityType.RELEASE,
                        name=related_title,
                        artist=related_artist,
                        url="https://www.forcedexposure.com" + href,
                    ),
                    sources=[provenance],
                ),
            )
    return Partial(
        source=SOURCE,
        candidate=candidate,
        tags=[Tag(name=genre, kind=TagKind.GENRE, scope=Scope.RELEASE, sources=[provenance])]
        if genre
        else [],
        texts=[
            Text(
                kind=TextKind.LABEL,
                body=body,
                publication="Forced Exposure",
                scope=Scope.RELEASE,
                sources=[provenance],
            ),
        ]
        if body
        else [],
        relations=relations,
        links=[Link(service=SOURCE, url=url, target=LinkTarget.ALBUM, sources=[provenance])],
    )
