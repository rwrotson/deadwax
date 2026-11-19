import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from deadwax import ConfigurationError, SourcesConfig
from deadwax.cli.settings import Settings, env_fields, load_settings

ENV_EXAMPLE = Path(__file__).parents[2] / ".env.example"


def test_settings_use_code_defaults() -> None:
    settings = load_settings()

    assert settings.log.level == "INFO"
    assert settings.log.format == "console"
    assert settings.log.dir is None


def test_nested_environment_variables(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DEADWAX_LOG__LEVEL", "WARNING")
    monkeypatch.setenv("DEADWAX_LOG__DIR", str(tmp_path))

    settings = load_settings()

    assert settings.log.level == "WARNING"
    assert settings.log.dir == tmp_path


def test_process_environment_overrides_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    Path(".env").write_text("DEADWAX_LOG__LEVEL=ERROR\nDEADWAX_LOG__FORMAT=json\n")
    monkeypatch.setenv("DEADWAX_LOG__LEVEL", "DEBUG")

    settings = load_settings()

    assert settings.log.level == "DEBUG"
    assert settings.log.format == "json"


def test_empty_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEADWAX_LOG__DIR", "")
    assert load_settings().log.dir is None


def test_invalid_level_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEADWAX_LOG__LEVEL", "LOUD")
    with pytest.raises(ValidationError):
        load_settings()


def test_env_example_parses_to_defaults() -> None:
    assert Settings(_env_file=ENV_EXAMPLE) == Settings()


def test_env_example_documents_every_setting() -> None:
    documented = set(re.findall(r"^#? ?(DEADWAX_[A-Z_]+)=", ENV_EXAMPLE.read_text(), re.MULTILINE))
    settings = {name for name, _ in env_fields()}

    assert settings - documented == set(), "add new settings to .env.example"
    assert documented - settings == set(), "remove stale settings from .env.example"


def test_every_setting_has_a_description() -> None:
    assert [name for name, field in env_fields() if not field.description] == []


def test_toml_file_sits_below_environment_and_flags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = tmp_path / "deadwax.toml"
    config.write_text("adapter_timeout = 9\n[http]\nretries = 1\ntimeout = 5\n[cache]\nttl = 60\n")
    monkeypatch.setenv("DEADWAX_HTTP__RETRIES", "2")

    settings = load_settings(config, cache={"enabled": False})

    assert settings.adapter_timeout == 9
    assert (settings.http.retries, settings.http.timeout) == (2, 5)
    assert (settings.cache.ttl, settings.cache.enabled) == (60, False)


def test_config_file_from_the_environment_and_the_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_user_dirs: Path,
) -> None:
    named = tmp_path / "named.toml"
    named.write_text("[lastfm]\napi_key = 'k'\n")
    isolated_user_dirs.parent.mkdir()
    isolated_user_dirs.write_text("[itunes]\nenabled = false\n")

    default = load_settings()
    monkeypatch.setenv("DEADWAX_CONFIG_FILE", str(named))
    from_environment = load_settings()

    assert not default.itunes.enabled
    assert from_environment.itunes.enabled
    assert from_environment.lastfm.api_key is not None


def test_named_config_file_must_exist(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="configuration file not found"):
        load_settings(tmp_path / "missing.toml")


def test_settings_cover_the_library_configuration(tmp_path: Path) -> None:
    settings = load_settings(cache={"path": str(tmp_path / "own.sqlite")}, odesli={"rate": 2})

    config = settings.sources_config()

    assert set(SourcesConfig.model_fields) <= set(Settings.model_fields)
    assert config.cache.path == tmp_path / "own.sqlite"
    assert config.odesli.rate == 2
    assert load_settings().sources_config().cache.path == tmp_path / "cache.sqlite"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("core, shops,", ("core", "shops")), ("musicbrainz", ("musicbrainz",))],
)
def test_default_sources_from_a_comma_separated_variable(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    expected: tuple[str, ...],
) -> None:
    monkeypatch.setenv("DEADWAX_DEFAULT_SOURCES", value)
    monkeypatch.setenv("DEADWAX_CONCURRENCY", "3")

    config = load_settings().sources_config()

    assert (config.default_sources, config.concurrency) == (expected, 3)


def test_default_sources_from_a_toml_list(tmp_path: Path) -> None:
    config = tmp_path / "deadwax.toml"
    config.write_text('default_sources = ["core", "radio"]\n')

    assert load_settings(config).default_sources == ("core", "radio")


def test_default_source_set_matches_the_library() -> None:
    assert load_settings().default_sources == SourcesConfig().default_sources
    assert "deezer" not in load_settings().default_sources
