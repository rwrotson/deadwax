import contextlib
import json
import re
from urllib.parse import urlsplit

from deadwax.core import (
    EntityKind,
    Provenance,
    Rating,
    RecordCandidate,
    RecordKey,
    Scope,
    Text,
    TextKind,
    Verdict,
    compare,
)
from deadwax.sources._html import Document, attribute, parse_html, text_of

MAX_SCORE = 10

_SITES = {
    "pitchfork.com": ("Pitchfork", ".body__inner-container p, .contents p, article p"),
    "thequietus.com": ("The Quietus", ".article-content p, .entry-content p, article p"),
    "thewire.co.uk": ("The Wire", ".article-body p, .entry-content p, article p"),
}


def review_site(url: str) -> tuple[str, str] | None:
    """Publication name and text selector of a supported review site."""
    host = (urlsplit(url).hostname or "").lower()
    return next(
        (site for domain, site in _SITES.items() if host == domain or host.endswith(f".{domain}")),
        None,
    )


def _identity(page: Document, publication: str) -> tuple[str | None, str | None]:
    title = text_of(page.css_first("[itemprop='name'], h1"))
    artist = text_of(page.css_first("[itemprop='byArtist'], .artist-links, .artist"))
    if publication == "Pitchfork":
        artist = text_of(page.css_first("[class*='ContentHeaderArtistWrapper']")) or artist
    elif publication == "The Quietus" and title:
        match = re.search(r"([^:]+?)[\u2019']s (.+)$", title)
        if match is not None:
            artist = match[1].strip()
            title = match[2].strip()
    elif publication == "The Wire":
        record = page.css_first(".article .body p")
        if record is not None:
            artist = text_of(record.css_first("strong"))
            title = text_of(record.css_first("em"))
    return artist, title


def _body(page: Document, publication: str, selector: str) -> str:
    if publication == "The Wire":
        paragraphs = []
        for node in page.css(".article .body p")[1:]:
            if node.css_first("strong") is not None and node.css_first("em") is not None:
                break
            value = text_of(node)
            if value and not value.startswith("This review appears in The Wire"):
                paragraphs.append(value)
        return "\n\n".join(paragraphs)
    return "\n\n".join(value for node in page.css(selector) if (value := text_of(node)))


def _rating(page: Document, publication: str) -> Rating | None:
    if publication == "Pitchfork":
        for script in page.css("script"):
            state = script.text().partition("window.__PRELOADED_STATE__ = ")
            if not state[1]:
                continue
            with contextlib.suppress(ValueError, KeyError, TypeError):
                data = json.loads(state[2].removesuffix(";"))
                value = data["transformed"]["review"]["headerProps"]["musicRating"]["score"]
                if isinstance(value, (int, float)) and 0 <= value <= MAX_SCORE:
                    return Rating(value=float(value), scale=MAX_SCORE)
    score = attribute(page.css_first("[itemprop='ratingValue']"), "content")
    if score:
        with contextlib.suppress(ValueError):
            return Rating(value=float(score), scale=MAX_SCORE)
    return None


def review(content: bytes, url: str, key: RecordKey) -> tuple[RecordCandidate, Text] | None:
    """Read the reviewed record and the review text of a press page."""
    site = review_site(url)
    if site is None:
        return None
    publication, selector = site
    page = parse_html(content)
    artist, title = _identity(page, publication)
    if not title or not artist:
        return None
    found = RecordCandidate(kind=key.kind, artist=artist, title=title, url=url)
    found_key = RecordKey(artist=artist, title=title, kind=key.kind)
    if compare(key, found_key).verdict is not Verdict.MATCH:
        return None
    body = _body(page, publication, selector)
    if not body:
        return None
    author = text_of(
        page.css_first(
            "[rel='author'], [itemprop='author'], .byline a, "
            "[class*='author'], .contributor-bylines a",
        ),
    )
    return found, Text(
        kind=TextKind.REVIEW,
        body=body,
        author=author,
        publication=publication,
        rating=_rating(page, publication),
        scope=Scope.RELEASE_GROUP if key.kind is EntityKind.ALBUM else Scope.RECORDING,
        sources=[Provenance(source="pressreviews", url=url)],
    )
