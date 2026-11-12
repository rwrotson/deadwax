from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from deadwax import (
    CacheSettings,
    Dossier,
    EntityKind,
    ErrorKind,
    IdKind,
    LinkTarget,
    Pass,
    Query,
    RelationKind,
    SourcesConfig,
    SourceState,
    TextKind,
    VersionKind,
    describe_sources,
    lookup,
    parse_query,
)

Replay = Callable[..., httpx.MockTransport]

PARANOID_ANDROID = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK)
ORIGINAL_RECORDING = "9f9cf187-d6f9-437f-9d98-d59cdbd52757"


async def replayed(query: Query, scenario: str, replay: Replay, config: SourcesConfig) -> Dossier:
    seen: list[str] = []
    dossier = await lookup(query, config, transport=replay(scenario, seen))
    assert seen
    assert [e for e in dossier.errors if e.kind is ErrorKind.FAILED] == []
    return dossier


def ids(dossier: Dossier) -> dict[IdKind, str]:
    return {external.kind: external.value for external in dossier.identity.external_ids}


def errors(dossier: Dossier) -> dict[str, ErrorKind]:
    return {error.source: error.kind for error in dossier.errors}


def tags_from(dossier: Dossier, source: str) -> set[str]:
    """Lower-cased names of the tags a source contributed, merged or not."""
    return {tag.name.lower() for tag in dossier.tags if source in {s.source for s in tag.sources}}


def relation_kinds(dossier: Dossier) -> set[RelationKind]:
    return {relation.kind for relation in dossier.relations}


@pytest.mark.asyncio
async def test_mainstream_track(replay: Replay, config: SourcesConfig) -> None:
    dossier = await replayed(PARANOID_ANDROID, "paranoid_android", replay, config)

    identity = dossier.identity
    assert identity.title is not None
    assert identity.title.value == "Paranoid Android"
    assert {source.source for source in identity.title.sources} == {
        "musicbrainz",
        "itunes",
        "discogs",
        "bandcamp",
    }
    assert identity.version.kind is VersionKind.ORIGINAL
    assert identity.date is not None
    assert identity.date.value == "1997-05-21"
    assert "GBAYE9701376" in [isrc.value for isrc in identity.isrcs]
    assert ids(dossier) | {
        IdKind.MUSICBRAINZ_RECORDING: ORIGINAL_RECORDING,
        IdKind.DISCOGS_MASTER: "21491",
        IdKind.WIKIDATA: "Q1751357",
        IdKind.APPLE_MUSIC: "1097861770",
    } == ids(dossier)
    assert ("producer", "Nigel Godrich") in {(c.role, c.name) for c in dossier.credits}
    assert {"art rock", "alternative rock"} <= {tag.name for tag in dossier.tags}
    assert {RelationKind.MEMBER, RelationKind.COVERED_BY, RelationKind.SAMPLED_BY} <= (
        relation_kinds(dossier)
    )
    assert {"spotify", "deezer", "tidal", "apple_music", "discogs", "bandcamp"} <= {
        link.service for link in dossier.links
    }
    assert "alternative rock" in tags_from(dossier, "discogs")
    assert errors(dossier) == {
        "odesli": ErrorKind.SKIPPED,
        "deezer": ErrorKind.BLOCKED,
        "discogs": ErrorKind.BLOCKED,
    }
    reviews = next(e for e in dossier.errors if e.source == "discogs")
    assert reviews.reason.startswith("reviews:")


