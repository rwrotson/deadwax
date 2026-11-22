from collections.abc import Mapping

import httpx
import pytest

from deadwax.core import (
    ArtistCandidate,
    ArtistIdentity,
    ArtistType,
    Capability,
    EntityKind,
    EntityType,
    ExternalId,
    Identity,
    IdKind,
    LabelCandidate,
    LookupContext,
    NotFoundError,
    Partial,
    Provenance,
    Query,
    RecordIdentity,
    RelationKind,
    Scope,
    Sourced,
)
from deadwax.sources import LookupConfig, MusicBrainzSettings, PerSourceSettings, parse_query
from deadwax.sources._http import HttpResources
from deadwax.sources.adapters.musicbrainz import MusicBrainzAdapter, models
from deadwax.sources.adapters.musicbrainz import parse as p

MBID = "{}0000000-0000-0000-0000-000000000000"
ARTIST_ID = MBID.format(1)
LABEL_ID = MBID.format(2)
ARTIST: dict[str, object] = {
    "id": ARTIST_ID,
    "name": "Burial",
    "type": "Person",
    "country": "GB",
    "disambiguation": "UK dubstep producer",
    "life-span": {"begin": "1979"},
    "aliases": [
        {"name": "Burial", "type": "Artist name"},
        {"name": "Berial", "type": "Search hint"},
        {"name": "William Bevan", "type": "Legal name"},
    ],
    "genres": [{"name": "dubstep", "count": 4}],
    "relations": [
        {
            "type": "recording contract",
            "target-type": "label",
            "label": {"id": MBID.format(2), "name": "Hyperdub"},
        },
        {
            "type": "discogs",
            "target-type": "url",
            "url": {"resource": "https://www.discogs.com/artist/166535"},
        },
        {
            "type": "wikidata",
            "target-type": "url",
            "url": {"resource": "https://www.wikidata.org/wiki/Q1000498"},
        },
        {
            "type": "bandcamp",
            "target-type": "url",
            "url": {"resource": "https://burial.bandcamp.com/"},
        },
    ],
}
NAMESAKE = {"id": MBID.format(3), "name": "Burial", "disambiguation": "US punk band"}
GROUPS = {
    "release-groups": [
        {"id": MBID.format(4), "title": "Untrue", "primary-type": "Album",
         "first-release-date": "2007-11-05"},
        {"id": MBID.format(5), "title": "Burial", "primary-type": "Album",
         "first-release-date": "2006-05-15"},
        {"id": MBID.format(6), "title": "Live", "primary-type": "Album",
         "secondary-types": ["Live"]},
        {"id": MBID.format(7), "title": "Archangel", "primary-type": "Single"},
    ],
}  # fmt: skip
LABEL: dict[str, object] = {
    "id": LABEL_ID,
    "name": "Hyperdub",
    "country": "GB",
    "life-span": {"begin": "2004"},
    "relations": [
        {
            "type": "imprint",
            "direction": "forward",
            "target-type": "label",
            "label": {"id": MBID.format(8), "name": "Flatlines"},
        },
        {
            "type": "label ownership",
            "direction": "backward",
            "target-type": "label",
            "label": {"id": MBID.format(9), "name": "Hyperdub Ltd"},
        },
        {
            "type": "label distribution",
            "direction": "backward",
            "target-type": "label",
            "label": {"id": MBID.format(10), "name": "Distributor"},
        },
        {
            "type": "label founder",
            "direction": "backward",
            "target-type": "artist",
            "attributes": ["original"],
            "artist": {"id": MBID.format(11), "name": "Kode9"},
        },
        {
            "type": "discogs",
            "target-type": "url",
            "url": {"resource": "https://www.discogs.com/label/14965"},
        },
    ],
}
SOURCES = [Provenance(source="discogs")]


