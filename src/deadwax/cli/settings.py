import os
from collections.abc import Iterator
from contextvars import ContextVar
from pathlib import Path
from typing import Annotated

from platformdirs import user_cache_path, user_config_path, user_log_path
from pydantic import BaseModel, BeforeValidator, Field
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from deadwax import (
    CacheSettings,
    ConfigurationError,
    DiscogsSettings,
    GeniusSettings,
    HttpSettings,
    LastfmSettings,
    SecondHandSongsSettings,
    SoundCloudSettings,
    SourcesConfig,
    SourceSettings,
    SpotifySettings,
    YouTubeSettings,
)
from deadwax.logs import LogSettings, RunLogSettings

APP_NAME = "deadwax"
CONFIG_FILE_VARIABLE = "DEADWAX_CONFIG_FILE"

# The library's default source set, shown and used when DEADWAX_DEFAULT_SOURCES is unset.
_DEFAULT_SOURCES: tuple[str, ...] = SourcesConfig.model_fields["default_sources"].default

# TOML file that load_settings() adds below the environment and .env for one load.
_toml_file: ContextVar[Path | None] = ContextVar("deadwax_toml_file", default=None)


def _split_names(value: object) -> object:
    if isinstance(value, str):
        return tuple(name.strip() for name in value.split(",") if name.strip())
    return value


class Settings(BaseSettings):
    """Load command settings from flags, DEADWAX_* variables, .env, and a TOML file."""

    model_config = SettingsConfigDict(
        env_prefix="DEADWAX_",
        env_file=".env",
        env_nested_delimiter="__",
        env_ignore_empty=True,
        extra="ignore",
    )

    config_file: Path | None = Field(
        default=None,
        description="TOML file with settings; read from the process environment or --config "
        "only. Default: config.toml in the user configuration directory",
    )
    adapter_timeout: float = Field(default=30.0, gt=0, description="Seconds per source lookup")

    # NoDecode: the environment gives a comma-separated string, not JSON.
    default_sources: Annotated[tuple[str, ...], NoDecode, BeforeValidator(_split_names)] = Field(
        default=_DEFAULT_SOURCES,
        description="Source and group names a lookup runs when --sources is not given",
    )

    concurrency: int = Field(default=8, ge=1, description="Sources queried at once in a lookup")
    log: LogSettings = Field(default_factory=LogSettings)
    runs: RunLogSettings = Field(default_factory=RunLogSettings)
    http: HttpSettings = Field(default_factory=HttpSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    musicbrainz: SourceSettings = Field(default_factory=SourceSettings)
    itunes: SourceSettings = Field(default_factory=SourceSettings)
    deezer: SourceSettings = Field(default_factory=SourceSettings)
    odesli: SourceSettings = Field(default_factory=SourceSettings)
    discogs: DiscogsSettings = Field(default_factory=DiscogsSettings)
    bandcamp: SourceSettings = Field(default_factory=SourceSettings)
    lastfm: LastfmSettings = Field(default_factory=LastfmSettings)
    wikipedia: SourceSettings = Field(default_factory=SourceSettings)
    listenbrainz: SourceSettings = Field(default_factory=SourceSettings)
    secondhandsongs: SecondHandSongsSettings = Field(default_factory=SecondHandSongsSettings)
    kexp: SourceSettings = Field(default_factory=SourceSettings)
    spotify: SpotifySettings = Field(default_factory=SpotifySettings)
    youtube: YouTubeSettings = Field(default_factory=YouTubeSettings)
    genius: GeniusSettings = Field(default_factory=GeniusSettings)
    soundcloud: SoundCloudSettings = Field(default_factory=SoundCloudSettings)
    beatport: SourceSettings = Field(default_factory=SourceSettings)
    hardwax: SourceSettings = Field(default_factory=SourceSettings)
    soundohm: SourceSettings = Field(default_factory=SourceSettings)
    juno: SourceSettings = Field(default_factory=SourceSettings)
    bleep: SourceSettings = Field(default_factory=SourceSettings)
    forcedexposure: SourceSettings = Field(default_factory=SourceSettings)
    allmusic: SourceSettings = Field(default_factory=SourceSettings)
    albumoftheyear: SourceSettings = Field(default_factory=SourceSettings)
    pressreviews: SourceSettings = Field(default_factory=SourceSettings)
    residentadvisor: SourceSettings = Field(default_factory=SourceSettings)
    nts: SourceSettings = Field(default_factory=SourceSettings)
    wfmu: SourceSettings = Field(default_factory=SourceSettings)
    rateyourmusic: SourceSettings = Field(default_factory=SourceSettings)
    whosampled: SourceSettings = Field(default_factory=SourceSettings)
    phonica: SourceSettings = Field(default_factory=SourceSettings)
    boomkat: SourceSettings = Field(
        default_factory=lambda: SourceSettings(browser_headless=False),
    )
    norman: SourceSettings = Field(
        default_factory=lambda: SourceSettings(browser_headless=False),
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,  # noqa: ARG003 -- base signature
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Read flags, then the environment, then .env, then the TOML file if one is set."""
        toml_file = _toml_file.get()
        if toml_file is None:
            return init_settings, env_settings, dotenv_settings
        toml = TomlConfigSettingsSource(settings_cls, toml_file=toml_file)
        return init_settings, env_settings, dotenv_settings, toml

    def sources_config(self) -> SourcesConfig:
        """Build the library configuration; the cache lives in the user cache directory."""
        cache = self.cache
        if cache.path is None:
            cache = cache.model_copy(update={"path": default_cache_file()})
        fields = {name: getattr(self, name) for name in SourcesConfig.model_fields}
        return SourcesConfig.model_validate(fields | {"cache": cache})

    def run_log(self) -> RunLogSettings:
        """Build the run journal settings; the journal lives in the user log directory."""
        if self.runs.dir is not None:
            return self.runs
        return self.runs.model_copy(update={"dir": default_log_dir()})


def default_config_file() -> Path:
    """Return config.toml in the user configuration directory."""
    return user_config_path(APP_NAME) / "config.toml"


def default_cache_file() -> Path:
    """Return the response cache in the user cache directory."""
    return user_cache_path(APP_NAME) / "responses.sqlite"


def default_log_dir() -> Path:
    """Return the user log directory, which holds the run journal."""
    return user_log_path(APP_NAME)


def nested_model(field: FieldInfo) -> type[BaseModel] | None:
    """Return the settings model of a nested section, if the field is one."""
    for candidate in getattr(field.annotation, "__args__", (field.annotation,)):
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            return candidate
    return None


def env_fields(
    model: type[BaseModel] = Settings,
    prefix: str = "DEADWAX_",
) -> Iterator[tuple[str, FieldInfo]]:
    """Yield every leaf setting with its environment variable name."""
    for name, field in model.model_fields.items():
        variable = f"{prefix}{name.upper()}"
        section = nested_model(field)
        if section is None:
            yield variable, field
        else:
            yield from env_fields(section, f"{variable}__")


def load_settings(config_file: Path | None = None, **overrides: object) -> Settings:
    """Load settings; `overrides` come from command-line flags and win over every file.

    An explicitly named TOML file must exist; the default one is optional.
    """
    explicit = config_file or os.environ.get(CONFIG_FILE_VARIABLE) or None
    path = Path(explicit) if explicit else default_config_file()
    if explicit and not path.is_file():
        raise ConfigurationError(f"configuration file not found: {path}")
    token = _toml_file.set(path)
    try:
        return Settings(**overrides)  # type: ignore[arg-type]  # overrides are field values
    finally:
        _toml_file.reset(token)
