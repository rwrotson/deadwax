import logging
import re
from collections.abc import Iterable, Sequence
from urllib.parse import urlsplit

from deadwax.core import (
    ArtistCandidate,
    CandidateLabel,
    Credit,
    Entity,
    EntityKind,
    EntityType,
    IdKind,
    LabelCandidate,
    Link,
    LinkTarget,
    NameKey,
    Provenance,
    RecordCandidate,
    RecordKey,
    Relation,
    RelationKind,
    Scope,
    Tag,
    TagKind,
    Text,
    TextKind,
    Verdict,
    compare,
    compare_names,
    normalize_barcode,
    normalize_text,
)
from deadwax.sources.adapters.discogs import models
from deadwax.sources.services import link_target, service_of

logger = logging.getLogger(__name__)

SOURCE = "discogs"
SITE = "https://www.discogs.com"
VERSIONS_LIMIT = 15
LABEL_RELEASES_LIMIT = 12
ARTIST_RELEASES_LIMIT = 12
COMPILATIONS_LIMIT = 12

# Placeholder artists Discogs uses for unknown credits.
_PLACEHOLDERS = frozenset({"unknown", "unknown artist", "no artist"})

# Placeholder label of self-released records, and its catalog number.
_NO_LABEL = "not on label"
_NO_CATNO = frozenset({"", "none"})

# Discogs adds " (2)" to names shared by several artists or labels.
_DISAMBIGUATION = re.compile(r"\s+\(\d+\)$")
_ROLE = re.compile(r"^(?P<role>[^\[]+?)\s*(?:\[(?P<detail>[^\]]*)\])?$")
_ROLE_SPLIT = re.compile(r",\s*(?![^\[]*\])")
_RANGE = re.compile(r"^(?P<start>\S+)\s+to\s+(?P<end>\S+)$", re.IGNORECASE)


def page(entity: str, discogs_id: int) -> str:
    """Return the Discogs page of a master, release, artist, or label."""
    return f"{SITE}/{entity}/{discogs_id}"


def clean_name(name: str) -> str:
    """Remove the numeric suffix Discogs adds to tell namesakes apart."""
    return _DISAMBIGUATION.sub("", name.strip())


def credit_name(artists: Sequence[models.ArtistCredit]) -> str:
    """Join an artist credit as printed, using the names credited on the release."""
    parts: list[str] = []
    for index, artist in enumerate(artists):
        parts.append(clean_name(artist.anv or artist.name))
        if index < len(artists) - 1:
            join = artist.join.strip() or ","
            parts.append(f" {join} " if join != "," else ", ")
    return "".join(parts)


def tags(genres: Iterable[str], styles: Iterable[str], scope: Scope, url: str | None) -> list[Tag]:
    """Return Discogs genres and styles."""
    sources = [Provenance(source=SOURCE, url=url)]
    return [
        *(Tag(name=g, kind=TagKind.GENRE, scope=scope, sources=sources) for g in genres),
        *(Tag(name=s, kind=TagKind.STYLE, scope=scope, sources=sources) for s in styles),
    ]


def roles(role: str) -> list[tuple[str, str | None]]:
    """Split 'Producer, Arranged By [Strings]' into (role, detail) pairs."""
    result = []
    for part in _ROLE_SPLIT.split(role):
        match = _ROLE.match(part.strip())
        if match is None or not match["role"]:
            continue
        name = re.sub(r"[\s-]+by$", "", match["role"].strip(), flags=re.IGNORECASE)
        result.append((name.lower(), match["detail"] or None))
    return result


def _positions(tracklist: Sequence[models.Track]) -> list[str]:
    return [track.position for track in tracklist if track.type_ == "track" and track.position]


def covers(tracks: str, position: str, positions: Sequence[str]) -> bool:
    """Whether a credit's track list, such as 'A1, B2' or 'A1 to A3', includes a position."""
    for part in (p.strip() for p in tracks.split(",")):
        if part == position:
            return True
        span = _RANGE.match(part)
        if span is not None and span["start"] in positions and span["end"] in positions:
            start, end = positions.index(span["start"]), positions.index(span["end"])
            if position in positions[start : end + 1]:
                return True
    return False


