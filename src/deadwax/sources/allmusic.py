import contextlib
from collections.abc import Mapping
from urllib.parse import quote, urlsplit

from deadwax.core import (
    Capability,
    Credit,
    Entity,
    EntityKind,
    EntityType,
    Partial,
    Pass,
    Provenance,
    Rating,
    RecordCandidate,
    RecordKey,
    Relation,
    RelationKind,
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


class AllMusicAdapter(SearchPageAdapter):
    """Reviews, credits, styles, moods, themes, and similar albums from AllMusic."""

    name = "allmusic"
    group = SourceGroup.PRESS
    pass_ = Pass.ENRICH
    service = "allmusic"
    capabilities = frozenset(
        {
            Capability.IDENTITY,
            Capability.TEXTS,
            Capability.TAGS,
            Capability.CREDITS,
            Capability.RELATIONS,
        },
    )

    def search_request(self, key: RecordKey) -> tuple[str, Mapping[str, str]]:
        """Search AllMusic for an album or song."""
        kind = "albums" if key.kind is EntityKind.ALBUM else "songs"
        return f"https://www.allmusic.com/search/{kind}/{quote(key.title)}", {}

    def search_hits(self, content: bytes, url: str) -> list[SearchHit]:
        """Read matching records in search results."""
        page = parse_html(content)
        kind = EntityKind.TRACK if "/songs/" in urlsplit(url).path else EntityKind.ALBUM
        found = []
        for row in page.css(".search-results li, .search-results .result"):
            link = row.css_first("a.title, .title a, h4 a")
            title = text_of(link)
            artist = text_of(row.css_first(".artist, .artists"))
            href = attribute(link, "href")
            if title and artist and href:
                found.append(
                    SearchHit(
                        url=href,
                        key=RecordKey(artist=artist, title=title, kind=kind),
                    ),
                )
        return found

    def read_page(self, content: bytes, url: str, key: RecordKey | None) -> Partial:
        """Read the record's AllMusic page."""
        page = parse_html(content)
        title = text_of(page.css_first("h1.album-title, h1.song-title, h1"))
        artist = text_of(page.css_first(".album-artist, .song-artist, .artist-name"))
        if not title or not artist:
            raise SourceError("the AllMusic page names no record", url=url)
        scope = (
            Scope.RELEASE_GROUP if key is None or key.kind is EntityKind.ALBUM else Scope.RECORDING
        )
        kind = EntityKind.TRACK if scope is Scope.RECORDING else EntityKind.ALBUM
        provenance = Provenance(source=self.name, url=url)
        review = page.css_first(".review, .album-review, .song-review")
        paragraphs = review.css("p") if review is not None else []
        body = "\n\n".join(value for node in paragraphs if (value := text_of(node)))
        critic = text_of(page.css_first(".review .author, .review-author, .review-byline"))
        score_node = page.css_first(".allmusic-rating, .rating-allmusic")
        score = attribute(score_node, "data-rating") or attribute(score_node, "aria-label")
        rating = None
        if score:
            with contextlib.suppress(ValueError):
                rating = Rating(value=float(score.split()[0]), scale=5)
        texts = (
            [
                Text(
                    kind=TextKind.REVIEW,
                    body=body,
                    author=critic,
                    publication="AllMusic",
                    rating=rating,
                    scope=scope,
                    sources=[provenance],
                ),
            ]
            if body or rating
            else []
        )
        tags: list[Tag] = []
        for selector, tag_kind in (
            (".styles a", TagKind.STYLE),
            (".moods a", TagKind.MOOD),
            (".themes a", TagKind.THEME),
        ):
            tags.extend(
                Tag(name=name, kind=tag_kind, scope=scope, sources=[provenance])
                for node in page.css(selector)
                if (name := text_of(node))
            )
        people = [
            Credit(role=role, name=name, scope=scope, sources=[provenance])
            for row in page.css(".credits .credit, .credits tr")
            if (name := text_of(row.css_first(".name, td:first-child")))
            and (role := text_of(row.css_first(".role, td:last-child")))
        ]
        relations = [
            Relation(
                kind=RelationKind.SIMILAR,
                target=Entity(type=EntityType.RELEASE, name=name, url=attribute(node, "href")),
                scope=scope,
                sources=[provenance],
            )
            for node in page.css(".similar-albums a.title")
            if (name := text_of(node))
        ]
        return Partial(
            source=self.name,
            candidate=RecordCandidate(kind=kind, artist=artist, title=title, url=url),
            texts=texts,
            tags=tags,
            credits=people,
            relations=relations,
            review_links=[ReviewLink(publication="AllMusic", url=url, sources=[provenance])],
        )
