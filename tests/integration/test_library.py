import os

import pytest
from pydantic import SecretStr

from deadwax import (
    DiscogsSettings,
    Dossier,
    EntityKind,
    ErrorKind,
    SourcesConfig,
    lookup,
    parse_query,
    parse_title,
)
from deadwax.core import RecordKey, Verdict, compare

# Read at import: the autouse fixture removes DEADWAX_* variables before each test.
DISCOGS_TOKEN = os.environ.get("DEADWAX_DISCOGS__TOKEN")

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


def live_config() -> SourcesConfig:
    """Default settings, with the Discogs token from the environment if set."""
    token = SecretStr(DISCOGS_TOKEN) if DISCOGS_TOKEN else None
    return SourcesConfig(discogs=DiscogsSettings(token=token))


def summary(name: str, dossier: Dossier) -> str:
    """One report line: what was found, by whom, and which sources gave up."""
    identity = dossier.identity
    if identity.title is None or identity.artist is None:
        found = "not found"
    else:
        by = ",".join(sorted({s.source for s in identity.title.sources}))
        record = f"{identity.artist.value} - {identity.title.value}"
        found = f"{record} [{identity.version.kind}] by {by}"
    counts = (
        f"tags {len(dossier.tags)}, credits {len(dossier.credits)}, texts {len(dossier.texts)}, "
        f"relations {len(dossier.relations)}, links {len(dossier.links)}"
    )
    errors = ", ".join(f"{e.source}:{e.kind}" for e in dossier.errors) or "none"
    return f"{name}: {found}; {counts}; errors: {errors}"


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

    dossier = await lookup(query, live_config())

    live_report.append(summary(request.node.callspec.id, dossier))
    assert [e for e in dossier.errors if e.kind is ErrorKind.FAILED] == []
    facts = [*dossier.tags, *dossier.credits, *dossier.texts, *dossier.relations, *dossier.links]
    assert all(fact.sources for fact in facts)
    identity = dossier.identity
    if identity.artist is None or identity.title is None:
        return
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
