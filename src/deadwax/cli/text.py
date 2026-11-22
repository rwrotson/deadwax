from deadwax import (
    AlbumQuery,
    ArtistIdentity,
    ArtistQuery,
    Identity,
    LabelIdentity,
    LabelQuery,
    Query,
    Rating,
    RecordIdentity,
    Relation,
    SourceAccess,
    Sourced,
    TrackQuery,
    VersionInfo,
)

# HTML transports that drive a browser and so run headless or headed.
_BROWSER_TRANSPORTS = frozenset({"patchright", "nodriver"})


def access_label(access: SourceAccess) -> str:
    """Describe the configured routes to a source in their attempt order."""
    parts = ["API (httpx)"] if access.api else []
    if access.browser_headless is not None:
        mode = "headless" if access.browser_headless else "headed"
        if access.browser_headless and access.headed_fallback:
            mode = "headless → headed"
        steps = [
            f"{step} [{mode}]" if step in _BROWSER_TRANSPORTS else step
            for step in access.html_transports
        ]
        parts.append(f"HTML ({' → '.join(steps) if steps else 'no permitted transports'})")
    return "; ".join(parts)


def number(value: float, *, grouped: bool = False) -> str:
    """Write a whole number without a decimal point, optionally with thousands separators."""
    if not value.is_integer():
        return f"{value:g}"
    return f"{int(value):,}" if grouped else str(int(value))


def rating(value: Rating | None) -> str:
    """Write a score as printed by its source, or as value and scale."""
    if value is None:
        return ""
    if value.text:
        return value.text
    if value.value is None:
        return ""
    scale = f"/{value.scale:g}" if value.scale is not None else ""
    return f"{value.value:g}{scale}"


def version_text(version: VersionInfo) -> str:
    """Write a version kind with its title marker."""
    return f"{version.kind} ({version.detail})" if version.detail else str(version.kind)


def identity_title(identity: Identity) -> str | None:
    """Name the identified record: artist and title of a track or album, else its name."""
    if isinstance(identity, RecordIdentity):
        if identity.title is None:
            return None
        artist = f"{identity.artist.value} — " if identity.artist is not None else ""
        return f"{artist}{identity.title.value}"
    return None if identity.name is None else identity.name.value


def query_text(query: Query) -> str:
    """Write what a query asks for: its URL, 'Artist - Title', or a name."""
    match query:
        case (
            TrackQuery(url=None, artist=str(artist), title=str(title))
            | AlbumQuery(
                url=None,
                artist=str(artist),
                title=str(title),
            )
        ):
            return f"{artist} - {title}"
        case ArtistQuery(url=None, name=str(name)) | LabelQuery(url=None, name=str(name)):
            return name
    return query.url or ""


def name_fields(identity: ArtistIdentity | LabelIdentity) -> list[tuple[str, Sourced[str]]]:
    """List the identified fields of an artist or label with their labels."""
    fields = [
        ("name", identity.name),
        ("disambiguation", identity.disambiguation),
        ("country", identity.country),
        ("location", identity.location),
        ("begin", identity.begin),
        ("end", identity.end),
    ]
    if isinstance(identity, ArtistIdentity) and identity.type is not None:
        artist_type = Sourced(value=str(identity.type.value), sources=identity.type.sources)
        fields.insert(2, ("type", artist_type))
    return [(label, value) for label, value in fields if value is not None]


def relation_details(relation: Relation) -> list[str]:
    """List the note, sampled element, and offsets of a relation."""
    details = [item for item in (relation.note, relation.element) if item]
    if relation.recording_offset is not None:
        details.append(f"recording {relation.recording_offset}s")
    if relation.target_offset is not None:
        details.append(f"target {relation.target_offset}s")
    return details
