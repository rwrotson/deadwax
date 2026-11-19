from urllib.parse import urljoin, urlsplit

from deadwax.core import (
    EntityKind,
    Metric,
    MetricKind,
    Partial,
    Provenance,
    Rating,
    RecordCandidate,
    RecordKey,
    ReviewLink,
    Scope,
    SourceError,
    Tag,
    TagKind,
    Text,
    TextKind,
)
from deadwax.sources._html import attribute, parse_html, text_of
from deadwax.sources._search import SearchHit, track_on_release

SOURCE = "albumoftheyear"
MAX_SCORE = 100


def _score(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        score = float(value.strip().split()[0])
    except ValueError:
        return None
    return score if 0 <= score <= MAX_SCORE else None


def search_hits(content: bytes) -> list[SearchHit]:
    """Read album results."""
    page = parse_html(content)
    hits = []
    for row in page.css(".albumBlock, .searchResult, .album-result"):
        link = row.css_first("a[href*='/album/']")
        title = text_of(row.css_first(".albumTitle, .title")) or text_of(link)
        artist = text_of(row.css_first(".artistTitle, .artist"))
        href = attribute(link, "href")
        if title and artist and href:
            hits.append(
                SearchHit(
                    url=href,
                    key=RecordKey(artist=artist, title=title, kind=EntityKind.ALBUM),
                ),
            )
    return hits


def page_partial(content: bytes, url: str, key: RecordKey | None) -> Partial:
    """Read the release and its scores; for a track, only a release that lists it."""
    page = parse_html(content)
    title = text_of(page.css_first("h1.albumTitle, h1"))
    artist = text_of(page.css_first(".albumHeadline .artist a")) or text_of(
        page.css_first(".artistTitle a, .artistTitle, .albumArtist a"),
    )
    if not title or not artist:
        raise SourceError("the Album of the Year page names no album", url=url)
    provenance = Provenance(source=SOURCE, url=url)
    scope = Scope.RELEASE_GROUP
    reviews = []
    links = []
    for row in page.css(".albumReviewRow, .criticReview, .critic-review, .reviewBlock"):
        publication = text_of(row.css_first(".publication, .source, .reviewSource"))
        score = _score(text_of(row.css_first(".albumReviewRating, .score, .rating")))
        if not publication or score is None:
            continue
        reviews.append(
            Text(
                kind=TextKind.REVIEW,
                body="",
                publication=publication,
                rating=Rating(value=score, scale=100),
                scope=scope,
                sources=[provenance],
            ),
        )
        link = row.css_first(".albumReviewLinks a[href]") or row.css_first("a[href]")
        href = attribute(link, "href")
        if href:
            target = urljoin(url, href)
            if urlsplit(target).hostname != urlsplit(url).hostname:
                links.append(
                    ReviewLink(publication=publication, url=target, sources=[provenance]),
                )
    genres = [
        Tag(name=name, kind=TagKind.GENRE, scope=scope, sources=[provenance])
        for node in page.css(
            "#centerContent .detailRow a[href^='/genre/'], .genre a, .genres a",
        )
        if (name := text_of(node))
    ]
    user_score = _score(text_of(page.css_first(".albumUserScore a, .userScore, .user-score")))
    metrics = (
        [
            Metric(
                kind=MetricKind.USER_SCORE,
                value=user_score,
                scale=MAX_SCORE,
                scope=scope,
                sources=[provenance],
            ),
        ]
        if user_score is not None
        else []
    )
    candidate = RecordCandidate(kind=EntityKind.ALBUM, artist=artist, title=title, url=url)
    relations = []
    if key is not None and key.kind is EntityKind.TRACK:
        tracks = [
            (artist, name)
            for node in page.css("#tracklist .trackList li, .trackListTable .trackTitle")
            if (name := text_of(node))
        ]
        candidate, relation = track_on_release(candidate, tracks, key, provenance)
        relations.append(relation)
    return Partial(
        source=SOURCE,
        candidate=candidate,
        tags=genres,
        texts=reviews,
        metrics=metrics,
        review_links=links,
        relations=relations,
    )
