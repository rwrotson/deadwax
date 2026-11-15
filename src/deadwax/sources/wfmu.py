from urllib.parse import urlencode, urljoin

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
    Text,
    TextKind,
    Verdict,
    compare,
)
from deadwax.sources._base import HttpAdapter, search_key
from deadwax.sources._html import parse_html, text_of
from deadwax.sources._http import Profile

SEARCH = "https://wfmu.org/searchadv.php?action=search"
MIN_CELLS = 2


class WfmuAdapter(HttpAdapter):
    """Find WFMU playlist entries and the DJ's comments on a track."""

    name = "wfmu"
    group = SourceGroup.RADIO
    pass_ = Pass.ENRICH
    profile = Profile.BROWSER
    capabilities = frozenset({Capability.RELATIONS, Capability.TEXTS})

    async def _playlist(self, url: str, key: RecordKey) -> Partial | None:
        detail = await self.client.get(url)
        playlist = parse_html(detail.content)
        title = text_of(playlist.css_first("title")) or "WFMU"
        relations: list[Relation] = []
        texts: list[Text] = []
        candidate: RecordCandidate | None = None
        for row in playlist.css("tr"):
            cells = row.css("td")
            if len(cells) < MIN_CELLS:
                continue
            artist = text_of(cells[0]) or ""
            song = text_of(cells[1]) or ""
            if (
                compare(
                    key,
                    RecordKey(artist=artist, title=song, kind=EntityKind.TRACK),
                ).verdict
                is not Verdict.MATCH
            ):
                continue
            candidate = RecordCandidate(
                kind=EntityKind.TRACK,
                artist=artist,
                title=song,
                url=url,
            )
            source = [Provenance(source=self.name, url=url)]
            relations.append(
                Relation(
                    kind=RelationKind.BROADCAST,
                    target=Entity(type=EntityType.BROADCAST, name=title, url=url),
                    scope=Scope.RECORDING,
                    sources=source,
                ),
            )
            if len(cells) > MIN_CELLS and (comment := text_of(cells[-1])):
                texts.append(
                    Text(
                        kind=TextKind.BROADCAST,
                        body=comment,
                        publication=title,
                        scope=Scope.RECORDING,
                        sources=source,
                    ),
                )
        if candidate is None:
            return None
        return Partial(source=self.name, candidate=candidate, relations=relations, texts=texts)

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Search posted playlists and check their track rows before adding facts."""
        key = search_key(query, context)
        if key is None or key.kind is EntityKind.ALBUM:
            raise NotFoundError("WFMU playlist search needs an artist and track title")
        body = urlencode(
            {
                "searchlogic": "and",
                "searchtext[Artist]": key.artist,
                "searchtext[Song title]": key.title,
            },
        ).encode()
        response = await self.client.request(
            "POST",
            SEARCH,
            headers={"content-type": "application/x-www-form-urlencoded"},
            body=body,
        )
        page = parse_html(response.content)
        content = text_of(page.body) or ""
        if "cannot run searches at this time" in content:
            raise SourceError("WFMU playlist search is temporarily unavailable", url=SEARCH)
        urls = list(
            dict.fromkeys(
                urljoin("https://wfmu.org", href)
                for anchor in page.css('a[href*="playlists/shows/"]')
                if (href := anchor.attributes.get("href"))
            ),
        )
        partials = [p for url in urls[:20] if (p := await self._playlist(url, key)) is not None]
        if not partials:
            raise NotFoundError("no WFMU playlist with this recording", url=SEARCH)
        return Partial(
            source=self.name,
            candidate=partials[0].candidate,
            relations=[relation for partial in partials for relation in partial.relations],
            texts=[text for partial in partials for text in partial.texts],
        )
