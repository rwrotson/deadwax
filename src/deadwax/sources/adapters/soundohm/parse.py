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
    Text,
    TextKind,
)
from deadwax.sources._html import Node, attribute, json_ld, parse_html, text_of
from deadwax.sources._search import SearchHit

SOURCE = "soundohm"
SERVICE = "soundohm"
SITE = "https://www.soundohm.com"
PUBLICATION = "Soundohm"

_YEAR = re.compile(r"\b(\d{4})\b")


def artist_name(links: list[Node]) -> str:
    """Credited artists joined the way the matching gate splits them."""
    return " & ".join(name for link in links if (name := text_of(link)))


def search_hits(content: bytes) -> list[SearchHit]:
    """Products of a search page."""
    hits = []
    for product in parse_html(content).css(".listing-grid-product"):
        title = product.css_first("a.product__title")
        artist = artist_name(product.css(".product__artists a"))
        href = attribute(title, "href")
        name = text_of(title)
        if href and name and artist:
            key = RecordKey(artist=artist, title=name, kind=EntityKind.ALBUM)
            hits.append(SearchHit(url=href, key=key))
    return hits


def _facts(info: Node) -> dict[str, str]:
    """Product facts by their name: format, label, genre, catalogue number, year."""
    facts: dict[str, str] = {}
    for fact in info.css(".product-page__fact"):
        name = text_of(fact.css_first(".product-page__fact-key"))
        value = text_of(fact.css_first("a")) or text_of(fact)
        if name and value:
            facts[name.casefold()] = value.removeprefix(name).strip()
    for item in info.css(".product-page__details-fold-item"):
        name, _, value = (text_of(item) or "").partition(":")
        if value.strip():
            facts[name.strip().casefold()] = value.strip()
    return facts


def _prose(node: Node) -> str:
    """Text of a node without spaces added around inline markup."""
    return " ".join(node.text(deep=True).split())


def _description(page: Node) -> str | None:
    node = page.css_first(".product-page__description")
    if node is None:
        return None
    paragraphs = [text for p in node.css("p") if (text := _prose(p))]
    return "\n\n".join(paragraphs) if paragraphs else _prose(node) or None


def _genre(content: bytes) -> str | None:
    """The genre link of the breadcrumb trail."""
    for trail in json_ld(parse_html(content), "BreadcrumbList"):
        items = trail.get("itemListElement")
        for item in items if isinstance(items, list) else []:
            link = item.get("item") if isinstance(item, dict) else None
            if isinstance(link, str) and "/genre/" in link and isinstance(item.get("name"), str):
                return str(item["name"])
    return None


def page_partial(content: bytes, url: str) -> Partial:
    """Shop text, genre, label, and year of a product page."""
    document = parse_html(content)
    page = document.css_first(".product-page")
    info = page.css_first(".product-page__info") if page is not None else None
    artist = artist_name(info.css("h1 a")) if info is not None else ""
    title = text_of(info.css_first("h2")) if info is not None else None
    if page is None or info is None or not artist or title is None:
        raise SourceError("the Soundohm page names no release", url=url)
    facts = _facts(page)
    provenance = Provenance(source=SOURCE, url=url)
    year = _YEAR.search(facts.get("year", ""))
    label = facts.get("label")
    candidate = RecordCandidate(
        kind=EntityKind.ALBUM,
        artist=artist,
        title=title,
        date=year[1] if year else None,
        labels=[CandidateLabel(name=label, catalog_number=facts.get("cat. number"))]
        if label
        else [],
        url=url,
    )
    body = _description(page)
    genre = _genre(content) or facts.get("genre")
    return Partial(
        source=SOURCE,
        candidate=candidate,
        tags=[Tag(name=genre, kind=TagKind.GENRE, scope=Scope.RELEASE, sources=[provenance])]
        if genre
        else [],
        texts=[
            Text(
                kind=TextKind.SHOP,
                body=body,
                publication=PUBLICATION,
                scope=Scope.RELEASE,
                sources=[provenance],
            ),
        ]
        if body
        else [],
        links=[Link(service=SERVICE, url=url, target=LinkTarget.ALBUM, sources=[provenance])],
    )
