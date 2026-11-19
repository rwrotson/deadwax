import re
from collections.abc import Iterable, Sequence

from deadwax.core import (
    CandidateLabel,
    Credit,
    Entity,
    EntityKind,
    EntityType,
    IdKind,
    Link,
    LinkTarget,
    Provenance,
    RecordKey,
    Relation,
    RelationKind,
    ReviewLink,
    Scope,
    Tag,
    TagKind,
    Verdict,
    VersionInfo,
    VersionKind,
    classify_marker,
    compare,
    parse_title,
)
from deadwax.sources.adapters.musicbrainz import models
from deadwax.sources.services import link_target, recognize, service_for_url

SOURCE = "musicbrainz"
SITE = "https://musicbrainz.org"

# Comments that mark a recording as an excerpt of a DJ mix, which is never the record itself.
_MIX_EXCERPT = re.compile(r"\bpart of\b|\bDJ[\s\-\u2010]?mix\b", re.IGNORECASE)
_ORIGINAL_COMMENT = re.compile(r"\b(?:original|album) (?:mix|version)\b", re.IGNORECASE)

# Version kinds a MusicBrainz comment can establish; other keywords in comments are too loose.
_COMMENT_KINDS = frozenset(
    {
        VersionKind.LIVE,
        VersionKind.DEMO,
        VersionKind.INSTRUMENTAL,
        VersionKind.ACOUSTIC,
        VersionKind.REMIX,
        VersionKind.EDIT,
        VersionKind.REMASTER,
        VersionKind.ALTERNATE,
    },
)

# Recording-to-recording relation types: (kind when this recording is entity0, kind otherwise).
_RECORDING_RELATIONS: dict[str, tuple[RelationKind, RelationKind, str | None]] = {
    "remix": (RelationKind.REMIX_OF, RelationKind.REMIXED_BY, None),
    "samples material": (RelationKind.SAMPLES, RelationKind.SAMPLED_BY, None),
    "mashes up": (RelationKind.SAMPLES, RelationKind.SAMPLED_BY, "mash-up"),
    "edit": (RelationKind.OTHER_VERSION, RelationKind.OTHER_VERSION, "edit"),
    "karaoke": (RelationKind.OTHER_VERSION, RelationKind.OTHER_VERSION, "karaoke"),
}

# MusicBrainz's placeholder for self-released records; it names no label.
_NO_LABEL = "157afde4-4bf5-4039-8ad2-5a15acc85176"

# Album-like release group types on which the original release of a recording appears.
_MAIN_TYPES = ("Album", "EP", "Single")


def page(entity: str, mbid: str) -> str:
    """Return the MusicBrainz page of an entity."""
    return f"{SITE}/{entity}/{mbid}"


def provenance(entity: str, mbid: str) -> list[Provenance]:
    """Return provenance pointing at an entity's page."""
    return [Provenance(source=SOURCE, url=page(entity, mbid))]


