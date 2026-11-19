from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from deadwax.sources import (
    BandcampSettings,
    BeatportSettings,
    BoomkatSettings,
    DiscogsSettings,
    Escalation,
    HttpSettings,
    LastfmSettings,
    LookupConfig,
    MusicBrainzSettings,
    PerSourceSettings,
    SourceSettings,
    TracklistsSettings,
)


def test_html_transport_defaults_and_overrides() -> None:
    config = LookupConfig()

    assert config.client_settings("beatport").html_transports[0] is Escalation.NODRIVER
    assert config.client_settings("juno").html_transports[0] is Escalation.IMPERSONATE
    assert config.client_settings("soundohm").html_transports[0] is Escalation.HTTPX

    custom = LookupConfig(
        http=HttpSettings(escalation=(Escalation.NODRIVER,)),
        sources=PerSourceSettings(
            beatport=BeatportSettings(
                html_transports=(Escalation.BROWSER, Escalation.NODRIVER, Escalation.HTTPX),
            ),
        ),
    )
    assert custom.client_settings("beatport").html_transports == (
        Escalation.NODRIVER,
        Escalation.HTTPX,
    )

    restricted = LookupConfig(http=HttpSettings(escalation=()))
    assert restricted.client_settings("norman").html_transports == ()


def test_patchright_is_read_as_browser() -> None:
    settings = SourceSettings.model_validate({"html_transports": ["patchright", "httpx"]})
    http = HttpSettings.model_validate({"escalation": ["patchright"]})

    assert settings.html_transports == (Escalation.BROWSER, Escalation.HTTPX)
    assert http.escalation == (Escalation.BROWSER,)


@pytest.mark.parametrize("steps", [["browser", "patchright"], ["httpx", "httpx"]])
def test_repeated_transports_are_rejected(steps: list[str]) -> None:
    with pytest.raises(ValidationError, match="must be distinct"):
        SourceSettings.model_validate({"html_transports": steps})
    with pytest.raises(ValidationError, match="must be distinct"):
        HttpSettings.model_validate({"escalation": steps})


def test_sources_hold_their_defaults() -> None:
    sources = LookupConfig().sources

    assert (sources.musicbrainz.rate, sources.itunes.rate, sources.tracklists.rate) == (
        1.0,
        0.3,
        0.125,
    )
    assert sources.tracklists.html_transports == (Escalation.BROWSER,)
    assert sources.boomkat.browser_headless is False
    assert sources.bandcamp.browser_headless is None


def test_partial_source_settings_keep_the_other_defaults() -> None:
    config = LookupConfig.model_validate({"sources": {"boomkat": {"enabled": False}}})

    assert config.sources.boomkat == BoomkatSettings(enabled=False)
    assert config.sources.boomkat.rate == 0.5
    assert config.sources.tracklists == TracklistsSettings()


def test_rates_use_source_defaults_and_overrides() -> None:
    config = LookupConfig(sources=PerSourceSettings(musicbrainz=MusicBrainzSettings(rate=0.5)))

    assert config.client_settings("musicbrainz").rate == 0.5
    assert config.client_settings("odesli").rate == 0.5
    assert config.client_settings("lastfm").rate == 4.0
    assert config.client_settings("unknown").rate == 1.0


def test_browser_mode_of_a_source_overrides_the_shared_one() -> None:
    config = LookupConfig(http=HttpSettings(browser_headless=True))

    assert config.client_settings("bandcamp").http.browser_headless
    assert not config.client_settings("boomkat").http.browser_headless


def test_ttl_uses_cache_default_unless_overridden() -> None:
    config = LookupConfig(sources=PerSourceSettings(bandcamp=BandcampSettings(ttl=60)))

    assert config.client_settings("bandcamp").ttl == 60
    assert config.client_settings("discogs").ttl == config.cache.ttl
    assert config.client_settings("http").ttl == config.cache.ttl
    assert config.client_settings("discogs").not_found_ttl == config.cache.not_found_ttl
    assert config.client_settings("discogs").blocked_ttl == config.cache.blocked_ttl


def test_bandcamp_pages_expire_before_their_stream_urls() -> None:
    assert LookupConfig().client_settings("bandcamp").ttl == 12 * 3600


def test_credentials_are_hidden() -> None:
    config = LookupConfig(
        sources=PerSourceSettings(
            discogs=DiscogsSettings(token=SecretStr("t0ken")),
            lastfm=LastfmSettings(api_key=SecretStr("k3y")),
        ),
    )

    assert "t0ken" not in repr(config)
    assert "k3y" not in config.model_dump_json()
    assert config.sources.discogs.token is not None
    assert config.sources.discogs.token.get_secret_value() == "t0ken"


def test_proxy_of_a_source_overrides_the_shared_one() -> None:
    config = LookupConfig.model_validate(
        {
            "sources": {"deezer": {"proxy": "direct"}},
            "http": {"proxy": "http://proxy.example:8080"},
        },
    )

    assert config.client_settings("deezer").proxy_url == "direct"
    assert config.client_settings("discogs").proxy_url == "http://proxy.example:8080"
    assert LookupConfig().client_settings("deezer").proxy_url is None
    assert "8080" not in repr(config.client_settings("discogs"))


def test_proxy_credentials_are_hidden() -> None:
    config = LookupConfig.model_validate({"http": {"proxy": "http://u:s3cret@proxy:8080"}})

    assert "s3cret" not in repr(config)
    assert "s3cret" not in config.model_dump_json()


@pytest.mark.parametrize(
    "proxy",
    ["none", "socks5://proxy:1080", "http://proxy", "http://:8080", "http://proxy:port"],
)
def test_invalid_proxies_are_rejected(proxy: str) -> None:
    with pytest.raises(ValidationError, match="'direct' or an http"):
        LookupConfig.model_validate({"http": {"proxy": proxy}})


@pytest.mark.parametrize(
    ("value", "expected"),
    [("core, shops,", ("core", "shops")), (["radio"], ("radio",)), ("", ())],
)
def test_default_sources_accept_a_comma_separated_string(
    value: object,
    expected: tuple[str, ...],
) -> None:
    config = LookupConfig.model_validate({"default_sources": value})

    assert config.default_sources == expected


def test_default_set_and_concurrency() -> None:
    assert (LookupConfig().default_sources, LookupConfig().concurrency) == (
        (
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
        ),
        8,
    )
    with pytest.raises(ValidationError):
        LookupConfig(concurrency=0)


def test_browser_profiles_must_be_distinct(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="separate profile directories"):
        HttpSettings(
            patchright_profile_dir=tmp_path / "profile",
            nodriver_profile_dir=tmp_path / "profile",
        )
