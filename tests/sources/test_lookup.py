from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from deadwax import (
    CacheSettings,
    Dossier,
    EntityKind,
    EntityType,
    ErrorKind,
    HttpSettings,
    IdKind,
    LinkTarget,
    LookupConfig,
    MetricKind,
    Pass,
    Query,
    Rating,
    RecordIdentity,
    RelationKind,
    Scope,
    SourceGroup,
    SourceState,
    TextKind,
    TrackQuery,
    VersionKind,
    describe_sources,
    lookup,
    parse_query,
)
from deadwax.sources import SpotifySettings, build_adapters
from deadwax.sources._http import BrowserSessions, HttpResources
from deadwax.sources.services import SERVICES

Replay = Callable[..., httpx.MockTransport]

PARANOID_ANDROID = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK)
ORIGINAL_RECORDING = "9f9cf187-d6f9-437f-9d98-d59cdbd52757"


async def replayed(query: Query, scenario: str, replay: Replay, config: LookupConfig) -> Dossier:
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
async def test_mainstream_track(replay: Replay, config: LookupConfig) -> None:
    dossier = await replayed(PARANOID_ANDROID, "paranoid_android", replay, config)

    identity = dossier.identity
    assert isinstance(identity, RecordIdentity)
    assert identity.title is not None
    assert identity.title.value == "Paranoid Android"
    assert {source.source for source in identity.title.sources} == {
        "musicbrainz",
        "itunes",
        "discogs",
        "bandcamp",
        "odesli",
        "lastfm",
        "wikipedia",
        "secondhandsongs",
        "kexp",
        "spotify",
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
    leads = {
        (source.source, relation.kind, relation.target.type)
        for relation in dossier.relations
        for source in relation.sources
    }
    assert {
        ("listenbrainz", RelationKind.SIMILAR_ARTIST_RECORDING, EntityType.RECORDING),
        ("lastfm", RelationKind.SIMILAR, EntityType.ARTIST),
        ("musicbrainz", RelationKind.ASSOCIATED, EntityType.ARTIST),
    } <= leads
    assert ("The Smile", "subgroup") in {
        (r.target.name, r.note) for r in dossier.relations if r.kind is RelationKind.ASSOCIATED
    }
    assert {"spotify", "deezer", "tidal", "apple_music", "discogs", "bandcamp"} <= {
        link.service for link in dossier.links
    }
    assert "alternative rock" in tags_from(dossier, "discogs")
    assert errors(dossier) == {"genius": ErrorKind.SKIPPED}
    assert {"pandora", "yandex"} <= {
        link.service for link in dossier.links if link.sources[0].source == "odesli"
    }
    weighted = [t for t in dossier.tags if t.sources[0].source == "lastfm" and t.weight]
    assert Scope.RECORDING in {t.scope for t in weighted}
    similar = [r for r in dossier.relations if r.kind is RelationKind.SIMILAR]
    assert any(r.sources[0].source == "lastfm" for r in similar)
    wiki = [t for t in dossier.texts if t.sources[0].source == "wikipedia"]
    assert {"Paranoid Android", "Composition"} <= {t.title for t in wiki}
    assert ("lyricist", "Thom Yorke") in {(c.role, c.name) for c in dossier.credits}


@pytest.mark.asyncio
async def test_album_on_a_small_label(replay: Replay, config: LookupConfig) -> None:
    query = parse_query(
        "Huerco S. - For Those of You Who Have Never (And Also Those Who Have)",
        EntityKind.ALBUM,
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
    scores = {t.publication: t.rating for t in dossier.texts if t.kind is TextKind.REVIEW}
    assert scores["Metacritic"] == Rating(value=85, scale=100)
    assert scores["Pitchfork"] == Rating(value=8.1, scale=10)
    # Wikidata names the performer Pendant, with Huerco S. as an alias.
    assert dossier.identity.artist is not None
    assert "wikipedia" in {s.source for s in dossier.identity.artist.sources}
    assert {r.target.name for r in dossier.relations if r.kind is RelationKind.SIMILAR} >= {
        "Actress",
        "Gas",
    }
    assert RelationKind.SIMILAR in relation_kinds(dossier)
    assert RelationKind.LABEL_RELEASE in relation_kinds(dossier)
    # Odesli starts from the Apple Music link that iTunes found in the enrichment pass.
    assert "odesli" not in errors(dossier)
    assert any(link.sources[0].source == "odesli" for link in dossier.links)


@pytest.mark.asyncio
async def test_cyrillic_track_is_not_transliterated(replay: Replay, config: LookupConfig) -> None:
    query = parse_query("Кино - Группа крови", EntityKind.TRACK)

    dossier = await replayed(query, "kino", replay, config)

    assert isinstance(dossier.identity, RecordIdentity)
    assert dossier.identity.artist is not None
    assert dossier.identity.artist.value == "Кино"
    assert [
        (label.name, [s.source for s in label.sources]) for label in dossier.identity.labels
    ] == [("Maschina Records", ["bandcamp"])]
    assert ("lyricist", "Виктор Цой") in {(c.role, c.name) for c in dossier.credits}
    assert errors(dossier)["itunes"] is ErrorKind.NO_MATCH
    assert errors(dossier)["odesli"] is ErrorKind.NO_MATCH
    russian = [t for t in dossier.texts if t.kind is TextKind.WIKI and t.language == "ru"]
    assert {"Группа крови (песня)", "Смысл", "История песни"} <= {t.title for t in russian}
    assert all(t.sources[0].url and "ru.wikipedia.org" in t.sources[0].url for t in russian)
    # The English sitelink redirects to the album article, which is not about the song.
    assert not [t for t in dossier.texts if t.language == "en"]
    similar = [r.target.artist for r in dossier.relations if r.kind is RelationKind.SIMILAR]
    assert "Агата Кристи" in similar


@pytest.mark.asyncio
async def test_remix_is_not_merged_with_the_original(replay: Replay, config: LookupConfig) -> None:
    query = parse_query("Everything but the Girl - Missing (Todd Terry Remix)", EntityKind.TRACK)

    dossier = await replayed(query, "missing_remix", replay, config)

    assert isinstance(dossier.identity, RecordIdentity)
    version = dossier.identity.version
    assert version.kind is VersionKind.REMIX
    assert version.detail is not None
    assert "Todd Terry" in version.detail
    assert ids(dossier)[IdKind.MUSICBRAINZ_RECORDING] != "e956a427-0d6b-4d5c-b31f-0fde4b3d49a6"
    assert ("remixer", "Todd Terry") in {(c.role, c.name) for c in dossier.credits}
    remix_of = [r for r in dossier.relations if r.kind is RelationKind.REMIX_OF]
    assert [r.target.name for r in remix_of] == ["Missing"]
    assert RelationKind.COVERED_BY not in relation_kinds(dossier)
    assert {d.field for d in dossier.identity.discrepancies} >= {"date"}
    date = next(d for d in dossier.identity.discrepancies if d.field == "date")
    assert "bandcamp" not in {s.source for value in date.values for s in value.sources}
    assert tags_from(dossier, "bandcamp") == set()
    compilations = [r for r in dossier.relations if r.kind is RelationKind.COMPILATION]
    assert "bandcamp" in {s.source for r in compilations for s in r.sources}
    assert errors(dossier)["discogs"] is ErrorKind.SKIPPED
    # Wikidata's item is the original song: it stays out and is listed as another version.
    other = [r for r in dossier.relations if r.kind is RelationKind.OTHER_VERSION]
    assert "wikipedia" in {s.source for r in other for s in r.sources}
    assert not [t for t in dossier.texts if t.sources[0].source == "wikipedia"]
    assert dossier.identity.title is not None
    assert "lastfm" in {s.source for s in dossier.identity.title.sources}


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
    url: str,
    scenario: str,
    replay: Replay,
    config: LookupConfig,
) -> None:
    dossier = await replayed(parse_query(url), scenario, replay, config)

    assert dossier.identity.kind is EntityKind.TRACK
    assert ids(dossier)[IdKind.MUSICBRAINZ_RECORDING] == ORIGINAL_RECORDING
    assert ids(dossier)[IdKind.APPLE_MUSIC] == "1097861770"
    odesli = [link for link in dossier.links if link.sources[0].source == "odesli"]
    assert odesli
    assert odesli[0].sources[0].url is not None
    assert "song.link" in odesli[0].sources[0].url


@pytest.mark.asyncio
async def test_spotify_resolves_its_urls_when_it_has_credentials(
    replay: Replay,
    config: LookupConfig,
) -> None:
    query = parse_query("https://open.spotify.com/track/6LgJvl0Xdtc73RJ1mmpotq")
    sources = config.sources.model_copy(update={"spotify": SpotifySettings(rate=1000)})
    without = config.model_copy(update={"sources": sources})

    with_spotify = await replayed(query, "spotify_url", replay, config)
    without_spotify = await replayed(query, "spotify_url", replay, without)

    for dossier, resolver in ((with_spotify, "spotify"), (without_spotify, "musicbrainz")):
        assert isinstance(dossier.identity, RecordIdentity)
        assert dossier.identity.title is not None
        assert dossier.identity.title.sources[0].source == resolver
        assert ids(dossier)[IdKind.MUSICBRAINZ_RECORDING] == ORIGINAL_RECORDING
    assert errors(without_spotify)["spotify"] is ErrorKind.SKIPPED
    assert isinstance(with_spotify.identity, RecordIdentity)
    copyrights = {line.value for line in with_spotify.identity.copyrights}
    assert copyrights == {"© 1997 XL Recordings Ltd", "℗ 1997 XL Recordings Ltd"}


@pytest.mark.asyncio
async def test_youtube_links_official_uploads(replay: Replay, config: LookupConfig) -> None:
    dossier = await replayed(PARANOID_ANDROID, "paranoid_android", replay, config)

    youtube = [link for link in dossier.links if link.service == "youtube"]
    assert 0 < len(youtube) <= 3
    assert {link.sources[0].source for link in youtube} == {"youtube"}
    assert isinstance(dossier.identity, RecordIdentity)
    assert dossier.identity.title is not None
    assert "youtube" not in {s.source for s in dossier.identity.title.sources}


@pytest.mark.asyncio
async def test_soundcloud_url_resolves_first(replay: Replay, config: LookupConfig) -> None:
    query = parse_query("https://soundcloud.com/radiohead/paranoid-android")

    include = [*config.default_sources, "soundcloud"]
    dossier = await lookup(query, config, include=include, transport=replay("soundcloud_url"))

    assert [e for e in dossier.errors if e.kind is ErrorKind.FAILED] == []
    assert dossier.identity.kind is EntityKind.TRACK
    assert dossier.identity.title is not None
    assert dossier.identity.title.sources[0].source == "soundcloud"
    assert ids(dossier)[IdKind.SOUNDCLOUD] == "265069358"
    assert ids(dossier)[IdKind.MUSICBRAINZ_RECORDING] == ORIGINAL_RECORDING
    kinds = {metric.kind for metric in dossier.metrics if metric.sources[0].source == "soundcloud"}
    assert {MetricKind.LISTENS, MetricKind.LIKES, MetricKind.REPOSTS} <= kinds


@pytest.mark.asyncio
async def test_unknown_record_has_no_identity(replay: Replay, config: LookupConfig) -> None:
    query = parse_query("Zzqx Nonexistent Artist - No Such Song At All", EntityKind.TRACK)

    dossier = await replayed(query, "no_match", replay, config)

    assert not dossier.found
    assert errors(dossier)["musicbrainz"] is ErrorKind.NOT_FOUND
    assert errors(dossier)["itunes"] is ErrorKind.NOT_FOUND
    assert errors(dossier)["bandcamp"] is ErrorKind.NOT_FOUND
    assert errors(dossier)["discogs"] is ErrorKind.SKIPPED


@pytest.mark.asyncio
async def test_selection_and_cache(replay: Replay, config: LookupConfig, tmp_path: Path) -> None:
    cached = config.model_copy(update={"cache": CacheSettings(path=tmp_path / "cache.sqlite")})

    query = parse_query("https://music.apple.com/us/album/x/1097861387?i=1097861770")

    first = await lookup(query, cached, include=["itunes"], transport=replay("apple_url"))
    second = await lookup(
        query,
        cached,
        exclude=[
            "musicbrainz",
            "deezer",
            "odesli",
            "discogs",
            "bandcamp",
            "lastfm",
            "wikipedia",
            "catalogues",
            "radio",
            "streaming",
        ],
        transport=replay("no_match"),
    )

    assert isinstance(first.identity, RecordIdentity)
    assert first.identity.title is not None
    assert second.identity == first.identity
    assert first.errors == second.errors == []


@pytest.mark.asyncio
async def test_bandcamp_url_resolves_first(replay: Replay, config: LookupConfig) -> None:
    url = "https://brianleeds.bandcamp.com/album/for-those-of-you-who-have-never-and-also-those-who-have"

    dossier = await replayed(parse_query(url), "bandcamp_url", replay, config)

    assert dossier.identity.kind is EntityKind.ALBUM
    assert dossier.identity.title is not None
    assert dossier.identity.title.sources[0].source == "bandcamp"
    assert ids(dossier)[IdKind.BANDCAMP_ALBUM] == "3201218634"
    assert ids(dossier)[IdKind.DISCOGS_MASTER] == "1016511"


@pytest.mark.asyncio
async def test_discogs_url_resolves_first(replay: Replay, config: LookupConfig) -> None:
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


@pytest.mark.asyncio
async def test_default_sources_run_without_include(replay: Replay, config: LookupConfig) -> None:
    query = parse_query("https://music.apple.com/us/album/x/1097861387?i=1097861770")
    seen: list[str] = []

    dossier = await lookup(
        query,
        config.model_copy(update={"default_sources": ("itunes",)}),
        transport=replay("apple_url", seen),
    )

    assert isinstance(dossier.identity, RecordIdentity)
    assert dossier.identity.title is not None
    assert dossier.errors == []
    assert seen
    assert all("itunes.apple.com" in key for key in seen)


@pytest.mark.asyncio
async def test_include_replaces_the_default_sources(replay: Replay, config: LookupConfig) -> None:
    query = parse_query("https://music.apple.com/us/album/x/1097861387?i=1097861770")
    seen: list[str] = []

    await lookup(
        query,
        config.model_copy(update={"default_sources": ("unknown",)}),
        include=["core"],
        exclude=["musicbrainz", "deezer", "odesli", "discogs", "bandcamp", "lastfm", "wikipedia"],
        transport=replay("apple_url", seen),
    )

    assert seen
    assert all("itunes.apple.com" in key for key in seen)


def test_describe_sources_marks_groups_and_the_default_set() -> None:
    infos = describe_sources(
        LookupConfig.model_validate({"default_sources": "musicbrainz, deezer"}),
    )

    assert {info.group for info in infos} == {
        SourceGroup.CORE,
        SourceGroup.CATALOGUES,
        SourceGroup.RADIO,
        SourceGroup.STREAMING,
        SourceGroup.SHOPS,
        SourceGroup.PRESS,
        SourceGroup.SAMPLES,
    }
    assert [info.source for info in infos if info.default] == ["musicbrainz", "deezer"]
    assert [info.source for info in describe_sources() if not info.default] == [
        "beatport",
        "juno",
        "forcedexposure",
        "bleep",
        "phonica",
        "boomkat",
        "norman",
        "allmusic",
        "albumoftheyear",
        "rateyourmusic",
        "whosampled",
        "tracklists",
    ]


def test_no_source_is_named_like_a_group() -> None:
    assert {info.source for info in describe_sources()}.isdisjoint(set(SourceGroup))


def test_describe_sources_reports_configured_access() -> None:
    config = LookupConfig.model_validate(
        {
            "sources": {
                "bandcamp": {"browser_headless": False, "html_transports": ["browser", "httpx"]},
            },
            "http": {"browser_headless": True},
        },
    )
    sources = {info.source: info.access for info in describe_sources(config)}

    assert sources["musicbrainz"].api
    assert sources["musicbrainz"].html_transports == []
    assert sources["deezer"].html_transports == [
        "httpx",
        "impersonate",
        "patchright",
        "nodriver",
    ]
    assert sources["deezer"].browser_headless is True
    assert sources["deezer"].headed_fallback
    assert not sources["musicbrainz"].headed_fallback
    assert sources["bandcamp"].api
    assert sources["bandcamp"].html_transports == ["patchright", "httpx"]
    assert sources["bandcamp"].browser_headless is False
    assert sources["discogs"].api
    assert sources["discogs"].html_transports == []
    for name in ("genius", "hardwax"):
        assert sources[name].api
        assert sources[name].html_transports


def test_describe_sources_disables_one_without_permitted_transports() -> None:
    config = LookupConfig.model_validate({"http": {"escalation": []}})

    sources = {info.source: info for info in describe_sources(config)}

    assert sources["norman"].access.html_transports == []
    assert sources["norman"].status.state is SourceState.DISABLED
    assert sources["norman"].status.detail == "no permitted HTML transports"
    assert sources["musicbrainz"].status.ready


@pytest.mark.asyncio
async def test_blocked_error_carries_configured_access() -> None:
    config = LookupConfig.model_validate(
        {
            "sources": {"deezer": {"html_transports": ["httpx"]}},
            "http": {"escalation": [], "browser_headless": False},
        },
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            403,
            content=b"<html><title>Just a moment...</title></html>",
            request=request,
        ),
    )

    dossier = await lookup(PARANOID_ANDROID, config, include=["deezer"], transport=transport)

    [error] = dossier.errors
    assert error.kind is ErrorKind.BLOCKED
    assert error.access is not None
    assert error.access.html_transports == ["httpx"]
    assert error.access.browser_headless is False


