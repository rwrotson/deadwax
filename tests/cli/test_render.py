import json

import pytest
from rich.console import Console

from deadwax import (
    Capability,
    Dossier,
    Pass,
    Query,
    Requirement,
    SourceGroup,
    SourceInfo,
    SourceState,
    SourceStatus,
)
from deadwax.cli.render import OutputFormat, env_variable, print_dossier, print_sources


def rendered(dossier: Dossier, output: OutputFormat = OutputFormat.PRETTY) -> str:
    console = Console(record=True, width=1000)
    print_dossier(dossier, output, console)
    return console.export_text()


def test_pretty_dossier_shows_every_section_with_sources(dossier: Dossier) -> None:
    text = rendered(dossier)

    assert text.startswith("Everything but the Girl — Missing")
    for section in ("Identity", "Tags", "Credits", "Texts", "Relations", "Links", "Errors"):
        assert f"\n{section}\n" in text
    assert "remix (Todd Terry remix)" in text
    assert "Blanco y Negro, NEG84CD" in text
    assert "sources disagree on date: 1995 (musicbrainz) ≠ 1994 (itunes)" in text
    assert "recording genres: house — musicbrainz" in text
    assert "review · Missing · Example Weekly · A. Critic · 1995-10-01 · rating 4/5" in text
    assert "rating B+" in text
    assert "x" * 600 + "…" in text
    assert "x" * 601 not in text
    assert "remix of\n  Missing (the song this recording performs) — musicbrainz" in text
    assert "Now 32 (Various, 1995)" in text
    assert "blocked" in text


def test_each_source_is_named_once_per_fact(dossier: Dossier) -> None:
    assert "musicbrainz, itunes" in rendered(dossier)


def test_nothing_matched(dossier: Dossier) -> None:
    empty = Dossier(
        query=Query(url="https://example.org/x"),
        identity={},  # type: ignore[arg-type]
        generated_at=dossier.generated_at,
    )

    assert rendered(empty).strip() == "Nothing matched the query"


def test_untitled_artist_is_omitted(dossier: Dossier) -> None:
    identity = dossier.identity.model_copy(update={"artist": None})

    assert rendered(dossier.model_copy(update={"identity": identity})).startswith("Missing\n")


def test_json_and_markdown(dossier: Dossier) -> None:
    assert Dossier.model_validate_json(rendered(dossier, OutputFormat.JSON)) == dossier
    assert rendered(dossier, OutputFormat.MARKDOWN).startswith(
        "# Everything but the Girl — Missing",
    )


INFOS = [
    SourceInfo(
        source="musicbrainz",
        group=SourceGroup.CORE,
        default=True,
        pass_=Pass.IDENTITY,
        capabilities=[Capability.IDENTITY, Capability.LINKS],
        requires=[],
        status=SourceStatus(source="musicbrainz", state=SourceState.READY),
    ),
    SourceInfo(
        source="lastfm",
        group=SourceGroup.CORE,
        default=True,
        pass_=Pass.ENRICH,
        capabilities=[Capability.TAGS],
        requires=[Requirement(setting="lastfm.api_key", purpose="every lookup")],
        status=SourceStatus(source="lastfm", state=SourceState.MISSING_CREDENTIAL, detail="x"),
    ),
    SourceInfo(
        source="bandcamp",
        group=SourceGroup.CORE,
        default=True,
        pass_=Pass.ENRICH,
        capabilities=[],
        requires=[],
        status=SourceStatus(
            source="bandcamp",
            state=SourceState.MISSING_EXTRA,
            detail="deadwax[browser]",
        ),
    ),
    SourceInfo(
        source="itunes",
        group=SourceGroup.CORE,
        default=False,
        pass_=Pass.ENRICH,
        capabilities=[],
        requires=[],
        status=SourceStatus(source="itunes", state=SourceState.DISABLED),
    ),
]


@pytest.mark.parametrize("output", list(OutputFormat))
def test_sources(output: OutputFormat) -> None:
    console = Console(record=True, width=200)

    print_sources(INFOS, output, console)
    text = console.export_text()

    if output is OutputFormat.JSON:
        assert [row["source"] for row in json.loads(text)] == [
            "musicbrainz",
            "lastfm",
            "bandcamp",
            "itunes",
        ]
        assert {(row["group"], row["default"]) for row in json.loads(text)} == {
            ("core", True),
            ("core", False),
        }
    else:
        assert "missing DEADWAX_LASTFM__API_KEY" in text
        assert "missing extra: deadwax[browser]" in text
        assert "disabled" in text
        assert "identity, links" in text
        assert "core" in text
        assert "yes" in text


def test_env_variable() -> None:
    assert env_variable("discogs.token") == "DEADWAX_DISCOGS__TOKEN"
