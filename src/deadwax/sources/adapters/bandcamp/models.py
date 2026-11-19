from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    """Base for Bandcamp data; unknown fields are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class Current(ApiModel):
    """Release or track fields of the page's `data-tralbum` attribute."""

    title: str | None = None
    artist: str | None = None
    release_date: str | None = None
    about: str | None = None
    credits: str | None = None
    band_id: int | None = None
    isrc: str | None = None
    upc: str | None = None


class TrackInfo(ApiModel):
    """Track listed on an album page."""

    id: int | None = None
    title: str
    artist: str | None = None
    title_link: str | None = None
    track_num: int | None = None
    file: dict[str, str] | None = Field(
        default=None,
        description="Stream URLs by encoding; a signed URL that expires",
    )


class Tralbum(ApiModel):
    """The `data-tralbum` attribute of an album or track page."""

    id: int
    item_type: str
    artist: str | None = None
    url: str | None = None
    album_url: str | None = None
    album_release_date: str | None = None
    current: Current = Current()
    trackinfo: list[TrackInfo] = []


class SearchResult(ApiModel):
    """Album or track found by the search autocomplete endpoint."""

    type: str
    id: int
    name: str
    band_id: int | None = None
    band_name: str | None = None
    item_url_path: str | None = None


class SearchResults(ApiModel):
    """Results of the search autocomplete endpoint."""

    results: list[SearchResult] = []


class SearchResponse(ApiModel):
    """Response of the search autocomplete endpoint."""

    auto: SearchResults = SearchResults()


class MobileBand(ApiModel):
    """Account that sells a release, as the mobile API describes it."""

    band_id: int | None = None
    name: str | None = None


class MobileTag(ApiModel):
    """Tag of a release; location tags are marked."""

    name: str
    isloc: bool = False


class MobileTrack(ApiModel):
    """Track of a release in the mobile API."""

    track_id: int | None = None
    title: str
    band_name: str | None = None


class MobileDetails(ApiModel):
    """Release or track from the mobile API's `tralbum_details` endpoint."""

    id: int
    type: str
    title: str
    bandcamp_url: str | None = None
    band: MobileBand = MobileBand()
    tralbum_artist: str | None = None
    about: str | None = None
    credits: str | None = None
    release_date: int | None = Field(default=None, description="Unix time")
    label: str | None = None
    tags: list[MobileTag] = []
    tracks: list[MobileTrack] = []
