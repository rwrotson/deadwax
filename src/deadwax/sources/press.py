import contextlib
import re
from urllib.parse import urlsplit

from deadwax.core import (
    Capability,
    EntityKind,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Provenance,
    Query,
    Rating,
    RecordCandidate,
    RecordKey,
    Scope,
    SourceGroup,
    Text,
    TextKind,
    Verdict,
    compare,
)
from deadwax.sources._base import HttpAdapter, search_key
from deadwax.sources._html import Document, attribute, parse_html, text_of
from deadwax.sources._http import Profile

_SITES = {
    "pitchfork.com": ("Pitchfork", ".body__inner-container p, .contents p, article p"),
    "thequietus.com": ("The Quietus", ".article-content p, .entry-content p, article p"),
    "thewire.co.uk": ("The Wire", ".article-body p, .entry-content p, article p"),
}


def _site(url: str) -> tuple[str, str] | None:
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
    return artist, title


def _review(content: bytes, url: str, key: RecordKey) -> tuple[RecordCandidate, Text] | None:
    site = _site(url)
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
    body = "\n\n".join(value for node in page.css(selector) if (value := text_of(node)))
    if not body:
        return None
    author = text_of(
        page.css_first("[rel='author'], [itemprop='author'], .byline a, [class*='author']"),
    )
    score = attribute(page.css_first("[itemprop='ratingValue']"), "content")
    rating = None
    if score:
        with contextlib.suppress(ValueError):
            rating = Rating(value=float(score), scale=10)
    return found, Text(
        kind=TextKind.REVIEW,
        body=body,
        author=author,
        publication=publication,
        rating=rating,
        scope=Scope.RELEASE_GROUP if key.kind is EntityKind.ALBUM else Scope.RECORDING,
        sources=[Provenance(source="pressreviews", url=url)],
    )


class PressAdapter(HttpAdapter):
    """Read reviews linked by earlier sources at three supported publications."""

    name = "pressreviews"
    group = SourceGroup.PRESS
    pass_ = Pass.LINKS
    profile = Profile.BROWSER
    capabilities = frozenset({Capability.TEXTS})

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Read linked reviews whose page identity matches the requested record."""
        key = search_key(query, context)
        if key is None:
            raise NotFoundError("no record identity for press reviews")
        links = [link.url for link in context.review_links if _site(link.url)]
        if not links:
            raise NotFoundError("no supported press review links")
        texts: list[Text] = []
        candidate = None
        for url in dict.fromkeys(links):
            response = await self.client.get(url)
            review = _review(response.content, response.url, key)
            if review is None:
                continue
            candidate, text = review
            texts.append(text)
        if not texts:
            raise NotFoundError("no matching accessible press reviews")
        return Partial(source=self.name, candidate=candidate, texts=texts)
