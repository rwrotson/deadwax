import re
from urllib.parse import quote, urljoin

from deadwax.core import (
    Capability,
    Entity,
    EntityKind,
    EntityType,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Provenance,
    Query,
    RecordCandidate,
    RecordKey,
    Relation,
    RelationKind,
    Scope,
    SourceError,
    SourceGroup,
    Verdict,
    compare,
)
from deadwax.sources._base import HttpAdapter, search_key
from deadwax.sources._html import Node, attribute, parse_html, text_of
from deadwax.sources._http import Profile

ROOT = "https://www.whosampled.com"
MIN_CELLS = 3
MIN_SAMPLE_BOXES = 2
_SECTION_KINDS = {
    "Contains samples": RelationKind.SAMPLES,
    "Sampled in": RelationKind.SAMPLED_BY,
    "Contains a cover": RelationKind.COVER_OF,
    "Covered in": RelationKind.COVERED_BY,
    "Contains a remix": RelationKind.REMIX_OF,
    "Remixed in": RelationKind.REMIXED_BY,
}


def _offset(value: str | None) -> int | None:
    if value is None or not re.fullmatch(r"\d+(?::\d{1,2}){1,2}", value):
        return None
    result = 0
    for part in value.split(":"):
        result = result * 60 + int(part)
    return result


def _slug(value: str) -> str:
    return quote(re.sub(r"\s+", "-", value.strip()), safe="-'()")


def _record_url(query: Query, key: RecordKey | None) -> str:
    if query.url is not None and "whosampled.com" in query.url:
        return query.url
    if key is not None:
        return f"{ROOT}/{_slug(key.artist)}/{_slug(key.title)}/"
    raise NotFoundError("WhoSampled needs an artist and track title")


class WhoSampledAdapter(HttpAdapter):
    """Read samples, covers, and remixes from a verified recording page."""

    name = "whosampled"
    group = SourceGroup.SAMPLES
    pass_ = Pass.ENRICH
    profile = Profile.BROWSER
    capabilities = frozenset({Capability.RELATIONS})

    def resolves(self, query: Query) -> bool:
        """Read a WhoSampled recording URL directly."""
        return query.url is not None and "whosampled.com" in query.url

    async def _section_relations(self, section: Node, kind: RelationKind) -> list[Relation]:
        rows = section.css("tr")
        relations = []
        for row in rows:
            name_node = row.css_first("a.trackName")
            name = text_of(name_node)
            link = attribute(name_node, "href")
            cells = row.css("td")
            if not name or not link or len(cells) < MIN_CELLS:
                continue
            source_url = urljoin(ROOT, link)
            element = (
                text_of(row.css_first(".tdata__badge"))
                if kind in {RelationKind.SAMPLES, RelationKind.SAMPLED_BY}
                else None
            )
            recording_offset = target_offset = None
            if element:
                detail = parse_html((await self.client.get(source_url)).content)
                boxes = detail.css(".sampleEntryBox")
                if len(boxes) >= MIN_SAMPLE_BOXES:
                    first = _offset(text_of(boxes[0].css_first(".timing")))
                    second = _offset(text_of(boxes[1].css_first(".timing")))
                    recording_offset, target_offset = (
                        (first, second) if kind is RelationKind.SAMPLES else (second, first)
                    )
            relations.append(
                Relation(
                    kind=kind,
                    target=Entity(
                        type=EntityType.RECORDING,
                        name=name,
                        artist=text_of(cells[2]),
                    ),
                    element=element,
                    recording_offset=recording_offset,
                    target_offset=target_offset,
                    scope=Scope.RECORDING,
                    sources=[Provenance(source=self.name, url=source_url)],
                ),
            )
        return relations

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Open a record directly because the site's search path is excluded by robots.txt."""
        key = search_key(query, context)
        if query.kind is EntityKind.ALBUM:
            raise NotFoundError("WhoSampled needs an artist and track title")
        url = _record_url(query, key)
        response = await self.client.get(url)
        page = parse_html(response.content)
        title = attribute(page.css_first('h1 meta[itemprop="name"]'), "content")
        if not title:
            raise SourceError("WhoSampled page names no recording", url=response.url)
        artist = text_of(page.css_first("h1 a")) or (key.artist if key else None)
        if artist is None:
            raise SourceError("WhoSampled page names no artist", url=response.url)
        if key is not None and (
            compare(key, RecordKey(artist=artist, title=title, kind=EntityKind.TRACK)).verdict
            is not Verdict.MATCH
        ):
            raise NotFoundError("WhoSampled page is another recording", url=response.url)
        relations: list[Relation] = []
        for section in page.css("section.subsection"):
            heading = text_of(section.css_first("header")) or ""
            kind = next(
                (item for prefix, item in _SECTION_KINDS.items() if heading.startswith(prefix)),
                None,
            )
            if kind is None:
                continue
            relations.extend(await self._section_relations(section, kind))
        return Partial(
            source=self.name,
            candidate=RecordCandidate(
                kind=EntityKind.TRACK,
                artist=artist,
                title=title,
                url=response.url,
            ),
            relations=relations,
        )
