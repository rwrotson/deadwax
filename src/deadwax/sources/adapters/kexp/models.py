from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base for KEXP API responses; unknown fields are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class Play(ApiModel):
    """One entry of the KEXP playlist; air breaks have no song."""

    id: int
    airdate: str
    play_type: str | None = None
    show: int | None = None
    artist: str | None = None
    song: str | None = None
    album: str | None = None
    comment: str | None = None


class Plays(ApiModel):
    """One page of plays, latest first."""

    results: list[Play] = []


class Show(ApiModel):
    """Program and hosts of one show."""

    id: int
    program_name: str | None = None
    host_names: list[str] = []