@pytest.mark.asyncio
async def test_lookup_closes_shared_browsers(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[BrowserSessions] = []

    async def aclose(sessions: BrowserSessions) -> None:
        closed.append(sessions)

    monkeypatch.setattr(BrowserSessions, "aclose", aclose)
    transport = httpx.MockTransport(lambda request: httpx.Response(404, request=request))

    await lookup(PARANOID_ANDROID, include=["deezer"], transport=transport)

    assert len(closed) == 1


@pytest.mark.asyncio
async def test_lookup_does_not_request_a_source_without_permitted_transports() -> None:
    config = LookupConfig.model_validate({"http": {"escalation": []}})
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    dossier = await lookup(
        PARANOID_ANDROID,
        config,
        include=["norman"],
        transport=httpx.MockTransport(answer),
    )

    assert requests == []
    assert dossier.errors == []


def test_describe_sources() -> None:
    sources = {info.source: info for info in describe_sources()}

    assert list(sources) == [
        "spotify", "musicbrainz", "odesli", "itunes", "deezer", "discogs", "bandcamp", "lastfm",
        "wikipedia", "listenbrainz", "secondhandsongs", "kexp", "youtube", "soundcloud",
        "beatport", "hardwax", "soundohm", "juno", "forcedexposure", "bleep", "phonica",
        "boomkat", "norman", "genius",
        "allmusic", "albumoftheyear", "pressreviews", "ra", "nts", "wfmu",
        "rateyourmusic", "whosampled", "tracklists",
    ]  # fmt: skip
    assert sources["musicbrainz"].pass_ is Pass.IDENTITY
    assert sources["odesli"].status.ready
    assert sources["odesli"].requires == []
    assert sources["itunes"].status.ready
    assert sources["discogs"].status.ready
    assert [r.setting for r in sources["discogs"].requires] == ["sources.discogs.token"]
    assert sources["bandcamp"].status.ready
    assert sources["lastfm"].status.state is SourceState.MISSING_CREDENTIAL
    assert [r.setting for r in sources["lastfm"].requires] == ["sources.lastfm.api_key"]
    assert sources["wikipedia"].status.ready
    assert sources["beatport"].status.ready
    assert sources["beatport"].group is SourceGroup.STREAMING
    assert not sources["beatport"].default
    for name in (
        "hardwax",
        "soundohm",
        "juno",
        "forcedexposure",
        "bleep",
        "phonica",
        "boomkat",
        "norman",
    ):
        assert sources[name].status.ready
        assert sources[name].group is SourceGroup.SHOPS
        assert sources[name].default == (name in {"hardwax", "soundohm"})
    for name in ("spotify", "youtube", "soundcloud"):
        assert sources[name].status.state is SourceState.MISSING_CREDENTIAL
        assert sources[name].group is SourceGroup.STREAMING
    assert [r.setting for r in sources["spotify"].requires] == [
        "sources.spotify.client_id",
        "sources.spotify.client_secret",
    ]


@pytest.mark.asyncio
async def test_covers_from_two_sources_merge_per_target(
    replay: Replay,
    config: LookupConfig,
) -> None:
    query = parse_query("Tim Buckley - Song to the Siren", EntityKind.TRACK)

    dossier = await lookup(query, config, exclude=["lastfm"], transport=replay("siren_covers"))

    covers = [r for r in dossier.relations if r.kind is RelationKind.COVERED_BY]
    targets = [(r.target.artist, r.target.name) for r in covers]
    assert len(targets) == len(set(targets))
    by_artist = {r.target.artist: {s.source for s in r.sources} for r in covers}
    assert by_artist["This Mortal Coil"] == {"musicbrainz", "secondhandsongs"}
    first = next(r for r in dossier.relations if r.note == "first performance")
    assert (first.kind, first.target.artist) == (RelationKind.OTHER_VERSION, "Tim Buckley")
    assert ("writer", "Larry Beckett") in {(c.role, c.name) for c in dossier.credits}
    assert {m.sources[0].source for m in dossier.metrics} == {"listenbrainz"}


@pytest.mark.asyncio
async def test_radio_plays_and_host_comments(replay: Replay, config: LookupConfig) -> None:
    query = parse_query("Radiohead - Reckoner", EntityKind.TRACK)

    dossier = await lookup(query, config, exclude=["lastfm"], transport=replay("reckoner"))

    broadcasts = [r for r in dossier.relations if r.kind is RelationKind.BROADCAST]
    assert len({r.target.date for r in broadcasts}) == len(broadcasts) > 1
    assert all(r.target.name.startswith("KEXP") for r in broadcasts)
    comments = [t for t in dossier.texts if t.kind is TextKind.BROADCAST]
    assert comments
    assert any(len(t.sources) > 1 for t in comments)
    assert [e for e in dossier.errors if e.kind is ErrorKind.FAILED] == []


@pytest.mark.asyncio
async def test_explicit_recording_is_the_original(replay: Replay, config: LookupConfig) -> None:
    query = parse_query("Kanye West - Stronger", EntityKind.TRACK)

    dossier = await lookup(query, config, exclude=["lastfm"], transport=replay("stronger_samples"))

    assert ids(dossier)[IdKind.MUSICBRAINZ_RECORDING].startswith("8009d470")
    assert isinstance(dossier.identity, RecordIdentity)
    assert dossier.identity.version.kind is VersionKind.ORIGINAL
    samples = [r.target for r in dossier.relations if r.kind is RelationKind.SAMPLES]
    assert ("Daft Punk", "Harder, Better, Faster, Stronger") in {
        (t.artist, t.name) for t in samples
    }
    assert RelationKind.SAMPLED_BY in relation_kinds(dossier)
    assert dossier.metrics


@pytest.mark.asyncio
async def test_radio_search_drops_other_versions_and_missing_artists() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.nts.live":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Archangel (Live)",
                            "artists": [{"name": "Burial"}],
                            "article": {"path": "/shows/example/episodes/live"},
                        },
                    ],
                },
            )
        return httpx.Response(200, text='<button name="id" value="1">Another Artist</button>')

    dossier = await lookup(
        TrackQuery(artist="Burial", title="Archangel"),
        LookupConfig(http=HttpSettings(escalation=())),
        include=("nts", "wfmu"),
        transport=httpx.MockTransport(respond),
    )

    assert not dossier.found
    assert {error.source: error.kind for error in dossier.errors} == {
        "nts": ErrorKind.NOT_FOUND,
        "wfmu": ErrorKind.NOT_FOUND,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["nts", "wfmu"])
