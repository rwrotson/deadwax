from deadwax.core import (
    Capability,
    EntityKind,
    IdKind,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Query,
    Scope,
    SourceGroup,
)
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._search import search_key
from deadwax.sources.adapters.kexp import models
from deadwax.sources.adapters.kexp import parse as p

API = "https://api.kexp.org/v2"
PLAYS = "25"


class KexpAdapter(HttpAdapter):
    """Plays of the record on KEXP with their programs, hosts, and host comments."""

    name = "kexp"
    pass_ = Pass.ENRICH
    group = SourceGroup.RADIO
    service = None
    capabilities = frozenset({Capability.IDENTITY, Capability.TEXTS, Capability.RELATIONS})

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Read the latest plays by MusicBrainz recording ID, else by artist and title."""
        key = search_key(query, context)
        if key is None:
            raise NotFoundError("neither the query nor earlier sources name the record")
        kind = key.kind or EntityKind.TRACK
        # The API filters plays by recording ID but ignores release group IDs.
        if kind is EntityKind.ALBUM:
            scope = Scope.RELEASE_GROUP
            params = {"artist": key.artist, "album": key.title}
        else:
            scope = Scope.RECORDING
            recording = context.id(IdKind.MUSICBRAINZ_RECORDING)
            params = (
                {"recording_id": recording}
                if recording
                else {"artist": key.artist, "song": key.title}
            )

        response = await self.client.get(f"{API}/plays/", params={**params, "limit": PLAYS})
        found = models.Plays.model_validate_json(response.content).results
        plays = p.matching(found, key, kind)
        if not plays:
            raise NotFoundError("no KEXP plays of the record", url=response.url)

        shows: dict[int, models.Show] = {}
        for show_id in dict.fromkeys(play.show for play in plays if play.show is not None):
            show = await self.client.get(f"{API}/shows/{show_id}/")
            shows[show_id] = models.Show.model_validate_json(show.content)
        return Partial(
            source=self.name,
            candidate=p.candidate(plays[0], kind),
            relations=p.broadcasts(plays, shows, scope),
            texts=p.comments(plays, shows, scope),
        )