def _credits_of(
    artists: Iterable[models.ArtistCredit],
    scope: Scope,
    sources: list[Provenance],
    note: str | None,
) -> list[Credit]:
    result = []
    for artist in artists:
        for role, detail in roles(artist.role):
            details = ", ".join(d for d in (detail, note) if d) or None
            result.append(
                Credit(
                    role=role,
                    name=clean_name(artist.anv or artist.name),
                    detail=details,
                    scope=scope,
                    sources=sources,
                ),
            )
    return result


def release_credits(release: models.Release, track: models.Track | None = None) -> list[Credit]:
    """Credits of the release; for a track, only release-wide ones and those of that track."""
    sources = [Provenance(source=SOURCE, url=page("release", release.id))]

    if track is None:
        result = []
        for artist in release.extraartists:
            note = f"tracks {artist.tracks}" if artist.tracks else None
            result += _credits_of([artist], Scope.RELEASE, sources, note)
        for entry in release.tracklist:
            note = f"track {entry.position}" if entry.position else entry.title
            result += _credits_of(entry.extraartists, Scope.RECORDING, sources, note)
        return result

    positions = _positions(release.tracklist)
    release_wide = [a for a in release.extraartists if not a.tracks]
    for_track = [
        a for a in release.extraartists if a.tracks and covers(a.tracks, track.position, positions)
    ]
    return [
        *_credits_of(release_wide, Scope.RELEASE, sources, None),
        *_credits_of([*for_track, *track.extraartists], Scope.RECORDING, sources, None),
    ]


def notes(text: str | None, title: str, scope: Scope, url: str) -> list[Text]:
    """Return the database notes of a master or release."""
    if not text or not text.strip():
        return []
    body = text.replace("\r\n", "\n").strip()
    return [
        Text(
            kind=TextKind.WIKI,
            title=title,
            body=body,
            publication="Discogs",
            scope=scope,
            sources=[Provenance(source=SOURCE, url=url)],
        ),
    ]


def real_labels(release: models.Release) -> list[models.LabelCredit]:
    """Labels of the release without the 'Not On Label' placeholder of self-releases."""
    return [
        label
        for label in release.labels
        if not clean_name(label.name).lower().startswith(_NO_LABEL)
    ]


def catalog_number(label: models.LabelCredit) -> str | None:
    """Catalog number, or None for the placeholder 'none'."""
    catno = label.catno.strip()
    return None if catno.lower() in _NO_CATNO else catno


def labels(release: models.Release) -> list[CandidateLabel]:
    """Labels with catalog numbers, without repeats."""
    found = {
        (clean_name(label.name), catalog_number(label)): None for label in real_labels(release)
    }
    return [CandidateLabel(name=name, catalog_number=catno) for name, catno in found]


def label_relations(release: models.Release) -> list[Relation]:
    """Labels of the release as related entities."""
    sources = [Provenance(source=SOURCE, url=page("release", release.id))]
    seen: dict[int | str, Relation] = {}
    for label in real_labels(release):
        key: int | str = label.id if label.id is not None else label.name
        if key in seen:
            continue
        seen[key] = Relation(
            kind=RelationKind.LABEL,
            target=Entity(
                type=EntityType.LABEL,
                name=clean_name(label.name),
                url=page("label", label.id) if label.id is not None else None,
                ids={IdKind.DISCOGS_LABEL: str(label.id)} if label.id is not None else {},
            ),
            note=catalog_number(label),
            scope=Scope.RELEASE,
            sources=sources,
        )

    return list(seen.values())


def barcodes(release: models.Release) -> list[str]:
    """Barcodes printed on the release, as digits, without repeats."""
    found = (normalize_barcode(i.value) for i in release.identifiers if i.type == "Barcode")
    return list(dict.fromkeys(code for code in found if code.isdigit()))


def _date(release: models.Release) -> str | None:
    released = (release.released or "").removesuffix("-00").removesuffix("-00")
    if released and released != "0":
        return released
    return str(release.year) if release.year else None


def _ids(release: models.Release, master: models.Master | None) -> dict[IdKind, str]:
    ids = {IdKind.DISCOGS_RELEASE: str(release.id)}
    master_id = master.id if master is not None else release.master_id
    if master_id:
        ids[IdKind.DISCOGS_MASTER] = str(master_id)
    artist_ids = [a.id for a in release.artists if a.id is not None]
    if artist_ids:
        ids[IdKind.DISCOGS_ARTIST] = str(artist_ids[0])
    return ids