def respond(routes: Mapping[str, object], seen: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/ws/2/")
        seen.append(path)
        body = routes.get(path)
        if body is None:
            return httpx.Response(404, json={"error": "Not Found"})
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


async def lookup(
    query: Query,
    routes: Mapping[str, object],
    identity: Identity | None = None,
    facets: frozenset[Capability] | None = None,
    seen: list[str] | None = None,
) -> Partial:
    resources = HttpResources(transport=respond(routes, [] if seen is None else seen))
    config = LookupConfig(sources=PerSourceSettings(musicbrainz=MusicBrainzSettings(rate=1000)))
    adapter = MusicBrainzAdapter(config, resources)
    context = LookupContext(
        query=query,
        identity=identity if identity is not None else RecordIdentity(),
        facets=facets,
    )
    try:
        return await adapter.lookup(query, context)
    finally:
        await adapter.aclose()


def artist_routes() -> dict[str, object]:
    return {
        "artist": {"artists": [NAMESAKE | {"name": "Burial Hex"}, ARTIST]},
        f"artist/{ARTIST_ID}": ARTIST,
        "release-group": GROUPS,
    }


@pytest.mark.asyncio
async def test_artist_search_reads_the_matching_artist() -> None:
    partial = await lookup(parse_query("Burial", EntityKind.ARTIST), artist_routes())

    candidate = partial.candidate
    assert isinstance(candidate, ArtistCandidate)
    assert candidate.type is ArtistType.PERSON
    assert (candidate.country, candidate.begin, candidate.end) == ("GB", "1979", None)
    assert candidate.disambiguation == "UK dubstep producer"
    assert candidate.ids == {
        IdKind.MUSICBRAINZ_ARTIST: ARTIST_ID,
        IdKind.DISCOGS_ARTIST: "166535",
        IdKind.WIKIDATA: "Q1000498",
        IdKind.BANDCAMP_ACCOUNT: "burial.bandcamp.com",
    }
    by_kind = {(r.kind, r.target.name) for r in partial.relations}
    assert by_kind == {
        (RelationKind.LABEL, "Hyperdub"),
        (RelationKind.ALIAS, "William Bevan"),
        (RelationKind.RELEASE, "Burial"),
        (RelationKind.RELEASE, "Untrue"),
    }
    releases = [r.target.name for r in partial.relations if r.kind is RelationKind.RELEASE]
    assert releases == ["Burial", "Untrue"]
    assert [t.name for t in partial.tags] == ["dubstep"]
    assert [link.url for link in partial.links] == ["https://burial.bandcamp.com/"]


@pytest.mark.asyncio
async def test_relations_facet_off_skips_the_release_browse() -> None:
    seen: list[str] = []

    partial = await lookup(
        parse_query("Burial", EntityKind.ARTIST),
        artist_routes(),
        facets=frozenset({Capability.TAGS}),
        seen=seen,
    )

    assert "release-group" not in seen
    assert RelationKind.RELEASE not in {r.kind for r in partial.relations}


@pytest.mark.asyncio
async def test_artist_without_a_matching_name_is_not_found() -> None:
    routes = {"artist": {"artists": [NAMESAKE | {"name": "Someone Else"}]}}

    with pytest.raises(NotFoundError):
        await lookup(parse_query("Burial", EntityKind.ARTIST), routes)


@pytest.mark.asyncio
async def test_artist_id_from_an_earlier_pass_needs_no_search() -> None:
    seen: list[str] = []
    identity = ArtistIdentity(
        name=Sourced(value="Burial", sources=SOURCES),
        external_ids=[
            ExternalId(kind=IdKind.MUSICBRAINZ_ARTIST, value=ARTIST_ID, sources=SOURCES),
        ],
    )

    partial = await lookup(
        parse_query("https://www.discogs.com/artist/166535"),
        artist_routes(),
        identity,
        seen=seen,
    )

    assert partial.candidate is not None
    assert "artist" not in seen
    assert "url" not in seen


@pytest.mark.asyncio
async def test_artist_url_of_another_service_is_looked_up() -> None:
    query = parse_query("https://www.discogs.com/artist/166535")
    routes = artist_routes() | {
        "url": {
            "id": MBID.format(12),
            "resource": query.url,
            "relations": [
                {"type": "discogs", "target-type": "artist", "artist": ARTIST},
            ],
        },
    }

    partial = await lookup(query, routes)

    assert partial.candidate is not None
    assert partial.candidate.ids[IdKind.MUSICBRAINZ_ARTIST] == ARTIST_ID


@pytest.mark.asyncio
async def test_unknown_url_falls_back_to_the_name_found_earlier() -> None:
    query = parse_query("https://www.discogs.com/artist/166535")
    identity = ArtistIdentity(name=Sourced(value="Burial", sources=SOURCES))
    routes = artist_routes() | {
        "url": {
            "id": MBID.format(12),
            "resource": query.url,
            "relations": [{"type": "discogs", "target-type": "label", "label": LABEL}],
        },
    }

    partial = await lookup(query, routes, identity)

    assert partial.candidate is not None
    assert partial.candidate.ids[IdKind.MUSICBRAINZ_ARTIST] == ARTIST_ID


@pytest.mark.asyncio
async def test_url_without_a_name_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        await lookup(parse_query("https://www.discogs.com/artist/166535"), {})


@pytest.mark.asyncio
async def test_label_reads_hierarchy_and_artists() -> None:
    routes = {
        "label": {"labels": [LABEL]},
        f"label/{LABEL_ID}": LABEL,
        "url": {"id": MBID.format(12), "resource": "x", "relations": []},
    }

    partial = await lookup(parse_query("Hyperdub", EntityKind.LABEL), routes)

    candidate = partial.candidate
    assert isinstance(candidate, LabelCandidate)
    assert candidate.ids == {IdKind.MUSICBRAINZ_LABEL: LABEL_ID, IdKind.DISCOGS_LABEL: "14965"}
    relations = {(r.kind, r.target.name, r.note) for r in partial.relations}
    assert relations == {
        (RelationKind.SUBLABEL, "Flatlines", "imprint"),
        (RelationKind.PARENT_LABEL, "Hyperdub Ltd", "label ownership"),
        (RelationKind.ASSOCIATED, "Kode9", "label founder: original"),
    }


@pytest.mark.asyncio
async def test_label_url_of_another_service_is_looked_up() -> None:
    query = parse_query("https://www.discogs.com/label/14965")
    routes = {
        f"label/{LABEL_ID}": LABEL,
        "url": {
            "id": MBID.format(12),
            "resource": query.url,
            "relations": [
                {"type": "discogs", "target-type": "artist", "artist": ARTIST},
                {"type": "discogs", "target-type": "label", "label": LABEL},
            ],
        },
    }

    partial = await lookup(query, routes)

    assert partial.candidate is not None
    assert partial.candidate.ids[IdKind.MUSICBRAINZ_LABEL] == LABEL_ID


@pytest.mark.asyncio
async def test_label_search_without_a_match_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        await lookup(parse_query("Hyperdub", EntityKind.LABEL), {"label": {"labels": []}})


def test_artist_type_outside_the_vocabulary_is_left_out() -> None:
    artist = models.Artist.model_validate(ARTIST | {"type": "Unknown"})

    assert p.artist_candidate(artist).type is None


def test_aliases_skip_blank_and_repeated_names() -> None:
    artist = models.Artist.model_validate(
        ARTIST | {"aliases": [{"name": " "}, {"name": "B"}, {"name": "b"}]},
    )

    found = p.aliases(artist, EntityType.ARTIST, Scope.ARTIST, "u")

    assert [(r.target.name, r.target.type) for r in found] == [("B", EntityType.ARTIST)]


def test_musicbrainz_resolves_its_artist_and_label_pages() -> None:
    adapter = MusicBrainzAdapter(LookupConfig(), HttpResources())

    assert adapter.resolves(parse_query(f"https://musicbrainz.org/artist/{ARTIST_ID}"))
    assert adapter.resolves(parse_query(f"https://musicbrainz.org/label/{LABEL_ID}"))
    assert adapter.lookups.kinds == frozenset(EntityKind)
