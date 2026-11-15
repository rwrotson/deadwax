from collections.abc import Mapping
from urllib.parse import urljoin, urlsplit

from deadwax.core import (
    Capability,
    EntityKind,
    Metric,
    MetricKind,
    Partial,
    Pass,
    Provenance,
    Rating,
    RecordCandidate,
    RecordKey,
    ReviewLink,
    Scope,
    SourceError,
    SourceGroup,
    Tag,
    TagKind,
    Text,
    TextKind,
)
from deadwax.sources._base import SearchHit, SearchPageAdapter
from deadwax.sources._html import attribute, parse_html, text_of

MAX_SCORE = 100


def _score(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        score = float(value.strip().split()[0])
    except ValueError:
        return None
    return score if 0 <= score <= MAX_SCORE else None


class AlbumOfTheYearAdapter(SearchPageAdapter):
    """Critic scores, user score, genres, and review links from Album of the Year."""

    name = "albumoftheyear"
    group = SourceGroup.CATALOGUES
    pass_ = Pass.ENRICH
    service = "albumoftheyear"
    capabilities = frozenset(
        {Capability.IDENTITY, Capability.TEXTS, Capability.TAGS, Capability.METRICS},
    )

    def search_request(self, key: RecordKey) -> tuple[str, Mapping[str, str]]:
        """Search Album of the Year for an album."""
        return "https://www.albumoftheyear.org/search/", {
            "q": f"{key.artist} {key.title}",
        }

    def search_hits(self, content: bytes, url: str) -> list[SearchHit]:  # noqa: ARG002 -- protocol
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

    def read_page(self, content: bytes, url: str, key: RecordKey | None) -> Partial:  # noqa: ARG002 -- protocol
        """Read the album and its scores."""
        page = parse_html(content)
        title = text_of(page.css_first("h1.albumTitle, h1"))
        artist = text_of(page.css_first(".albumHeadline .artist a")) or text_of(
            page.css_first(".artistTitle a, .artistTitle, .albumArtist a"),
        )
        if not title or not artist:
            raise SourceError("the Album of the Year page names no album", url=url)
        provenance = Provenance(source=self.name, url=url)
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
        return Partial(
            source=self.name,
            candidate=RecordCandidate(kind=EntityKind.ALBUM, artist=artist, title=title, url=url),
            tags=genres,
            texts=reviews,
            metrics=metrics,
            review_links=links,
        )
