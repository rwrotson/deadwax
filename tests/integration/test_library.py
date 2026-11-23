import os

import pytest
from pydantic import SecretStr

from deadwax import (
    ArtistIdentity,
    Dossier,
    EntityKind,
    ErrorKind,
    IdKind,
    LabelIdentity,
    LookupConfig,
    PerSourceSettings,
    RecordIdentity,
    TextKind,
    TrackQuery,
    lookup,
    parse_query,
    parse_title,
)
from deadwax.core import RecordKey, Verdict, compare
from deadwax.sources import (
    DiscogsSettings,
    GeniusSettings,
    LastfmSettings,
    SoundCloudSettings,
    SpotifySettings,
    YouTubeSettings,
)

# Read at import (`poe test-live` loads .env): the autouse fixture removes DEADWAX_* variables
# before each test.
DISCOGS_TOKEN = os.environ.get("DEADWAX_SOURCES__DISCOGS__TOKEN")
LASTFM_KEY = os.environ.get("DEADWAX_SOURCES__LASTFM__API_KEY")
SPOTIFY_ID = os.environ.get("DEADWAX_SOURCES__SPOTIFY__CLIENT_ID")
SPOTIFY_SECRET = os.environ.get("DEADWAX_SOURCES__SPOTIFY__CLIENT_SECRET")
YOUTUBE_KEY = os.environ.get("DEADWAX_SOURCES__YOUTUBE__API_KEY")
SOUNDCLOUD_ID = os.environ.get("DEADWAX_SOURCES__SOUNDCLOUD__CLIENT_ID")
GENIUS_TOKEN = os.environ.get("DEADWAX_SOURCES__GENIUS__TOKEN")

# Keep the library corpus on the sources qualified for this live suite.
LIBRARY_SOURCES = (
    "musicbrainz",
    "itunes",
    "odesli",
    "bandcamp",
    "wikipedia",
    "lastfm",
    "discogs",
    "listenbrainz",
    "secondhandsongs",
    "kexp",
    "spotify",
    "youtube",
    "genius",
    "soundcloud",
)

# Tracks from a personal library as "Artist - Title" from their tags. Tracks of compilations
# tagged "Various Artists" use the artist from the title, and an untagged file its name.
LIBRARY: dict[str, str] = {
    "ambarchi_salt": "Oren Ambarchi - Salt",
    "hainbach_btm_blau": "Hainbach - BTM Blau",
    "deadbeat_blue_moon": "Deadbeat, Camara - Blue Moon Revisited (Song for Elvis)",
    "open_yellow_circle": "Open Yellow Circle, O Yuki Conjugate - Dark Blue Trees",
    "jason_gibbs_starlings": "E. Jason Gibbs - Mostly Starlings Before a Storm (For Steffen)",
    "marble_oscar": "Marble - Oscar",
    "vlasenko_untitled": "Ilya Vlasenko feat. Sasha Hilko - untitled",
    # The release spells the title with a Latin "i" among Cyrillic letters, as tagged.
    "kollezhsky_asessor": "Коллежский асессор - Убывство хрыстiанина",  # noqa: RUF001
    "picture_leeeeeee": "Picture - Leeeeeee",
    "stuk_bambuka": "Стук Бамбука в XI Часов - Лоскуток",
    "albert_hammond": "Albert Hammond - I Was Blue",
    "premature_ejaculation": "Premature Ejaculation - Pruguelknaben",
    "vantzou_hot_springs": "Christina Vantzou - Hot Springs (Ft Ezra Fieremans)",
    "suzanne_kraft_nordsee": "Suzanne Kraft - Nordsee",
    "teresa_winter": "Teresa Winter - No Love Is Sorrow",
    "us_girls_junkyard": "U.S. Girls - Junkyard",
    "codeine_promise_of_love": "Codeine - Promise Of Love",
    "codeine_d": "Codeine - D",
    "jeff_bridges": "Jeff Bridges - Hummmmmm",
    "spiritualized_shine_a_light": "Spiritualized - Shine a Light (Clear Light-Clear Rush)",
    "jeff_buckley_sky_blue_skin": "Jeff Buckley - Sky Blue Skin",
    "basinski_and_blue_again": (
        "Camilla Sparksss, William Basinski, Gary Thomas Wright - "
        "And Blue Again (Remix by William Basinski and Gary Wright)"
    ),
}


def _secret(value: str | None) -> SecretStr | None:
    return SecretStr(value) if value else None


def live_config() -> LookupConfig:
    """Default settings, with every source's credential from the environment."""
    return LookupConfig(
        sources=PerSourceSettings(
            discogs=DiscogsSettings(token=_secret(DISCOGS_TOKEN)),
            lastfm=LastfmSettings(api_key=_secret(LASTFM_KEY)),
            spotify=SpotifySettings(
                client_id=_secret(SPOTIFY_ID),
                client_secret=_secret(SPOTIFY_SECRET),
            ),
            youtube=YouTubeSettings(api_key=_secret(YOUTUBE_KEY)),
            soundcloud=SoundCloudSettings(client_id=_secret(SOUNDCLOUD_ID)),
            genius=GeniusSettings(token=_secret(GENIUS_TOKEN)),
        ),
    )


