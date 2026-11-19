import logging
from urllib.parse import urlencode

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
    SourceGroup,
    Text,
    TextKind,
    Verdict,
    adapter_time_left,
    compare,
    trace,
)
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._html import parse_html, text_of
from deadwax.sources._http import Profile
from deadwax.sources._search import search_key
from deadwax.sources.adapters.wfmu import parse

logger = logging.getLogger(__name__)


class WfmuAdapter(HttpAdapter):
    """Find WFMU playlist entries and the DJ's comments on a track."""

    name = "wfmu"
    group = SourceGroup.RADIO
    pass_ = Pass.ENRICH
    profile = Profile.BROWSER
    capabilities = frozenset({Capability.RELATIONS, Capability.TEXTS})

    async def _playlist(self, url: str, key: RecordKey, date: str | None) -> Partial | None:
        detail = await self.client.get(url)
        playlist = parse_html(detail.content)
        title = text_of(playlist.css_first("title")) or "WFMU"
        program = title.split(": Playlist", maxsplit=1)[0]
        host = program.rsplit(" with ", maxsplit=1)[-1] if " with " in program else None
        relations: list[Relation] = []
        texts: list[Text] = []
        candidate: RecordCandidate | None = None
        for row in playlist.css("tr"):
            cells = row.css("td")
            if len(cells) < parse.MIN_CELLS:
                continue
            artist = text_of(row.css_first(".col_artist font")) or text_of(cells[0]) or ""
            song = text_of(row.css_first(".col_song_title font")) or text_of(cells[1]) or ""
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
                    target=Entity(type=EntityType.BROADCAST, name=program, date=date, url=url),
                    scope=Scope.RECORDING,
                    sources=source,
                ),
            )
            comment = text_of(row.css_first(".col_comments font"))
            if comment:
                texts.append(
                    Text(
                        kind=TextKind.BROADCAST,
                        body=comment,
                        author=host,
                        publication=program,
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
        initial = key.artist[:1].upper()
        index = await self.client.get(
            parse.ARTISTS,
            params={"action": "artistlist", "initial": initial},
        )
        artist_id = parse.artist_id(index.content, key.artist)
        if artist_id is None:
            raise NotFoundError("artist absent from WFMU playlists", url=index.url)
        response = await self.client.request(
            "POST",
            parse.ARTISTS,
            params={"action": "artist"},
            headers={"content-type": "application/x-www-form-urlencoded"},
            body=urlencode({"id": artist_id}).encode(),
        )
        plays = parse.plays(response.content, key)[: parse.MAX_PLAYLISTS]
        partials: list[Partial] = []
        for read, (url, date) in enumerate(plays):
            left = adapter_time_left()
            if partials and left is not None and left < parse.PLAYLIST_RESERVE:
                trace(logger, "wfmu.truncated", read=read, remaining=len(plays) - read)
                break
            if (partial := await self._playlist(url, key, date)) is not None:
                partials.append(partial)
        if not partials:
            raise NotFoundError("no WFMU playlist with this recording", url=response.url)
        return Partial(
            source=self.name,
            candidate=partials[0].candidate,
            relations=[relation for partial in partials for relation in partial.relations],
            texts=[text for partial in partials for text in partial.texts],
        )
