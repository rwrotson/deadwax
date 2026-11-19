from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from deadwax.sources import (
    DEFAULT_RATES,
    DiscogsSettings,
    Escalation,
    HttpSettings,
    LastfmSettings,
    SourcesConfig,
    SourceSettings,
)


def test_html_transport_defaults_and_overrides() -> None:
    config = SourcesConfig()

    assert config.html_transports("beatport")[0] is Escalation.NODRIVER
    assert config.html_transports("juno")[0] is Escalation.IMPERSONATE
    assert config.html_transports("soundohm")[0] is Escalation.HTTPX

    custom = SourcesConfig(
        http=HttpSettings(escalation=(Escalation.NODRIVER,)),
        beatport=SourceSettings(
            html_transports=(Escalation.BROWSER, Escalation.NODRIVER, Escalation.HTTPX),
        ),
    )
    assert custom.html_transports("beatport") == (Escalation.NODRIVER, Escalation.HTTPX)

    restricted = SourcesConfig(http=HttpSettings(escalation=()))
    assert restricted.html_transports("norman") == ()


def test_rates_use_source_defaults_and_overrides() -> None:
    config = SourcesConfig(musicbrainz=SourceSettings(rate=0.5))

    assert config.rate("musicbrainz") == 0.5
    assert config.rate("odesli") == DEFAULT_RATES["odesli"]
    assert config.rate("unknown") == 1.0


def test_ttl_uses_cache_default_unless_overridden() -> None:
    config = SourcesConfig(bandcamp=SourceSettings(ttl=60))

    assert config.ttl("bandcamp") == 60
    assert config.ttl("discogs") == config.cache.ttl
    assert config.ttl("http") == config.cache.ttl


def test_credentials_are_hidden() -> None:
    config = SourcesConfig(
        discogs=DiscogsSettings(token=SecretStr("t0ken")),
        lastfm=LastfmSettings(api_key=SecretStr("k3y")),
    )

    assert "t0ken" not in repr(config)
    assert "k3y" not in config.model_dump_json()
    assert config.discogs.token is not None
    assert config.discogs.token.get_secret_value() == "t0ken"


def test_proxy_of_a_source_overrides_the_shared_one() -> None:
    config = SourcesConfig.model_validate(
        {"http": {"proxy": "http://proxy.example:8080"}, "deezer": {"proxy": "direct"}},
    )

    assert config.proxy("deezer") == "direct"
    assert config.proxy("discogs") == "http://proxy.example:8080"
    assert SourcesConfig().proxy("deezer") is None


def test_proxy_credentials_are_hidden() -> None:
    config = SourcesConfig.model_validate({"http": {"proxy": "http://u:s3cret@proxy:8080"}})

    assert "s3cret" not in repr(config)
    assert "s3cret" not in config.model_dump_json()


@pytest.mark.parametrize(
    "proxy",
    ["none", "socks5://proxy:1080", "http://proxy", "http://:8080", "http://proxy:port"],
)
def test_invalid_proxies_are_rejected(proxy: str) -> None:
    with pytest.raises(ValidationError, match="'direct' or an http"):
        SourcesConfig.model_validate({"http": {"proxy": proxy}})


@pytest.mark.parametrize(
    ("value", "expected"),
    [("core, shops,", ("core", "shops")), (["radio"], ("radio",)), ("", ())],
)
def test_default_sources_accept_a_comma_separated_string(
    value: object,
    expected: tuple[str, ...],
) -> None:
    config = SourcesConfig.model_validate({"default_sources": value})

    assert config.default_sources == expected


def test_default_set_and_concurrency() -> None:
    assert (SourcesConfig().default_sources, SourcesConfig().concurrency) == (
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
        SourcesConfig(concurrency=0)


def test_browser_profiles_must_be_distinct(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="separate profile directories"):
        HttpSettings(
            patchright_profile_dir=tmp_path / "profile",
            nodriver_profile_dir=tmp_path / "profile",
        )