@pytest.mark.asyncio
async def test_album_on_a_small_label(replay: Replay, config: SourcesConfig) -> None:
    query = parse_query(
        "Huerco S. - For Those of You Who Have Never (And Also Those Who Have)", EntityKind.ALBUM
    )

    dossier = await replayed(query, "huerco_s", replay, config)

    assert dossier.identity.kind is EntityKind.ALBUM
    labels = {
        (label.name, label.catalog_number): {s.source for s in label.sources}
        for label in dossier.identity.labels
    }
    assert labels == {
        ("Proibito", "PRB018"): {"musicbrainz", "discogs"},
        ("West Mineral Ltd.", None): {"bandcamp"},
    }
    assert ids(dossier)[IdKind.DISCOGS_MASTER] == "1016511"
    assert ("producer", "Brian Leeds") in {(c.role, c.name) for c in dossier.credits}
    bandcamp = [link for link in dossier.links if link.service == "bandcamp"]
    assert [link.target for link in bandcamp] == [LinkTarget.ALBUM, LinkTarget.ARTIST]
    assert ("mastering", "Simon Davey") in {(c.role, c.name) for c in dossier.credits}
    assert {"ambient", "experimental"} <= tags_from(dossier, "discogs")
    assert {"dub", "malleable musics"} <= tags_from(dossier, "bandcamp")
    fans = [text for text in dossier.texts if text.kind is TextKind.USER]
    assert fans
    assert all(text.author for text in fans)
    assert RelationKind.SIMILAR in relation_kinds(dossier)
    assert RelationKind.LABEL_RELEASE in relation_kinds(dossier)


@pytest.mark.asyncio
async def test_cyrillic_track_is_not_transliterated(replay: Replay, config: SourcesConfig) -> None:
    query = parse_query("Кино - Группа крови", EntityKind.TRACK)

    dossier = await replayed(query, "kino", replay, config)

    assert dossier.identity.artist is not None
    assert dossier.identity.artist.value == "Кино"
    assert [
        (label.name, [s.source for s in label.sources]) for label in dossier.identity.labels
    ] == [("Maschina Records", ["bandcamp"])]
    assert ("lyricist", "Виктор Цой") in {(c.role, c.name) for c in dossier.credits}
    assert errors(dossier)["itunes"] is ErrorKind.NO_MATCH


@pytest.mark.asyncio
async def test_remix_is_not_merged_with_the_original(replay: Replay, config: SourcesConfig) -> None:
    query = parse_query("Everything but the Girl - Missing (Todd Terry Remix)", EntityKind.TRACK)

    dossier = await replayed(query, "missing_remix", replay, config)

    version = dossier.identity.version
    assert version.kind is VersionKind.REMIX
    assert version.detail is not None
    assert "Todd Terry" in version.detail
    assert ids(dossier)[IdKind.MUSICBRAINZ_RECORDING] != "e956a427-0d6b-4d5c-b31f-0fde4b3d49a6"
    assert ("remixer", "Todd Terry") in {(c.role, c.name) for c in dossier.credits}
    remix_of = [r for r in dossier.relations if r.kind is RelationKind.REMIX_OF]
    assert [r.target.name for r in remix_of] == ["Missing"]
    assert RelationKind.COVERED_BY not in relation_kinds(dossier)
    assert {d.field for d in dossier.identity.discrepancies} >= {"artist", "date"}
    date = next(d for d in dossier.identity.discrepancies if d.field == "date")
    assert "bandcamp" not in {s.source for value in date.values for s in value.sources}
    assert tags_from(dossier, "bandcamp") == set()
    compilations = [r for r in dossier.relations if r.kind is RelationKind.COMPILATION]
    assert "bandcamp" in {s.source for r in compilations for s in r.sources}
    assert errors(dossier)["discogs"] is ErrorKind.SKIPPED


@pytest.mark.parametrize(
    ("url", "scenario"),
    [
        ("https://open.spotify.com/track/6LgJvl0Xdtc73RJ1mmpotq", "spotify_url"),
        (
            "https://music.apple.com/us/album/paranoid-android/1097861387?i=1097861770",
            "apple_url",
        ),
    ],
)
@pytest.mark.asyncio
async def test_streaming_urls_resolve_to_the_same_recording(
    url: str, scenario: str, replay: Replay, config: SourcesConfig
) -> None:
    dossier = await replayed(parse_query(url), scenario, replay, config)

    assert dossier.identity.kind is EntityKind.TRACK
    assert ids(dossier)[IdKind.MUSICBRAINZ_RECORDING] == ORIGINAL_RECORDING
    assert ids(dossier)[IdKind.APPLE_MUSIC] == "1097861770"


