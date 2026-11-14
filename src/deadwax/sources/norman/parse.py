from deadwax.core import (
    EntityKind,
    Link,
    LinkTarget,
    Partial,
    Provenance,
    RecordCandidate,
    Scope,
    SourceError,
    Tag,
    TagKind,
)
from deadwax.sources._html import attribute, parse_html, text_of

SOURCE = "norman"


def page_partial(content: bytes, url: str) -> Partial:
    """Read the release identity and genres from a complete product page."""
    document = parse_html(content)
    heading = document.css_first("h1")
    title = attribute(document.css_first('meta[property="og:title"]'), "content")
    if heading is None or not title or " - " not in title:
        raise SourceError("the Norman Records page names no release", url=url)
    artist, release = title.split(" - ", maxsplit=1)
    url = attribute(document.css_first('meta[property="og:url"]'), "content") or url
    provenance = Provenance(source=SOURCE, url=url)
    genres = {name for link in document.css('a[href^="/genre/"]') if (name := text_of(link))}
    return Partial(
        source=SOURCE,
        candidate=RecordCandidate(kind=EntityKind.ALBUM, artist=artist, title=release, url=url),
        tags=[
            Tag(name=name, kind=TagKind.GENRE, scope=Scope.RELEASE, sources=[provenance])
            for name in sorted(genres)
        ],
        links=[Link(service=SOURCE, url=url, target=LinkTarget.ALBUM, sources=[provenance])],
    )
