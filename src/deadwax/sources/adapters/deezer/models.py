from pydantic import BaseModel, ConfigDict


class _Api(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class Named(_Api):
    """Artist, genre, or album reference."""

    id: int | None = None
    name: str | None = None
    title: str | None = None
    link: str | None = None


class Genres(_Api):
    """Genre list of an album."""

    data: list[Named] = []


class Track(_Api):
    """Track from a lookup or a search."""

    id: int
    title: str
    isrc: str | None = None
    link: str | None = None
    preview: str | None = None
    release_date: str | None = None
    artist: Named
    album: Named | None = None


class Album(_Api):
    """Album from a lookup or a search."""

    id: int
    title: str
    upc: str | None = None
    link: str | None = None
    label: str | None = None
    release_date: str | None = None
    artist: Named
    genres: Genres = Genres()