def album_candidate(release: models.Release, master: models.Master | None) -> RecordCandidate:
    """Describe the album by its master's title and the main release's labels and barcode."""
    url = page("master", master.id) if master is not None else page("release", release.id)
    return RecordCandidate(
        kind=EntityKind.ALBUM,
        artist=credit_name(master.artists if master is not None else release.artists),
        title=master.title if master is not None else release.title,
        date=_date(release),
        labels=labels(release),
        upcs=barcodes(release),
        ids=_ids(release, master),
        url=url,
    )


def find_track(release: models.Release, reference: RecordKey) -> models.Track | None:
    """Return the tracklist entry of the queried track."""
    album_artist = credit_name(release.artists)
    for track in release.tracklist:
        if track.type_ != "track":
            continue
        artist = credit_name(track.artists) if track.artists else album_artist
        candidate = RecordKey(artist=artist, title=track.title, kind=EntityKind.TRACK)
        if compare(reference, candidate).verdict is not Verdict.NO_MATCH:
            return track
    return None


def track_candidate(
    release: models.Release,
    master: models.Master | None,
    track: models.Track,
) -> RecordCandidate:
    """Describe a track by its tracklist entry on the main release."""
    artists = track.artists or release.artists
    return RecordCandidate(
        kind=EntityKind.TRACK,
        artist=credit_name(artists),
        title=track.title,
        date=_date(release),
        labels=labels(release),
        ids=_ids(release, master),
        url=page("release", release.id),
    )


def appears_on(release: models.Release, master: models.Master | None) -> Relation:
    """The album a track was found on."""
    url = page("master", master.id) if master is not None else page("release", release.id)
    ids = {IdKind.DISCOGS_RELEASE: str(release.id)}
    if master is not None:
        ids[IdKind.DISCOGS_MASTER] = str(master.id)
    return Relation(
        kind=RelationKind.APPEARS_ON,
        target=Entity(
            type=EntityType.RELEASE,
            name=master.title if master is not None else release.title,
            artist=credit_name(release.artists) or None,
            date=_date(release),
            url=url,
            ids=ids,
        ),
        scope=Scope.RELEASE,
        sources=[Provenance(source=SOURCE, url=url)],
    )


def version_relations(versions: Iterable[models.Version], exclude: int) -> list[Relation]:
    """Other versions of the master: reissues, remasters, and other formats."""
    result = []
    for version in versions:
        if version.id == exclude:
            continue
        url = page("release", version.id)
        details = [version.format, version.country, version.label, version.catno]
        result.append(
            Relation(
                kind=RelationKind.OTHER_VERSION,
                target=Entity(
                    type=EntityType.RELEASE,
                    name=version.title,
                    date=version.released or None,
                    url=url,
                    ids={IdKind.DISCOGS_RELEASE: str(version.id)},
                ),
                note=", ".join(d for d in details if d) or None,
                scope=Scope.RELEASE_GROUP,
                sources=[Provenance(source=SOURCE, url=url)],
            ),
        )
        if len(result) >= VERSIONS_LIMIT:
            break

    return result


def _artist_relation(
    kind: RelationKind,
    ref: models.ArtistRef,
    note: str | None,
    url: str,
) -> Relation:
    return Relation(
        kind=kind,
        target=Entity(
            type=EntityType.ARTIST,
            name=clean_name(ref.name),
            url=page("artist", ref.id),
            ids={IdKind.DISCOGS_ARTIST: str(ref.id)},
        ),
        note=note,
        scope=Scope.ARTIST,
        sources=[Provenance(source=SOURCE, url=url)],
    )


