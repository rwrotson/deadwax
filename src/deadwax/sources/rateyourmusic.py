import re
from collections.abc import Mapping
from urllib.parse import urljoin, urlsplit

from deadwax.core import (
    Capability,
    Entity,
    EntityKind,
    EntityType,
    Metric,
    MetricKind,
    Partial,
    Pass,
    Provenance,
    RecordCandidate,
    RecordKey,
    Relation,
    RelationKind,
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

MAX_REVIEWS = 10


def _number(value: str) -> float | None:
    match = re.search(r"\d+(?:[.,]\d+)?", value.replace(",", ""))
    return float(match[0]) if match is not None else None


def _reviews(content: bytes, url: str, scope: Scope) -> list[Text]:
    """Read up to ten visible user reviews from a record page."""
    reviews = []
    for row in parse_html(content).css(".review, .user_review")[:MAX_REVIEWS]:
        body = text_of(row.css_first(".review_body, .review_text, .review_content"))
        if body:
            link = row.css_first("a[href*='/review/']")
            review_url = urljoin(url, attribute(link, "href") or url)
            reviews.append(
                Text(
                    kind=TextKind.USER,
                    body=body,
                    author=text_of(row.css_first(".review_author, .review_username")) or None,
                    scope=scope,
                    sources=[Provenance(source="rateyourmusic", url=review_url)],
                ),
            )
    return reviews


class RateYourMusicAdapter(SearchPageAdapter):
    """Read record metadata and community reviews from Rate Your Music."""

    name = "rateyourmusic"
    group = SourceGroup.CATALOGUES
    pass_ = Pass.ENRICH
    service = "rateyourmusic"
    capabilities = frozenset(
        {
            Capability.IDENTITY,
            Capability.TAGS,
            Capability.TEXTS,
            Capability.METRICS,
            Capability.RELATIONS,
        },
    )

    def search_request(self, key: RecordKey) -> tuple[str, Mapping[str, str]]:
        """Search releases or songs by artist and title."""
        return "https://rateyourmusic.com/search", {
            "searchterm": f"{key.artist} {key.title}",
            "searchtype": "s" if key.kind is EntityKind.TRACK else "l",
        }

    def search_hits(self, content: bytes, url: str) -> list[SearchHit]:  # noqa: ARG002 -- protocol
        """Read release and song links with their displayed identities."""
        page = parse_html(content)
        hits = []
        for row in page.css(".search_result, .searchresult, .search_results li"):
            link = row.css_first("a[href*='/release/'], a[href*='/song/']")
            href = attribute(link, "href")
            if href is None:
                continue
            artist = text_of(row.css_first(".search_artist, .artist, .search_result_artist"))
            title = text_of(
                row.css_first(".search_title, .release, .song, .search_result_title"),
            ) or text_of(link)
            if artist and title:
                kind = EntityKind.TRACK if "/song/" in href else EntityKind.ALBUM
                hits.append(
                    SearchHit(url=href, key=RecordKey(artist=artist, title=title, kind=kind)),
                )
        return hits

    def read_page(self, content: bytes, url: str, key: RecordKey | None) -> Partial:  # noqa: ARG002 -- protocol
        """Read the visible facts of a matched record page."""
        page = parse_html(content)
        title = text_of(page.css_first(".album_title, .song_title, .release_title, h1"))
        artist = text_of(
            page.css_first(
                ".album_artist a, .album_artist, .song_artist a, .song_artist, .release_artist a",
            ),
        )
        if not title or not artist:
            raise SourceError("the Rate Your Music page names no record", url=url)
        kind = EntityKind.TRACK if "/song/" in urlsplit(url).path else EntityKind.ALBUM
        scope = Scope.RECORDING if kind is EntityKind.TRACK else Scope.RELEASE_GROUP
        provenance = Provenance(source=self.name, url=url)
        tags: list[Tag] = []
        for selector, tag_kind in (
            (".release_pri_genres a, .primary_genres a", TagKind.GENRE),
            (".release_sec_genres a, .secondary_genres a", TagKind.SECONDARY_GENRE),
            (".release_descriptors a, .descriptors a", TagKind.DESCRIPTOR),
        ):
            tags.extend(
                Tag(name=name, kind=tag_kind, scope=scope, sources=[provenance])
                for node in page.css(selector)
                if (name := text_of(node))
            )
        metrics = []
        for selector, metric_kind, scale in (
            (".avg_rating, .rating_avg", MetricKind.USER_SCORE, 5.0),
            (".num_ratings, .rating_count", MetricKind.RATING_VOTES, None),
        ):
            node = page.css_first(selector)
            value = _number(text_of(node) or "") if node is not None else None
            if value is not None:
                metrics.append(
                    Metric(
                        kind=metric_kind,
                        value=value,
                        scale=scale,
                        scope=scope,
                        sources=[provenance],
                    ),
                )
        relations = []
        for row in page.css(".chart_peak a, .chart_position a"):
            chart_url = attribute(row, "href")
            label = text_of(row)
            if chart_url and label:
                relations.append(
                    Relation(
                        kind=RelationKind.CHARTED_IN,
                        target=Entity(
                            type=EntityType.CHART,
                            name=label,
                            url=urljoin(url, chart_url),
                        ),
                        note=label,
                        scope=scope,
                        sources=[provenance],
                    ),
                )
        return Partial(
            source=self.name,
            candidate=RecordCandidate(kind=kind, artist=artist, title=title, url=url),
            tags=tags,
            metrics=metrics,
            relations=relations,
            texts=_reviews(content, url, scope),
        )
