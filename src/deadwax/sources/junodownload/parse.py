import re

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
    Verdict,
    compare,
)
from deadwax.sources._base import SearchHit
from deadwax.sources._html import Document, Node, attribute, parse_html, text_of
from deadwax.sources.junodownload import models

SOURCE = "junodownload"
SERVICE = "junodownload"
SITE = "https://www.junodownload.com"

_MONTHS = {
    month: number
    for number, month in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}

# Release dates are printed as '05 Nov, 2007'.
_DATE = re.compile(r"^(\d{1,2})\s+([A-Za-z]{3})[a-z]*,?\s+(\d{4})$")

# Tempos dance stores list; anything else in a BPM cell is not a tempo.
_BPM = re.compile(r"^(\d{2,3}(?:\.\d+)?)(?:\s*bpm)?$", re.IGNORECASE)
_MIN_BPM, _MAX_BPM = 40.0, 250.0


def page_date(text: str | None) -> str | None:
    """ISO date of a printed release date."""
    match = _DATE.match(text or "")
    if match is None or match[2].lower() not in _MONTHS:
        return None
    return f"{match[3]}-{_MONTHS[match[2].lower()]:02d}-{int(match[1]):02d}"


def bpm(text: str | None) -> float | None:
    """Tempo of a tracklist cell, if it holds a plausible one."""
    match = _BPM.match(text or "")
    if match is None:
        return None
    value = float(match[1])
    return value if _MIN_BPM <= value <= _MAX_BPM else None


def _names(nodes: list[Node]) -> str | None:
    names = [name for node in nodes if (name := text_of(node))]
    # Joined the way the matching gate splits collaborations.
    return " & ".join(dict.fromkeys(names)) or None


def _first_text(root: Document | Node, *selectors: str) -> str | None:
    for selector in selectors:
        if (text := text_of(root.css_first(selector))) is not None:
            return text
    return None


def labelled_values(document: Document) -> dict[str, list[str]]:
    """Read 'Label: value' pairs of the product details, where each label is a bold node."""
    values: dict[str, list[str]] = {}
    for strong in document.css(".product-meta strong, .product-meta b"):
        label = (text_of(strong) or "").rstrip(":").strip().casefold()
        parts: list[str] = []
        node = strong.next
        while node is not None and node.tag not in {"strong", "b", "br"}:
            if (text := text_of(node)) is not None:
                parts.append(text)
            node = node.next
        links = [text for text in parts if text]
        if label and links:
            values.setdefault(label, []).extend(links)
    return values


def _track(row: Node) -> models.Track | None:
    title = _first_text(row, '[itemprop="name"]', ".juno-title", ".track-title")
    if title is None:
        return None
    return models.Track(
        title=title,
        artist=_names(row.css('[itemprop="byArtist"], .juno-artist')),
        bpm=bpm(_first_text(row, '[class*="bpm"]')),
    )


def release(content: bytes, url: str) -> models.Release:
    """Read a release page."""
    document = parse_html(content)
    title = _first_text(document, "h1.product-title", '[itemprop="album"] [itemprop="name"]', "h1")
    artist = _names(document.css(".product-artist a")) or _first_text(document, ".product-artist")
    if title is None or artist is None:
        raise SourceError("the Juno Download page names no release", url=url)

    details = labelled_values(document)
    rows = document.css('.product-tracklist [itemprop="track"], .product-tracklist-track')
    tracks = [track for row in rows if (track := _track(row)) is not None]
    return models.Release(
        artist=artist,
        title=title,
        label=next(iter(details.get("label", [])), None),
        catalog_number=next(iter(details.get("cat", [])), None),
        date=page_date(next(iter(details.get("released", [])), None)),
        genres=list(dict.fromkeys(details.get("genre", []))),
        tracks=list(dict.fromkeys(tracks)),
    )


def listings(content: bytes) -> list[models.Listing]:
    """Read the releases of a search page."""
    found = []
    for item in parse_html(content).css(".jd-listing-item"):
        link = item.css_first("a.juno-title")
        href = attribute(link, "href")
        title = text_of(link)
        artist = _names(item.css(".juno-artist"))
        if href is None or title is None or artist is None:
            continue
        tracks = [
            models.Track(title=name)
            for node in item.css(".jd-listing-tracklist .juno-track")
            if (name := text_of(node)) is not None
        ]
        found.append(models.Listing(url=href, artist=artist, title=title, tracks=tracks))
    return found


def hits(content: bytes) -> list[SearchHit]:
    """Search hits: each release, and each of its tracks pointing at the release page."""
    found = []
    for listing in listings(content):
        found.append(
            SearchHit(listing.url, RecordKey(listing.artist, listing.title, EntityKind.ALBUM)),
        )
        found += [
            SearchHit(listing.url, RecordKey(listing.artist, track.title, EntityKind.TRACK))
            for track in listing.tracks
        ]
    return found


def find_track(page: models.Release, key: RecordKey) -> models.Track | None:
    """The tracklist row of the record, else the first row of another version of it."""
    other_version = None
    for track in page.tracks:
        row = RecordKey(track.artist or page.artist, track.title, EntityKind.TRACK)
        verdict = compare(key, row).verdict
        if verdict is Verdict.MATCH:
            return track
        if verdict is Verdict.OTHER_VERSION and other_version is None:
            other_version = track
    return other_version


def _common(page: models.Release, url: str) -> tuple[list[CandidateLabel], Partial]:
    provenance = Provenance(source=SOURCE, url=url)
    labels = (
        [CandidateLabel(name=page.label, catalog_number=page.catalog_number)] if page.label else []
    )
    facts = Partial(
        source=SOURCE,
        tags=[
            Tag(name=genre, kind=TagKind.GENRE, scope=Scope.RELEASE, sources=[provenance])
            for genre in page.genres
        ],
        links=[Link(service=SERVICE, url=url, target=LinkTarget.ALBUM, sources=[provenance])],
    )
    return labels, facts


def album_partial(page: models.Release, url: str) -> Partial:
    """The release as an album."""
    labels, facts = _common(page, url)
    candidate = RecordCandidate(
        kind=EntityKind.ALBUM,
        artist=page.artist,
        title=page.title,
        date=page.date,
        labels=labels,
        url=url,
    )
    return facts.model_copy(update={"candidate": candidate})


def track_partial(page: models.Release, track: models.Track, url: str) -> Partial:
    """One track of the release, with its tempo and the release's label and genres."""
    labels, facts = _common(page, url)
    candidate = RecordCandidate(
        kind=EntityKind.TRACK,
        artist=track.artist or page.artist,
        title=track.title,
        date=page.date,
        bpm=track.bpm,
        labels=labels,
        url=url,
    )
    return facts.model_copy(update={"candidate": candidate})