def artist_relations(
    artist: models.Artist,
    *,
    aliases_as_aliases: bool = False,
) -> list[Relation]:
    """Members of a group, groups of a person, and other names the artist records under."""
    url = page("artist", artist.id)
    aliases = [a for a in artist.aliases if clean_name(a.name).lower() not in _PLACEHOLDERS]
    kind = RelationKind.ALIAS if aliases_as_aliases else RelationKind.PROJECT
    relations = [
        *(
            _artist_relation(
                RelationKind.MEMBER,
                m,
                None if m.active is not False else "former",
                url,
            )
            for m in artist.members
        ),
        *(_artist_relation(RelationKind.PROJECT, g, None, url) for g in artist.groups),
        *(_artist_relation(kind, a, None if aliases_as_aliases else "alias", url) for a in aliases),
    ]
    if aliases_as_aliases:
        seen = {normalize_text(clean_name(a.name)) for a in aliases}
        seen.add(normalize_text(clean_name(artist.name)))
        for variation in artist.namevariations:
            name = clean_name(variation)
            key = normalize_text(name)
            if not key or key in seen or name.lower() in _PLACEHOLDERS:
                continue
            seen.add(key)
            relations.append(
                Relation(
                    kind=RelationKind.ALIAS,
                    target=Entity(type=EntityType.ARTIST, name=name),
                    scope=Scope.ARTIST,
                    sources=[Provenance(source=SOURCE, url=url)],
                ),
            )
    return relations


def artist_candidate(artist: models.Artist) -> ArtistCandidate:
    """Identify the artist by the Discogs profile."""
    return ArtistCandidate(
        name=clean_name(artist.name),
        disambiguation=(artist.realname or "").strip() or None,
        ids={IdKind.DISCOGS_ARTIST: str(artist.id)},
        url=page("artist", artist.id),
    )


def label_candidate(label: models.Label) -> LabelCandidate:
    """Identify the label by the Discogs profile."""
    return LabelCandidate(
        name=clean_name(label.name),
        ids={IdKind.DISCOGS_LABEL: str(label.id)},
        url=page("label", label.id),
    )


def label_hierarchy(label: models.Label) -> list[Relation]:
    """Return directional relations to the parent label and sublabels."""
    entries = [(RelationKind.SUBLABEL, ref) for ref in label.sublabels]
    if label.parent_label is not None:
        entries.insert(0, (RelationKind.PARENT_LABEL, label.parent_label))
    return [
        Relation(
            kind=kind,
            target=Entity(
                type=EntityType.LABEL,
                name=clean_name(ref.name),
                url=page("label", ref.id),
                ids={IdKind.DISCOGS_LABEL: str(ref.id)},
            ),
            scope=Scope.LABEL,
            sources=[Provenance(source=SOURCE, url=page("label", label.id))],
        )
        for kind, ref in entries
    ]


def artist_release_relations(releases: Iterable[models.ArtistRelease], url: str) -> list[Relation]:
    """Return the artist's main masters in discography order."""
    result = []
    seen: set[int] = set()
    for item in releases:
        if item.type != "master" or item.role != "Main" or item.id in seen:
            continue
        seen.add(item.id)
        result.append(
            Relation(
                kind=RelationKind.RELEASE,
                target=Entity(
                    type=EntityType.RELEASE,
                    name=item.title.strip(),
                    artist=clean_name(item.artist or "") or None,
                    date=str(item.year) if item.year else None,
                    url=page("master", item.id),
                    ids={IdKind.DISCOGS_MASTER: str(item.id)},
                ),
                scope=Scope.ARTIST,
                sources=[Provenance(source=SOURCE, url=url)],
            ),
        )
        if len(result) >= ARTIST_RELEASES_LIMIT:
            break
    return result


def label_release_relations(
    releases: Iterable[models.LabelRelease],
    label: str,
    label_id: int,
    record_title: str | None = None,
) -> list[Relation]:
    """Other releases of the label, one per artist and title."""
    url = page("label", label_id)
    seen: set[tuple[str, str]] = set()
    if record_title is not None:
        seen.add((normalize_text(record_title), ""))
    result = []
    for item in releases:
        artist = clean_name(item.artist or "")
        key = (normalize_text(item.title), normalize_text(artist))
        if key in seen or (normalize_text(item.title), "") in seen:
            continue
        seen.add(key)
        result.append(
            Relation(
                kind=RelationKind.LABEL_RELEASE,
                target=Entity(
                    type=EntityType.RELEASE,
                    name=item.title.strip(),
                    artist=artist or None,
                    date=str(item.year) if item.year else None,
                    url=page("release", item.id),
                    ids={IdKind.DISCOGS_RELEASE: str(item.id)},
                ),
                note=", ".join(d.strip() for d in (label, item.catno) if d and d.strip()),
                scope=Scope.LABEL,
                sources=[Provenance(source=SOURCE, url=url)],
            ),
        )
        if len(result) >= LABEL_RELEASES_LIMIT:
            break

    return result


