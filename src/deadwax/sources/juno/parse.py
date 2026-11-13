import re
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

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
from deadwax.sources._html import Node, attribute, parse_html, text_of

SOURCE = "juno"
SERVICE = "juno"
SITE = "https://www.juno.co.uk"
PUBLICATION = "Juno"

# Juno's name for a release without a label.
NO_LABEL = "unknown label"

# A tracklist entry: an optional artist, the quoted title, and a mix name after it.
_TRACK = re.compile(r'^(?:(?P<artist>.+?)\s+-\s+)?"(?P<title>.+)"\s*(?P<mix>.*)$')

# The length that search results print after a track's title, such as ' (3:58)'.
_LENGTH = re.compile(r"\s*\(\d+:\d{2}\)$")


def _first_text(nodes: list[Node]) -> str | None:
    return next((text for node in nodes if (text := text_of(node))), None)


def _prose(node: Node | None) -> str | None:
    """Text of a node without spaces added around inline markup."""
    return " ".join(node.text(deep=True).split()) or None if node is not None else None


def search_hits(content: bytes) -> list[SearchHit]:
    """Releases of a search page, and each of their tracks."""
    hits = []
    for item in parse_html(content).css(".product-list .dv-item"):
        artist = _first_text(item.css('strong a[href^="/artists/"]'))
        link = item.css_first('a.text-md[href^="/products/"]')
        title, href = text_of(link), attribute(link, "href")
        if not (artist and title and href):
            continue
        hits.append(
            SearchHit(url=href, key=RecordKey(artist=artist, title=title, kind=EntityKind.ALBUM)),
        )
        hits.extend(
            SearchHit(url=href, key=RecordKey(artist=artist, title=track, kind=EntityKind.TRACK))
            for track in (
                _LENGTH.sub("", text_of(node) or "")
                for node in item.css(".listing-track > div:last-child")
            )
            if track
        )
    return hits


def track_entry(text: str, artist: str) -> tuple[str, str]:
    """Artist and title of a tracklist entry such as '"Missing" (Todd Terry club mix)'."""
    match = _TRACK.match(text)
    if match is None:
        return artist, text
    title = f"{match['title']} {match['mix']}".strip()
    return (match["artist"] or artist).strip(), title


def _tracks(page: Node, artist: str) -> list[tuple[str, str]]:
    """Tracks of the page, each once: the mobile and desktop layouts repeat them."""
    tracks: dict[tuple[str, str], tuple[str, str]] = {}
    for row in page.css('#product-tracklist [itemprop="track"]'):
        text = text_of(row.css_first(".col"))
        if text:
            entry = track_entry(text, artist)
            tracks.setdefault((normalize_text(entry[0]), normalize_text(entry[1])), entry)
    return list(tracks.values())


def _facts(page: Node) -> dict[str, str]:
    """'Format', 'Cat', 'Released', and 'Genre' rows of the product page."""
    facts: dict[str, str] = {}
    for row in page.css(".product-meta > div.mb-1"):
        name, _, value = (text_of(row) or "").partition(":")
        if value.strip():
            facts.setdefault(name.strip().casefold(), value.strip())
    return facts


def _date(printed: str | None) -> str | None:
    """'02 Nov 07' as '2007-11-02'."""
    try:
        return datetime.strptime(printed or "", "%d %b %y").date().isoformat()  # noqa: DTZ007 -- a calendar date, no time
    except ValueError:
        return None


def page_url(content_url: str, canonical: str | None) -> str:
    """The product page's canonical URL, else the requested one without its query."""
    if canonical:
        return canonical
    parts = urlsplit(content_url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def page_partial(content: bytes, url: str, key: RecordKey | None) -> Partial:
    """Shop text, genre, tags, label, and date of a release or of one of its tracks."""
    document = parse_html(content)
    page = document.css_first("#product-page-music")
    artist = _first_text(page.css('[itemprop="byArtist"]')) if page is not None else None
    title = _first_text(page.css('.product-title [itemprop="name"]')) if page is not None else None
    if page is None or artist is None or title is None:
        raise SourceError("the Juno page names no release", url=url)
    url = page_url(url, attribute(document.css_first('link[rel="canonical"]'), "href"))
    provenance = Provenance(source=SOURCE, url=url)
    facts = _facts(page)
    label = _first_text(page.css(".product-label h2"))
    candidate = RecordCandidate(
        kind=EntityKind.ALBUM,
        artist=artist,
        title=title,
        date=_date(facts.get("released")),
        labels=[CandidateLabel(name=label, catalog_number=facts.get("cat"))]
        if label and label.casefold() != NO_LABEL
        else [],
        url=url,
    )
    relations = []
    if key is not None and key.kind is EntityKind.TRACK:
        candidate, relation = track_on_release(candidate, _tracks(page, artist), key, provenance)
        relations.append(relation)

    genre = attribute(page.css_first('meta[itemprop="genre"]'), "content") or facts.get("genre")
    named = [(genre, TagKind.GENRE)] + [
        (text_of(link), TagKind.TAG) for link in page.css(".juno-tags-tag a")
    ]
    tags: dict[str, Tag] = {}
    for name, kind in named:
        if name:
            tag = Tag(name=name, kind=kind, scope=Scope.RELEASE, sources=[provenance])
            tags.setdefault(normalize_text(name), tag)
    body = _prose(page.css_first('[itemprop="reviewBody"]'))
    return Partial(
        source=SOURCE,
        candidate=candidate,
        tags=list(tags.values()),
        texts=[
            Text(
                kind=TextKind.SHOP,
                body=text,
                publication=PUBLICATION,
                scope=Scope.RELEASE,
                sources=[provenance],
            )
            for text in [body]
            if text
        ],
        relations=relations,
        links=[Link(service=SERVICE, url=url, target=LinkTarget.ALBUM, sources=[provenance])],
    )
