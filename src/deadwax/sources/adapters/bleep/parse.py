from datetime import datetime

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
)
from deadwax.sources._html import attribute, parse_html, text_of
from deadwax.sources._search import SearchHit, track_on_release

SOURCE = "bleep"


def search_hits(content: bytes) -> list[SearchHit]:
    """Read releases from Bleep search results."""
    hits = []
    for row in parse_html(content).css(".track-list .track"):
        artist = text_of(row.css_first(".main-track-artist"))
        title_link = row.css_first(".track-release a")
        title = text_of(title_link)
        href = attribute(title_link, "href")
        if artist and title and href:
            hits.append(
                SearchHit(
                    url=href,
                    key=RecordKey(artist=artist, title=title, kind=EntityKind.ALBUM),
                ),
            )
    return hits


def page_partial(content: bytes, url: str, key: RecordKey | None) -> Partial:
    """Read the editorial description of a Bleep release."""
    document = parse_html(content)
    page = document.css_first(".product-page.release")
    info = page.css_first(".product-info") if page is not None else None
    artist = text_of(info.css_first(".artist a")) if info is not None else None
    title = text_of(info.css_first(".release-title")) if info is not None else None
    if page is None or info is None or not artist or not title:
        raise SourceError("the Bleep page names no release", url=url)
    canonical = attribute(document.css_first('meta[property="og:url"]'), "content")
    url = canonical or url
    provenance = Provenance(source=SOURCE, url=url)
    fields = {}
    for term in info.css("dt"):
        definition = term.next
        while definition is not None and definition.tag != "dd":
            definition = definition.next
        if definition is not None:
            fields[(text_of(term) or "").casefold()] = text_of(definition)
    label = fields.get("label")
    try:
        date = datetime.strptime(fields.get("release date") or "", "%d %B %Y").date().isoformat()  # noqa: DTZ007 -- calendar date
    except ValueError:
        date = None
    candidate = RecordCandidate(
        kind=EntityKind.ALBUM,
        artist=artist,
        title=title,
        date=date,
        labels=[CandidateLabel(name=label, catalog_number=fields.get("catalogue number"))]
        if label
        else [],
        url=url,
    )
    relations = []
    if key is not None and key.kind is EntityKind.TRACK:
        tracks = [
            (artist, name)
            for node in page.css('.track-list .track [itemprop="name"]')
            if (name := text_of(node))
        ]
        candidate, relation = track_on_release(candidate, tracks, key, provenance)
        relations.append(relation)
    description = page.css_first(".product-description")
    paragraphs = [text_of(node) for node in description.css("p")] if description is not None else []
    body = "\n\n".join(text for text in paragraphs if text)
    genres = {
        name
        for section in document.css("#upsell-genre")
        if (name := text_of(section.css_first("h2 a")))
    }
    return Partial(
        source=SOURCE,
        candidate=candidate,
        texts=[
            Text(
                kind=TextKind.SHOP,
                body=body,
                publication="Bleep",
                scope=Scope.RELEASE,
                sources=[provenance],
            ),
        ]
        if body
        else [],
        tags=[
            Tag(name=name, kind=TagKind.GENRE, scope=Scope.RELEASE, sources=[provenance])
            for name in sorted(genres)
        ],
        relations=relations,
        links=[Link(service=SOURCE, url=url, target=LinkTarget.ALBUM, sources=[provenance])],
    )