def split_title(title: str) -> tuple[str, str]:
    """Split a search result title 'Artist - Title'."""
    artist, separator, rest = title.partition(" - ")
    return (clean_name(artist), rest) if separator else ("", title)


def compilation_relations(
    results: Iterable[models.SearchResult],
    exclude: set[int],
) -> list[Relation]:
    """Compilations a track appears on, from a database search."""
    result = []
    seen: set[int] = set()
    for item in results:
        group = item.master_id or item.id
        if (
            item.id in exclude
            or (item.master_id is not None and item.master_id in exclude)
            or group in seen
        ):
            continue
        seen.add(group)
        artist, title = split_title(item.title)
        url = page("release", item.id)
        result.append(
            Relation(
                kind=RelationKind.COMPILATION,
                target=Entity(
                    type=EntityType.RELEASE,
                    name=title,
                    artist=artist or None,
                    date=item.year or None,
                    url=url,
                    ids={IdKind.DISCOGS_RELEASE: str(item.id)},
                ),
                note=", ".join([*item.label[:1], *(c for c in [item.catno] if c)]) or None,
                scope=Scope.RECORDING,
                sources=[Provenance(source=SOURCE, url=url)],
            ),
        )
        if len(result) >= COMPILATIONS_LIMIT:
            break

    return result


def pick_result(
    reference: RecordKey,
    results: Iterable[models.SearchResult],
) -> models.SearchResult | None:
    """Return the first search result whose artist and title match an album query.

    For a track query only the artist is compared; the tracklist decides later.
    """
    for item in results:
        artist, title = split_title(item.title)
        if reference.kind is EntityKind.TRACK:
            key = RecordKey(artist=artist, title=reference.title, kind=EntityKind.TRACK)
        else:
            key = RecordKey(artist=artist, title=title, kind=EntityKind.ALBUM)
        if compare(reference, key).verdict is Verdict.MATCH:
            return item
    return None


def links(release: models.Release, master: models.Master | None) -> list[Link]:
    """Pages of the master, the main release, and the artist on Discogs."""
    sources = [Provenance(source=SOURCE, url=page("release", release.id))]
    result = []
    if master is not None:
        result.append(
            Link(
                service=SOURCE,
                url=page("master", master.id),
                target=LinkTarget.ALBUM,
                sources=sources,
            ),
        )

    result.append(
        Link(
            service=SOURCE,
            url=page("release", release.id),
            target=LinkTarget.ALBUM,
            sources=sources,
        ),
    )

    result += [
        Link(service=SOURCE, url=page("artist", a.id), target=LinkTarget.ARTIST, sources=sources)
        for a in release.artists
        if a.id is not None
    ]

    return result


def pick_name(
    reference: NameKey,
    results: Iterable[models.SearchResult],
    id_kind: IdKind,
) -> models.SearchResult | None:
    """Pick the best matching artist or label, in search order for tied names."""
    best = None
    score = -1.0
    for item in results:
        if item.type != reference.kind:
            continue
        key = NameKey(name=clean_name(item.title), kind=reference.kind, ids={id_kind: str(item.id)})
        match = compare_names(reference, key)
        if match.verdict is Verdict.MATCH and match.name_score > score:
            best, score = item, match.name_score
    return best


def profile_links(urls: Iterable[str], target: LinkTarget, profile_url: str) -> list[Link]:
    """External links listed on a Discogs artist or label profile."""
    result = []
    for url in dict.fromkeys(raw.strip() for raw in urls):
        try:
            parts = urlsplit(url)
        except ValueError:
            continue
        if parts.scheme not in {"https", "http"} or not parts.hostname:
            continue
        service = service_of(url)
        result.append(
            Link(
                service=service.name
                if service is not None
                else parts.hostname.removeprefix("www."),
                url=url,
                target=link_target(url, target),
                sources=[Provenance(source=SOURCE, url=profile_url)],
            ),
        )
    return result
