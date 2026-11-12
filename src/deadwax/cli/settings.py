import os
from collections.abc import Iterator
from contextvars import ContextVar
from pathlib import Path

from platformdirs import user_cache_path, user_config_path
from pydantic import BaseModel, Field
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from deadwax import (
    CacheSettings,
    ConfigurationError,
    DiscogsSettings,
    HttpSettings,
    LastfmSettings,
    OdesliSettings,
    SourcesConfig,
    SourceSettings,
)
from deadwax.logs import LogSettings

APP_NAME = "deadwax"
CONFIG_FILE_VARIABLE = "DEADWAX_CONFIG_FILE"

# TOML file that load_settings() adds below the environment and .env for one load.
_toml_file: ContextVar[Path | None] = ContextVar("deadwax_toml_file", default=None)


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
    log: LogSettings = Field(default_factory=LogSettings)
    http: HttpSettings = Field(default_factory=HttpSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    musicbrainz: SourceSettings = Field(default_factory=SourceSettings)
    itunes: SourceSettings = Field(default_factory=SourceSettings)
    deezer: SourceSettings = Field(default_factory=SourceSettings)
    odesli: OdesliSettings = Field(default_factory=OdesliSettings)
    discogs: DiscogsSettings = Field(default_factory=DiscogsSettings)
    bandcamp: SourceSettings = Field(default_factory=SourceSettings)
    lastfm: LastfmSettings = Field(default_factory=LastfmSettings)
    wikipedia: SourceSettings = Field(default_factory=SourceSettings)

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


def default_config_file() -> Path:
    """Return config.toml in the user configuration directory."""
    return user_config_path(APP_NAME) / "config.toml"


def default_cache_file() -> Path:
    """Return the response cache in the user cache directory."""
    return user_cache_path(APP_NAME) / "responses.sqlite"


def nested_model(field: FieldInfo) -> type[BaseModel] | None:
    """Return the settings model of a nested section, if the field is one."""
    for candidate in getattr(field.annotation, "__args__", (field.annotation,)):
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            return candidate
    return None


def env_fields(
    model: type[BaseModel] = Settings, prefix: str = "DEADWAX_"
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