@pytest.mark.asyncio
async def test_unknown_record_has_no_identity(replay: Replay, config: SourcesConfig) -> None:
    query = parse_query("Zzqx Nonexistent Artist - No Such Song At All", EntityKind.TRACK)

    dossier = await replayed(query, "no_match", replay, config)

    assert not dossier.found
    assert errors(dossier)["musicbrainz"] is ErrorKind.NOT_FOUND
    assert errors(dossier)["itunes"] is ErrorKind.NOT_FOUND
    assert errors(dossier)["bandcamp"] is ErrorKind.NOT_FOUND
    assert errors(dossier)["discogs"] is ErrorKind.SKIPPED


@pytest.mark.asyncio
async def test_selection_and_cache(replay: Replay, config: SourcesConfig, tmp_path: Path) -> None:
    cached = config.model_copy(update={"cache": CacheSettings(path=tmp_path / "cache.sqlite")})

    query = parse_query("https://music.apple.com/us/album/x/1097861387?i=1097861770")

    first = await lookup(query, cached, include=["itunes"], transport=replay("apple_url"))
    second = await lookup(
        query,
        cached,
        exclude=["musicbrainz", "deezer", "odesli", "discogs", "bandcamp"],
        transport=replay("no_match"),
    )

    assert first.identity.title is not None
    assert second.identity == first.identity
    assert first.errors == second.errors == []


@pytest.mark.asyncio
async def test_bandcamp_url_resolves_first(replay: Replay, config: SourcesConfig) -> None:
    url = "https://brianleeds.bandcamp.com/album/for-those-of-you-who-have-never-and-also-those-who-have"

    dossier = await replayed(parse_query(url), "bandcamp_url", replay, config)

    assert dossier.identity.kind is EntityKind.ALBUM
    assert dossier.identity.title is not None
    assert dossier.identity.title.sources[0].source == "bandcamp"
    assert ids(dossier)[IdKind.BANDCAMP_ALBUM] == "3201218634"
    assert ids(dossier)[IdKind.DISCOGS_MASTER] == "1016511"


@pytest.mark.asyncio
async def test_discogs_url_resolves_first(replay: Replay, config: SourcesConfig) -> None:
    query = parse_query("https://www.discogs.com/master/21491-Radiohead-OK-Computer")

    dossier = await replayed(query, "discogs_url", replay, config)

    assert dossier.identity.kind is EntityKind.ALBUM
    assert dossier.identity.title is not None
    assert dossier.identity.title.value == "OK Computer"
    assert dossier.identity.title.sources[0].source == "discogs"
    assert ids(dossier)[IdKind.DISCOGS_RELEASE] == "4950798"
    other_versions = [r for r in dossier.relations if r.kind is RelationKind.OTHER_VERSION]
    assert other_versions
    assert {"Thom Yorke", "Jonny Greenwood"} <= {
        r.target.name for r in dossier.relations if r.kind is RelationKind.MEMBER
    }


def test_describe_sources() -> None:
    sources = {info.source: info for info in describe_sources()}

    assert list(sources) == ["musicbrainz", "odesli", "itunes", "deezer", "discogs", "bandcamp"]
    assert sources["musicbrainz"].pass_ is Pass.IDENTITY
    assert sources["odesli"].status.state is SourceState.MISSING_CREDENTIAL
    assert [r.setting for r in sources["odesli"].requires] == ["odesli.api_key"]
    assert sources["itunes"].status.ready
    assert sources["discogs"].status.ready
    assert [r.setting for r in sources["discogs"].requires] == ["discogs.token"]
    assert sources["bandcamp"].status.ready
