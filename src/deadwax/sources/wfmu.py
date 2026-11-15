from datetime import UTC, datetime
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
    SourceGroup,
    Text,
    TextKind,
    Verdict,
    compare,
    normalize_artist,
)
from deadwax.sources._base import HttpAdapter, search_key
from deadwax.sources._html import parse_html, text_of
from deadwax.sources._http import Profile

ARTISTS = "https://wfmu.org/artistbrowser.php"
MIN_CELLS = 2
MIN_INDEX_CELLS = 4
MAX_PLAYLISTS = 10


def _date(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%b %d %Y").replace(tzinfo=UTC).date().isoformat()
    except ValueError:
        return None


def _artist_id(content: bytes, artist: str) -> str | None:
    page = parse_html(content)
    wanted = normalize_artist(artist)
    for button in page.css('button[name="id"]'):
        if normalize_artist(text_of(button) or "") == wanted:
            return button.attributes.get("value")
    return None


def _plays(content: bytes, key: RecordKey) -> list[tuple[str, str | None]]:
    page = parse_html(content)
    found: dict[str, str | None] = {}
    for row in page.css("tr"):
        cells = row.css("td")
        if len(cells) < MIN_INDEX_CELLS:
            continue
        artist = text_of(cells[0]) or ""
        title = (text_of(cells[1]) or "").split(" (plus", maxsplit=1)[0].strip('" ')
        if (
            compare(
                key,
                RecordKey(artist=artist, title=title, kind=EntityKind.TRACK),
            ).verdict
            is not Verdict.MATCH
        ):
            continue
        link = cells[-1].css_first('a[href*="/playlists/"]')
        if link is not None and (href := link.attributes.get("href")):
            found[urljoin("https://wfmu.org", href)] = _date(text_of(link))
    return sorted(found.items(), key=lambda item: item[1] or "", reverse=True)


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
            if len(cells) < MIN_CELLS:
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
            ARTISTS,
            params={"action": "artistlist", "initial": initial},
        )
        artist_id = _artist_id(index.content, key.artist)
        if artist_id is None:
            raise NotFoundError("artist absent from WFMU playlists", url=index.url)
        response = await self.client.request(
            "POST",
            ARTISTS,
            params={"action": "artist"},
            headers={"content-type": "application/x-www-form-urlencoded"},
            body=urlencode({"id": artist_id}).encode(),
        )
        plays = _plays(response.content, key)
        partials = [
            p
            for url, date in plays[:MAX_PLAYLISTS]
            if (p := await self._playlist(url, key, date)) is not None
        ]
        if not partials:
            raise NotFoundError("no WFMU playlist with this recording", url=response.url)
        return Partial(
            source=self.name,
            candidate=partials[0].candidate,
            relations=[relation for partial in partials for relation in partial.relations],
            texts=[text for partial in partials for text in partial.texts],
        )
