from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _as_list(value: Any) -> Any:  # noqa: ANN401 -- raw JSON before validation
    """Last.fm sends one item as an object and no items as an empty string."""
    if value in ("", None):
        return []
    if isinstance(value, dict):
        return [value]
    return value


def _as_object(value: Any) -> Any:  # noqa: ANN401 -- raw JSON before validation
    """Last.fm sends an empty container as an empty string."""
    return {} if value in ("", None) else value


class ApiModel(BaseModel):
    """Base for Last.fm API responses; unknown fields are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)


class Envelope(ApiModel):
    """Any response, checked for an error first."""

    error: int | None = None
    message: str = ""


class Wiki(ApiModel):
    """User-contributed wiki text of a track or album."""

    published: str | None = None
    summary: str = ""
    content: str = ""


class Named(ApiModel):
    """Artist reference with its page."""

    name: str
    url: str | None = None


class Tag(ApiModel):
    """Tag with its relative count (0-100) among the item's tags."""

    name: str
    count: int = 0
    url: str | None = None


class TopTags(ApiModel):
    """Tags of an item, most used first."""

    tag: Annotated[list[Tag], BeforeValidator(_as_list)] = []


class TopTagsResponse(ApiModel):
    """Response of the getTopTags methods."""

    toptags: Annotated[TopTags, BeforeValidator(_as_object)] = TopTags()


class TrackInfo(ApiModel):
    """Track as Last.fm knows it."""

    name: str
    url: str | None = None
    artist: Named
    wiki: Wiki | None = None


class TrackInfoResponse(ApiModel):
    """Response of track.getInfo."""

    track: TrackInfo


class AlbumInfo(ApiModel):
    """Album as Last.fm knows it; its artist is a plain name."""

    name: str
    artist: str
    url: str | None = None
    wiki: Wiki | None = None


class AlbumInfoResponse(ApiModel):
    """Response of album.getInfo."""

    album: AlbumInfo


class SimilarTrack(ApiModel):
    """Track listened to by the same people, with a 0-1 match score."""

    name: str
    url: str | None = None
    match: float | None = None
    artist: Named


class SimilarTracks(ApiModel):
    """Similar tracks, best match first."""

    track: Annotated[list[SimilarTrack], BeforeValidator(_as_list)] = []


class SimilarTracksResponse(ApiModel):
    """Response of track.getSimilar."""

    similartracks: Annotated[SimilarTracks, BeforeValidator(_as_object)] = SimilarTracks()


class SimilarArtist(ApiModel):
    """Artist listened to by the same people, with a 0-1 match score."""

    name: str
    url: str | None = None
    match: float | None = None


class SimilarArtists(ApiModel):
    """Similar artists, best match first."""

    artist: Annotated[list[SimilarArtist], BeforeValidator(_as_list)] = []


class SimilarArtistsResponse(ApiModel):
    """Response of artist.getSimilar."""

    similar: Annotated[SimilarArtists, BeforeValidator(_as_object)] = Field(
        default=SimilarArtists(), alias="similarartists"
    )
