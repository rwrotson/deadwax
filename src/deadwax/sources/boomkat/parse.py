import re

from deadwax.core import (
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
from deadwax.sources._base import SearchHit
from deadwax.sources._html import attribute, parse_html, text_of

SOURCE = "boomkat"
_RESULT = re.compile(r'^View "(?P<title>.+)" by (?P<artist>.+)$')


def search_hits(content: bytes) -> list[SearchHit]:
    """Read release links with their title and artist."""
    hits = []
    for link in parse_html(content).css('a[title^="View "][href*="/releases/"]'):
        label = attribute(link, "title") or ""
        match = _RESULT.match(label)
        href = attribute(link, "href")
        if match is not None and href is not None:
            hits.append(
                SearchHit(
                    url=href,
                    key=RecordKey(
                        artist=match["artist"],
                        title=match["title"],
                        kind=EntityKind.ALBUM,
                    ),
                ),
            )
    return hits


def page_partial(content: bytes, url: str) -> Partial:
    """Read a Boomkat release without treating recommendations as its facts."""
    document = parse_html(content)
    review = document.css_first(".release-review-content")
    title = text_of(document.css_first("h2.text-xl"))
    artist = text_of(document.css_first("h1.text-2xl"))
    if not artist or not title:
        raise SourceError("the Boomkat page names no release", url=url)
    url = attribute(document.css_first('meta[property="og:url"]'), "content") or url
    provenance = Provenance(source=SOURCE, url=url)
    body = text_of(review)
    genres = {name for link in document.css('a[href^="/genres/"]') if (name := text_of(link))}
    return Partial(
        source=SOURCE,
        candidate=RecordCandidate(kind=EntityKind.ALBUM, artist=artist, title=title, url=url),
        texts=[
            Text(
                kind=TextKind.SHOP,
                body=body,
                publication="Boomkat",
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
        links=[Link(service=SOURCE, url=url, target=LinkTarget.ALBUM, sources=[provenance])],
    )
