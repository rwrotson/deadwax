from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    """Base for Discogs API responses; unknown fields are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class ArtistCredit(ApiModel):
    """Artist in a credit list, with a role and track positions for extra artists."""

    id: int | None = None
    name: str
    anv: str = Field(default="", description="Name as credited on the release")
    join: str = ""
    role: str = ""
    tracks: str = ""


class LabelCredit(ApiModel):
    """Label of a release with its catalog number."""

    id: int | None = None
    name: str
    catno: str = ""


class Identifier(ApiModel):
    """Barcode, matrix, or other identifier printed on a release."""

    type: str
    value: str = ""


class Format(ApiModel):
    """Physical or digital format of a release."""

    name: str
    qty: str = ""
    descriptions: list[str] = []


class Track(ApiModel):
    """Tracklist entry; headings and index tracks have other types."""

    position: str = ""
    type_: str = "track"
    title: str
    artists: list[ArtistCredit] = []
    extraartists: list[ArtistCredit] = []


class Master(ApiModel):
    """Master release grouping the versions of an album."""

    id: int
    title: str
    year: int | None = None
    main_release: int | None = None
    uri: str | None = None
    notes: str | None = None
    genres: list[str] = []
    styles: list[str] = []
    artists: list[ArtistCredit] = []
    tracklist: list[Track] = []


class Release(ApiModel):
    """One version of a release."""

    id: int
    title: str
    year: int | None = None
    released: str | None = None
    country: str | None = None
    master_id: int | None = None
    uri: str | None = None
    notes: str | None = None
    genres: list[str] = []
    styles: list[str] = []
    artists: list[ArtistCredit] = []
    extraartists: list[ArtistCredit] = []
    labels: list[LabelCredit] = []
    identifiers: list[Identifier] = []
    formats: list[Format] = []
    tracklist: list[Track] = []


class Version(ApiModel):
    """Release listed among a master's versions."""

    id: int
    title: str
    label: str | None = None
    catno: str | None = None
    country: str | None = None
    format: str | None = None
    released: str | None = None


class Versions(ApiModel):
    """Page of a master's versions."""

    versions: list[Version] = []


class ArtistRef(ApiModel):
    """Member, group, or alias of an artist."""

    id: int
    name: str
    active: bool | None = None


class Artist(ApiModel):
    """Artist with members, groups, and aliases."""

    id: int
    name: str
    uri: str | None = None
    realname: str | None = None
    profile: str | None = None
    urls: list[str] = []
    namevariations: list[str] = []
    members: list[ArtistRef] = []
    groups: list[ArtistRef] = []
    aliases: list[ArtistRef] = []


class LabelRef(ApiModel):
    """Parent label or sublabel listed on a label profile."""

    id: int
    name: str


class Label(LabelRef):
    """Label profile and hierarchy."""

    profile: str | None = None
    urls: list[str] = []
    parent_label: LabelRef | None = None
    sublabels: list[LabelRef] = []


class ArtistRelease(ApiModel):
    """A master or release in an artist's discography."""

    id: int
    title: str
    type: str
    role: str
    artist: str | None = None
    year: int | None = None


class ArtistReleases(ApiModel):
    """Page of an artist's discography."""

    releases: list[ArtistRelease] = []


class LabelRelease(ApiModel):
    """Release in a label's catalog."""

    id: int
    title: str
    artist: str | None = None
    year: int | None = None
    catno: str | None = None
    format: str | None = None


class LabelReleases(ApiModel):
    """Page of a label's catalog."""

    releases: list[LabelRelease] = []


class SearchResult(ApiModel):
    """Database search result; the title is 'Artist - Title'."""

    id: int
    type: str
    title: str
    year: str | None = None
    master_id: int | None = None
    uri: str | None = None
    format: list[str] = []
    label: list[str] = []
    catno: str | None = None


class Search(ApiModel):
    """Page of database search results."""

    results: list[SearchResult] = []
