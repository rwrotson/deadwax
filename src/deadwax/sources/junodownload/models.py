from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Track:
    """Row of a release's tracklist."""

    title: str
    artist: str | None = None
    bpm: float | None = None


@dataclass(frozen=True, slots=True)
class Release:
    """Release page: the product Juno Download sells, with its tracks."""

    artist: str
    title: str
    label: str | None = None
    catalog_number: str | None = None
    date: str | None = None
    genres: list[str] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Listing:
    """Search result: a release with the titles of its tracks."""

    url: str
    artist: str
    title: str
    tracks: list[Track] = field(default_factory=list)