def summary(name: str, dossier: Dossier) -> str:
    """One report line: what was found, by whom, and which sources gave up."""
    identity = dossier.identity
    found = "not found"
    if isinstance(identity, RecordIdentity) and identity.title and identity.artist:
        by = ",".join(sorted({s.source for s in identity.title.sources}))
        record = f"{identity.artist.value} - {identity.title.value}"
        found = f"{record} [{identity.version.kind}] by {by}"
    elif isinstance(identity, ArtistIdentity | LabelIdentity) and identity.name:
        by = ",".join(sorted({s.source for s in identity.name.sources}))
        found = f"{identity.name.value} [{identity.kind}] by {by}"
    counts = (
        f"tags {len(dossier.tags)}, credits {len(dossier.credits)}, texts {len(dossier.texts)}, "
        f"relations {len(dossier.relations)}, links {len(dossier.links)}"
    )
    errors = ", ".join(f"{e.source}:{e.kind}" for e in dossier.errors) or "none"
    return f"{name}: {found}; {counts}; errors: {errors}"


def assert_name_lookup(
    dossier: Dossier,
    identity: ArtistIdentity | LabelIdentity,
    mbid: IdKind,
) -> None:
    assert dossier.found
    assert any(external.kind is mbid and external.value for external in identity.external_ids)
    assert ErrorKind.UNSUPPORTED not in {error.kind for error in dossier.errors}
    facts = [
        *dossier.tags,
        *dossier.credits,
        *dossier.texts,
        *dossier.relations,
        *dossier.metrics,
        *dossier.links,
        *dossier.review_links,
        *identity.external_ids,
        *(value for discrepancy in identity.discrepancies for value in discrepancy.values),
        identity.name,
        identity.disambiguation,
        identity.country,
        identity.location,
        identity.begin,
        identity.end,
        identity.type if isinstance(identity, ArtistIdentity) else None,
    ]
    for fact in facts:
        if fact is not None:
            assert fact.sources, fact
            assert all(source.source and source.url for source in fact.sources), fact


@pytest.mark.enable_socket
@pytest.mark.timeout(120)
@pytest.mark.parametrize(
    ("text", "kind"),
    [
        pytest.param("Aphex Twin", EntityKind.ARTIST, id="aphex_twin"),
        pytest.param("Burial", EntityKind.ARTIST, id="burial"),
        pytest.param("Кино", EntityKind.ARTIST, id="kino"),
        pytest.param(
            "https://musicbrainz.org/artist/f22942a1-6f70-4f48-866e-238cb2308fbd",
            None,
            id="musicbrainz_artist_url",
        ),
    ],
)
@pytest.mark.asyncio
async def test_artist_lookup(
    text: str,
    kind: EntityKind | None,
    request: pytest.FixtureRequest,
    live_report: list[str],
) -> None:
    dossier = await lookup(parse_query(text, kind), live_config())

    live_report.append(summary(request.node.callspec.id, dossier))
    assert isinstance(dossier.identity, ArtistIdentity)
    assert_name_lookup(dossier, dossier.identity, IdKind.MUSICBRAINZ_ARTIST)


@pytest.mark.enable_socket
@pytest.mark.timeout(120)
@pytest.mark.parametrize("name", ["Warp", "Hyperdub"], ids=["warp", "hyperdub"])
@pytest.mark.asyncio
async def test_label_lookup(name: str, live_report: list[str]) -> None:
    dossier = await lookup(parse_query(name, EntityKind.LABEL), live_config())

    live_report.append(summary(name, dossier))
    assert isinstance(dossier.identity, LabelIdentity)
    assert_name_lookup(dossier, dossier.identity, IdKind.MUSICBRAINZ_LABEL)


@pytest.mark.enable_socket
@pytest.mark.timeout(600)
@pytest.mark.parametrize("text", LIBRARY.values(), ids=list(LIBRARY))
@pytest.mark.asyncio
async def test_library_track(
    text: str,
    request: pytest.FixtureRequest,
    live_report: list[str],
) -> None:
    query = parse_query(text, EntityKind.TRACK)

    dossier = await lookup(query, live_config(), include=LIBRARY_SOURCES)

    live_report.append(summary(request.node.callspec.id, dossier))
    assert [e for e in dossier.errors if e.kind is ErrorKind.FAILED] == []
    facts = [*dossier.tags, *dossier.credits, *dossier.texts, *dossier.relations, *dossier.links]
    assert all(fact.sources for fact in facts)
    identity = dossier.identity
    assert isinstance(identity, RecordIdentity)
    if identity.artist is None or identity.title is None:
        return
    assert isinstance(query, TrackQuery)
    assert query.artist is not None
    assert query.title is not None
    reference = RecordKey(query.artist, query.title, EntityKind.TRACK)
    found = RecordKey(
        identity.artist.value,
        identity.title.value,
        EntityKind.TRACK,
        identity.version,
    )
    assert compare(reference, found).verdict is Verdict.MATCH
    assert identity.version.kind is parse_title(query.title).version.kind
    if not query.artist.isascii():
        assert not identity.artist.value.isascii(), "non-Latin names are not transliterated"


@pytest.mark.enable_socket
@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_genius_song(live_report: list[str]) -> None:
    if GENIUS_TOKEN is None:
        pytest.skip("Genius token is unavailable")
    query = parse_query("Kanye West - Stronger", EntityKind.TRACK)
    dossier = await lookup(query, live_config(), include=["genius"])

    live_report.append(summary("genius_stronger", dossier))
    assert dossier.found
    assert dossier.credits
    assert dossier.relations
    assert any(text.kind is TextKind.USER for text in dossier.texts)
    assert any(text.kind is TextKind.LYRICS and text.body for text in dossier.texts)