async def test_radio_search_reports_blocked_source(source: str) -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, headers={"cf-mitigated": "challenge"})

    dossier = await lookup(
        TrackQuery(artist="Burial", title="Archangel"),
        LookupConfig(http=HttpSettings(escalation=(), retries=0)),
        include=(source,),
        transport=httpx.MockTransport(respond),
    )

    assert [(error.source, error.kind) for error in dossier.errors] == [
        (source, ErrorKind.BLOCKED),
    ]


def test_every_adapter_names_a_catalogue_service_or_none() -> None:
    names = {service.name for service in SERVICES}

    adapters = build_adapters(LookupConfig(), HttpResources())

    assert all(adapter.service is None or adapter.service in names for adapter in adapters)


@pytest.mark.parametrize(
    ("source", "text", "resolves"),
    [
        ("whosampled", "https://www.whosampled.com/Daft-Punk/One-More-Time/", True),
        ("whosampled", "https://example.com/?from=whosampled.com", False),
        ("hardwax", "https://hardwax.com/act/burial/", True),
        ("hardwax", "https://www.juno.co.uk/products/x/1-01/", False),
        ("lastfm", "https://www.last.fm/music/Burial/_/Archangel", False),
    ],
)
def test_default_resolves_reads_pages_of_the_adapter_service(
    source: str,
    text: str,
    resolves: bool,
) -> None:
    adapters = {
        adapter.name: adapter for adapter in build_adapters(LookupConfig(), HttpResources())
    }

    assert adapters[source].resolves(parse_query(text)) is resolves


def test_text_query_is_resolved_by_no_adapter() -> None:
    adapters = build_adapters(LookupConfig(), HttpResources())

    assert not any(adapter.resolves(PARANOID_ANDROID) for adapter in adapters)
