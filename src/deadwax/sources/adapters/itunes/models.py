from pydantic import BaseModel, ConfigDict, Field

from deadwax.core import (
    EntityKind,
)


class _Api(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class Item(_Api):
    """Track or collection from the iTunes Search API."""

    wrapper_type: str = Field(alias="wrapperType")
    artist_name: str = Field(default="", alias="artistName")
    track_name: str | None = Field(default=None, alias="trackName")
    collection_name: str | None = Field(default=None, alias="collectionName")
    track_id: int | None = Field(default=None, alias="trackId")
    collection_id: int | None = Field(default=None, alias="collectionId")
    track_view_url: str | None = Field(default=None, alias="trackViewUrl")
    collection_view_url: str | None = Field(default=None, alias="collectionViewUrl")
    artist_view_url: str | None = Field(default=None, alias="artistViewUrl")
    preview_url: str | None = Field(default=None, alias="previewUrl")
    release_date: str | None = Field(default=None, alias="releaseDate")
    primary_genre_name: str | None = Field(default=None, alias="primaryGenreName")

    @property
    def kind(self) -> EntityKind | None:
        """Track or album, or None for artists and other results."""
        if self.wrapper_type == "track" and self.track_name is not None:
            return EntityKind.TRACK
        if self.wrapper_type == "collection" and self.collection_name is not None:
            return EntityKind.ALBUM
        return None

    @property
    def title(self) -> str:
        """Track title for tracks, collection title for albums."""
        if self.kind is EntityKind.TRACK and self.track_name is not None:
            return self.track_name
        return self.collection_name or ""


class Results(_Api):
    """Response of the search and lookup endpoints."""

    results: list[Item] = []