def phrase(text: str) -> str:
    """Quote text as a Lucene phrase."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def credit_name(artist_credit: Sequence[models.ArtistCredit]) -> str:
    """Join an artist credit into the name printed on the record."""
    return "".join(f"{credit.name}{credit.joinphrase}" for credit in artist_credit)


def is_mix_excerpt(comment: str) -> bool:
    """Whether a disambiguation comment marks an excerpt of a DJ mix."""
    return bool(_MIX_EXCERPT.search(comment))


def comment_version(comment: str) -> VersionInfo | None:
    """Read a version from a disambiguation comment, when the comment clearly names one."""
    if not comment or _ORIGINAL_COMMENT.search(comment):
        return None
    kind = classify_marker(comment)
    if kind not in _COMMENT_KINDS:
        return None
    return VersionInfo(kind=kind, detail=comment)


def recording_version(title: str, comment: str) -> VersionInfo:
    """Combine the version in a title with the one in its disambiguation comment."""
    version = parse_title(title).version
    if version.kind is VersionKind.ORIGINAL:
        return comment_version(comment) or version
    return version


def _date_key(date: str | None) -> str:
    return date or "9999"


def _year_key(date: str | None) -> str:
    """Compare by year only: partial dates such as '1997-05' would sort before full ones."""
    return (date or "9999")[:4]


def _is_main(release: models.ReleaseRef) -> bool:
    """Whether a release is an official album, EP or single without secondary types."""
    group = release.release_group
    return (
        release.status == "Official"
        and group is not None
        and group.primary_type in _MAIN_TYPES
        and not group.secondary_types
    )


def rank_recordings(
    reference: RecordKey,
    recordings: Iterable[models.Recording],
) -> list[models.Recording]:
    """Return the recordings that match the reference, the most likely original first."""
    matching = [
        recording
        for recording in recordings
        if not recording.video
        and not is_mix_excerpt(recording.disambiguation)
        and compare(
            reference,
            RecordKey(
                artist=credit_name(recording.artist_credit),
                title=recording.title,
                kind=EntityKind.TRACK,
                version=recording_version(recording.title, recording.disambiguation),
            ),
        ).verdict
        is Verdict.MATCH
    ]

    return sorted(
        matching,
        key=lambda r: (
            not any(_is_main(release) for release in r.releases),
            _year_key(r.first_release_date),
            -len(r.releases),
        ),
    )


def rank_release_groups(
    reference: RecordKey,
    groups: Iterable[models.ReleaseGroup],
) -> list[models.ReleaseGroup]:
    """Return the release groups that match the reference, plain albums first."""
    matching = [
        group
        for group in groups
        if compare(
            reference,
            RecordKey(
                artist=credit_name(group.artist_credit),
                title=group.title,
                kind=EntityKind.ALBUM,
                version=parse_title(group.title).version,
            ),
        ).verdict
        is Verdict.MATCH
    ]

    return sorted(
        matching,
        key=lambda g: (bool(g.secondary_types), _date_key(g.first_release_date)),
    )


def first_release(releases: Iterable[models.ReleaseRef]) -> models.ReleaseRef | None:
    """Pick the earliest official release, preferring albums, EPs and singles."""
    ordered = sorted(
        releases,
        key=lambda r: (r.status != "Official", not _is_main(r), _date_key(r.date)),
    )
    return ordered[0] if ordered else None


def tags(
    folksonomy: Sequence[models.Tag],
    genres: Sequence[models.Tag],
    scope: Scope,
    url: str,
) -> list[Tag]:
    """Turn genres and tags with positive votes into weighted tags."""
    voted = [tag for tag in [*genres, *folksonomy] if tag.count > 0]
    if not voted:
        return []

    top = max(tag.count for tag in voted)
    genre_names = {genre.name for genre in genres}
    result: list[Tag] = []
    seen: set[str] = set()
    for tag in voted:
        if tag.name in seen:
            continue
        seen.add(tag.name)
        result.append(
            Tag(
                name=tag.name,
                kind=TagKind.GENRE if tag.name in genre_names else TagKind.TAG,
                weight=round(tag.count / top, 3),
                scope=scope,
                sources=[Provenance(source=SOURCE, url=url)],
            ),
        )
    return result


def artist_credits(relations: Iterable[models.Relation], scope: Scope, url: str) -> list[Credit]:
    """Turn artist relations into credits; attributes such as instruments become the detail."""
    return [
        Credit(
            role=relation.type,
            name=relation.artist.name,
            detail=", ".join(relation.attributes) or None,
            scope=scope,
            sources=[Provenance(source=SOURCE, url=url)],
        )
        for relation in relations
        if relation.target_type == "artist" and relation.artist is not None
    ]


def _recording_entity(recording: models.RecordingRef) -> Entity:
    return Entity(
        type=EntityType.RECORDING,
        name=recording.title,
        artist=credit_name(recording.artist_credit) or None,
        url=page("recording", recording.id),
        ids={IdKind.MUSICBRAINZ_RECORDING: recording.id},
    )


def recording_relations(
    relations: Iterable[models.Relation],
    scope: Scope,
    url: str,
) -> list[Relation]:
    """Turn remix, sample, mash-up and edit relations between recordings into relations."""
    result = []
    for relation in relations:
        mapping = _RECORDING_RELATIONS.get(relation.type)
        if relation.recording is None or mapping is None or relation.recording.video:
            continue
        forward, backward, note = mapping
        result.append(
            Relation(
                kind=forward if relation.direction == "forward" else backward,
                target=_recording_entity(relation.recording),
                note=note,
                scope=scope,
                sources=[Provenance(source=SOURCE, url=url)],
            ),
        )
    return result


def appearances(
    releases: Iterable[models.ReleaseRef],
    skip_group: str | None,
    url: str,
) -> list[Relation]:
    """Turn the official releases of a recording into appearances, one per release group."""
    result: list[Relation] = []
    seen = {skip_group}
    for release in sorted(releases, key=lambda r: _date_key(r.date)):
        group = release.release_group
        if release.status != "Official" or group is None or group.id in seen:
            continue
        seen.add(group.id)
        if "Live" in group.secondary_types:
            continue
        if "DJ-mix" in group.secondary_types:
            kind = RelationKind.MIX
        elif "Compilation" in group.secondary_types:
            kind = RelationKind.COMPILATION
        else:
            kind = RelationKind.APPEARS_ON
        result.append(
            Relation(
                kind=kind,
                target=Entity(
                    type=EntityType.RELEASE,
                    name=group.title or release.title,
                    date=group.first_release_date or release.date,
                    url=page("release-group", group.id),
                    ids={IdKind.MUSICBRAINZ_RELEASE_GROUP: group.id},
                ),
                scope=Scope.RECORDING,
                sources=[Provenance(source=SOURCE, url=url)],
            ),
        )

    return result


def links(relations: Iterable[models.Relation], default: LinkTarget, url: str) -> list[Link]:
    """Turn URL relations to streaming and store services into links."""
    result = []
    for relation in relations:
        if relation.url is None:
            continue
        service = service_for_url(relation.url.resource)
        if service is None:
            continue
        result.append(
            Link(
                service=service,
                url=relation.url.resource,
                target=link_target(relation.url.resource, default),
                sources=[Provenance(source=SOURCE, url=url)],
            ),
        )
    return result


def review_links(relations: Iterable[models.Relation], url: str) -> list[ReviewLink]:
    """Keep MusicBrainz URL relations to reviews for later press lookups."""
    return [
        ReviewLink(url=relation.url.resource, sources=[Provenance(source=SOURCE, url=url)])
        for relation in relations
        if relation.url is not None and "review" in relation.type.casefold()
    ]


_WIKIDATA = re.compile(r"^https?://(?:www\.)?wikidata\.org/wiki/(Q\d+)$")


def url_ids(relations: Iterable[models.Relation]) -> dict[IdKind, str]:
    """Collect Wikidata and Discogs identifiers from URL relations."""
    ids: dict[IdKind, str] = {}
    for relation in relations:
        if relation.url is None:
            continue
        resource = relation.url.resource
        wikidata = _WIKIDATA.match(resource)
        if wikidata:
            ids.setdefault(IdKind.WIKIDATA, wikidata[1])
            continue
        _, found = recognize(resource)
        for kind in (IdKind.DISCOGS_MASTER, IdKind.DISCOGS_RELEASE):
            if kind in found:
                ids.setdefault(kind, found[kind])
    return ids


def labels(release: models.Release) -> list[CandidateLabel]:
    """Return the labels and catalog numbers of a release."""
    return [
        CandidateLabel(name=info.label.name, catalog_number=info.catalog_number)
        for info in release.label_info
        if info.label is not None and info.label.id != _NO_LABEL
    ]


def label_relations(release: models.Release) -> list[Relation]:
    """Return the labels of a release as relations for further digging."""
    url = page("release", release.id)
    return [
        Relation(
            kind=RelationKind.LABEL,
            target=Entity(
                type=EntityType.LABEL,
                name=info.label.name,
                url=page("label", info.label.id),
                ids={IdKind.MUSICBRAINZ_LABEL: info.label.id},
            ),
            note=info.catalog_number,
            scope=Scope.RELEASE,
            sources=[Provenance(source=SOURCE, url=url)],
        )
        for info in release.label_info
        if info.label is not None and info.label.id != _NO_LABEL
    ]


def member_relations(artist: models.Artist) -> list[Relation]:
    """Return the members of a group, or the groups a person belongs to."""
    url = page("artist", artist.id)
    result = []
    for relation in artist.relations:
        if relation.type != "member of band" or relation.artist is None:
            continue
        kind = RelationKind.MEMBER if relation.direction == "backward" else RelationKind.PROJECT
        result.append(
            Relation(
                kind=kind,
                target=Entity(
                    type=EntityType.ARTIST,
                    name=relation.artist.name,
                    url=page("artist", relation.artist.id),
                    ids={IdKind.MUSICBRAINZ_ARTIST: relation.artist.id},
                ),
                note=", ".join(relation.attributes) or None,
                scope=Scope.ARTIST,
                sources=[Provenance(source=SOURCE, url=url)],
            ),
        )

    return result


def work_relations(
    work: models.Work,
    recording_id: str,
    version: VersionInfo,
    is_cover: bool,
    limit: int = 50,
) -> list[Relation]:
    """Relate a recording to its work and the work's other recordings.

    A cover points at the work as `cover_of`, a remix as `remix_of`, and any other derived
    version as `other_version`; only an original lists the work's covers as `covered_by`.
    """
    url = page("work", work.id)
    sources = [Provenance(source=SOURCE, url=url)]

    if is_cover or version.kind is not VersionKind.ORIGINAL:
        if is_cover:
            kind = RelationKind.COVER_OF
        elif version.kind is VersionKind.REMIX:
            kind = RelationKind.REMIX_OF
        else:
            kind = RelationKind.OTHER_VERSION
        target = Entity(
            type=EntityType.WORK,
            name=work.title,
            url=url,
            ids={IdKind.MUSICBRAINZ_WORK: work.id},
        )
        note = "the song this recording performs"
        return [Relation(kind=kind, target=target, note=note, scope=Scope.WORK, sources=sources)]

    covers = [
        relation.recording
        for relation in work.relations
        if relation.type == "performance"
        and "cover" in relation.attributes
        and relation.recording is not None
        and relation.recording.id != recording_id
    ]
    return [
        Relation(
            kind=RelationKind.COVERED_BY,
            target=_recording_entity(recording),
            scope=Scope.WORK,
            sources=sources,
        )
        for recording in covers[:limit]
    ]


def track_credits(release: models.Release) -> list[Credit]:
    """Collect per-track artist relations of a release, one credit per person, role and detail.

    The detail lists the instruments or vocals, followed by the tracks they apply to.
    """
    url = page("release", release.id)
    grouped: dict[tuple[str, str, str], list[str]] = {}
    for medium in release.media:
        for track in medium.tracks:
            for relation in track.recording.relations:
                if relation.target_type != "artist" or relation.artist is None:
                    continue
                key = (relation.type, relation.artist.name, ", ".join(relation.attributes))
                titles = grouped.setdefault(key, [])
                if track.title not in titles:
                    titles.append(track.title)

    return [
        Credit(
            role=role,
            name=name,
            detail=f"{attributes} ({'; '.join(titles)})" if attributes else "; ".join(titles),
            scope=Scope.RECORDING,
            sources=[Provenance(source=SOURCE, url=url)],
        )
        for (role, name, attributes), titles in grouped.items()
    ]
