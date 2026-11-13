from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base for SoundCloud API responses; unknown fields are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class User(ApiModel):
    """Account that uploaded or reposted a record."""

    id: int
    username: str
    permalink_url: str | None = None
    followers_count: int = 0
    verified: bool = False


class PublisherMetadata(ApiModel):
    """Release details a distributor or label attached to an upload."""

    artist: str | None = None
    isrc: str | None = None
    upc_or_ean: str | None = None
    p_line: str | None = None
    c_line: str | None = None


class Item(ApiModel):
    """Track or playlist; the fields both kinds share."""

    kind: str
    id: int
    title: str
    permalink_url: str | None = None
    description: str | None = None
    genre: str | None = None
    tag_list: str | None = None
    likes_count: int | None = None
    reposts_count: int | None = None
    release_date: str | None = None
    user: User | None = None
    publisher_metadata: PublisherMetadata | None = None


class Track(Item):
    """Uploaded track."""

    playback_count: int | None = None


class Playlist(Item):
    """Set of tracks; `set_type` tells albums and EPs from playlists."""

    set_type: str | None = None


class Resolved(ApiModel):
    """Object a page URL resolves to, read for its kind first."""

    kind: str


class TrackSearch(ApiModel):
    """Track search results."""

    collection: list[Track] = []


class PlaylistSearch(ApiModel):
    """Album search results."""

    collection: list[Playlist] = []


class Users(ApiModel):
    """Users who reposted a track."""

    collection: list[User] = []
