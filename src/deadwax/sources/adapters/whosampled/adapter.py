from urllib.parse import urljoin, urlsplit

from deadwax.core import (
    Capability,
    Entity,
    EntityKind,
    EntityType,
    LookupContext,
    Lookups,
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
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._html import Node, attribute, parse_html, text_of
from deadwax.sources._http import Profile
from deadwax.sources._search import search_key
from deadwax.sources.adapters.whosampled import parse


class WhoSampledAdapter(HttpAdapter):
    """Read samples, covers, and remixes from a verified recording page."""

    name = "whosampled"
    group = SourceGroup.SAMPLES
    pass_ = Pass.ENRICH
    service = "whosampled"
    profile = Profile.BROWSER
    capabilities = frozenset({Capability.RELATIONS})

    async def _section_relations(self, section: Node, kind: RelationKind) -> list[Relation]:
        rows = section.css("tr")
        relations = []
        for row in rows:
            name_node = row.css_first("a.trackName")
            name = text_of(name_node)
            link = attribute(name_node, "href")
            cells = row.css("td")
            if not name or not link or len(cells) < parse.MIN_CELLS:
                continue
            source_url = urljoin(parse.ROOT, link)
            element = (
                text_of(row.css_first(".tdata__badge"))
                if kind in {RelationKind.SAMPLES, RelationKind.SAMPLED_BY}
                else None
            )
            recording_offset = target_offset = None
            if element:
                detail = parse_html((await self.client.get(source_url)).content)
                boxes = detail.css(".sampleEntryBox")
                if len(boxes) >= parse.MIN_SAMPLE_BOXES:
                    first = parse.offset(text_of(boxes[0].css_first(".timing")))
                    second = parse.offset(text_of(boxes[1].css_first(".timing")))
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

    @property
    def lookups(self) -> Lookups:
        """Tracks, also from a track page URL."""
        return Lookups(track=self.find, unresolved=self.find)

    async def find(self, query: Query, context: LookupContext) -> Partial:
        """Open a record directly because the site's search path is excluded by robots.txt."""
        key = search_key(query, context)
        url = parse.record_url(query, key)
        response = await self.client.get(url)

        # The site redirects an unknown track to its artist's page.
        if len(urlsplit(response.url).path.strip("/").split("/")) == 1:
            raise NotFoundError("no WhoSampled page for the track", url=response.url)

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
                (
                    item
                    for prefix, item in parse.SECTION_KINDS.items()
                    if heading.startswith(prefix)
                ),
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
