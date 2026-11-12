from pydantic import SecretStr

from deadwax.sources import (
    DEFAULT_RATES,
    DiscogsSettings,
    LastfmSettings,
    SourcesConfig,
    SourceSettings,
)


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
