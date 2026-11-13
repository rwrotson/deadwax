import re
from collections.abc import Mapping
from datetime import datetime

from deadwax.core import (
    Entity,
    EntityKind,
    EntityType,
    Provenance,
    RecordCandidate,
    RecordKey,
    Relation,
    RelationKind,
    Scope,
    Text,
    TextKind,
    Verdict,
    compare,
)
from deadwax.sources.kexp import models

SOURCE = "kexp"
STATION = "KEXP"
TRACK_PLAY = "trackplay"

# Hosts separate the parts of a long comment with a line of dashes.
_SEPARATOR = re.compile(r"^\s*-{2,}\s*$", re.MULTILINE)


def _name(play: models.Play, kind: EntityKind) -> str | None:
    return play.album if kind is EntityKind.ALBUM else play.song


def matching(plays: list[models.Play], key: RecordKey, kind: EntityKind) -> list[models.Play]:
    """Song plays of the record; plays of other records or other versions are dropped."""
    result = []
    for play in plays:
        name = _name(play, kind)
        if play.play_type != TRACK_PLAY or not play.artist or not name:
            continue
        found = RecordKey(artist=play.artist, title=name, kind=kind)
        if compare(key, found).verdict is Verdict.MATCH:
            result.append(play)
    return result


def playlist_url(airdate: str) -> str:
    """Playlist page of the hour a play aired, in the station's time zone."""
    aired = datetime.fromisoformat(airdate)
    hour = f"{aired.hour % 12 or 12}{'am' if aired.hour < 12 else 'pm'}"  # noqa: PLR2004 -- noon
    return f"https://www.kexp.org/playlist/{aired.year}/{aired.month}/{aired.day}/{hour}/"


def candidate(play: models.Play, kind: EntityKind) -> RecordCandidate:
    """Describe the record a play names."""
    return RecordCandidate(
        kind=kind,
        artist=play.artist or "",
        title=_name(play, kind) or "",
        url=playlist_url(play.airdate),
    )


def _program(show: models.Show | None) -> str:
    if show is None or not show.program_name:
        return STATION
    return f"{STATION}: {show.program_name}"


def _hosts(show: models.Show | None) -> str | None:
    return ", ".join(show.host_names) or None if show is not None else None


def broadcasts(
    plays: list[models.Play],
    shows: Mapping[int, models.Show],
    scope: Scope,
) -> list[Relation]:
    """Each play as a broadcast on its date with the program and hosts."""
    result = []
    for play in plays:
        show = shows.get(play.show) if play.show is not None else None
        url = playlist_url(play.airdate)
        result.append(
            Relation(
                kind=RelationKind.BROADCAST,
                target=Entity(
                    type=EntityType.BROADCAST,
                    name=_program(show),
                    date=play.airdate[:10],
                    url=url,
                ),
                note=_hosts(show),
                scope=scope,
                sources=[Provenance(source=SOURCE, url=url)],
            ),
        )
    return result


def comments(
    plays: list[models.Play],
    shows: Mapping[int, models.Show],
    scope: Scope,
) -> list[Text]:
    """Host comments on the plays, one text per part of a comment."""
    result = []
    for play in plays:
        show = shows.get(play.show) if play.show is not None else None
        for part in _SEPARATOR.split(play.comment or ""):
            body = "\n".join(line.rstrip() for line in part.strip().splitlines())
            if not body:
                continue
            result.append(
                Text(
                    kind=TextKind.BROADCAST,
                    body=body,
                    author=_hosts(show),
                    publication=_program(show),
                    date=play.airdate[:10],
                    scope=scope,
                    sources=[Provenance(source=SOURCE, url=playlist_url(play.airdate))],
                ),
            )
    return result
