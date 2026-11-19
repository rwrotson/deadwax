from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base for Spotify Web API responses; unknown fields are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class Token(ApiModel):
    """Access token of the client credentials flow."""

    access_token: str


class ExternalUrls(ApiModel):
    """Web pages of an object."""

    spotify: str | None = None


class ExternalIds(ApiModel):
    """Codes of a track or album; development-mode apps may get none."""

    isrc: str | None = None
    upc: str | None = None


class Artist(ApiModel):
    """Artist credited on a track or album."""

    id: str | None = None
    name: str
    external_urls: ExternalUrls = ExternalUrls()


class Copyright(ApiModel):
    """Copyright line: type 'C' for ©, 'P' for ℗."""

    text: str
    type: str | None = None


class AlbumRef(ApiModel):
    """Album as a track or a search lists it."""

    id: str
    name: str
    href: str | None = None
    album_type: str | None = None
    release_date: str | None = None
    artists: list[Artist] = []
    external_urls: ExternalUrls = ExternalUrls()


class Album(AlbumRef):
    """Full album."""

    label: str | None = None
    popularity: int | None = None
    copyrights: list[Copyright] = []
    external_ids: ExternalIds = ExternalIds()


class Track(ApiModel):
    """Track from a lookup or a search."""

    id: str
    name: str
    href: str | None = None
    artists: list[Artist] = []
    album: AlbumRef | None = None
    popularity: int | None = None
    preview_url: str | None = None
    external_ids: ExternalIds = ExternalIds()
    external_urls: ExternalUrls = ExternalUrls()


class TrackPage(ApiModel):
    """One page of track search results."""

    items: list[Track | None] = []


class AlbumPage(ApiModel):
    """One page of album search results."""

    items: list[AlbumRef | None] = []


class SearchResults(ApiModel):
    """Answer of the search endpoint."""

    tracks: TrackPage = TrackPage()
    albums: AlbumPage = AlbumPage()
