import json
import logging

from deadwax.core import (
    BlockedError,
    Capability,
    EntityKind,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Query,
    RecordKey,
    Relation,
    SourceError,
    recognize_url,
)
from deadwax.sources._base import HttpAdapter, search_key, service_for_url
from deadwax.sources._http import Profile
from deadwax.sources.bandcamp import models
from deadwax.sources.bandcamp import parse as p

logger = logging.getLogger(__name__)

SEARCH_API = "https://bandcamp.com/api/bcsearch_public_api/1/autocomplete_elastic"
SEARCH_PAGE = "https://bandcamp.com/search"
MOBILE_API = "https://bandcamp.com/api/mobile/24/tralbum_details"


class BandcampAdapter(HttpAdapter):
    """Tags, notes, credits, fan texts, and recommendations from Bandcamp release pages."""

    name = "bandcamp"
    pass_ = Pass.ENRICH
    capabilities = frozenset(
        {
            Capability.IDENTITY,
            Capability.LINKS,
            Capability.TAGS,
            Capability.CREDITS,
            Capability.TEXTS,
            Capability.RELATIONS,
        }
    )
    profile = Profile.BROWSER

    def resolves(self, query: Query) -> bool:
        """Album and track pages on bandcamp.com subdomains; custom domains are not recognized."""
        return query.url is not None and service_for_url(query.url) == "bandcamp"

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Read the page from the query, an earlier pass, or a search, then its label's page."""
        key = search_key(query, context)
        kind = query.kind or (key.kind if key is not None else None)
        found = await self._find(query, context, key, kind)
        if found is None:
            raise NotFoundError("no matching Bandcamp release")
        record, details = found
        if details is not None:
            record = p.with_details(record, details)
        record = p.own_facts(record)
        return p.partial(record, await self._label_releases(record))

    async def _find(
        self, query: Query, context: LookupContext, key: RecordKey | None, kind: EntityKind | None
    ) -> tuple[p.Record, models.MobileDetails | None] | None:
        if self.resolves(query) and query.url is not None:
            return await self._open(query.url, key, kind)
        pages = _known_pages(context, kind)
        if pages:
            return await self._open(pages[0], key, kind)
        if key is None:
            raise NotFoundError("neither the query nor earlier sources name the record")
        result = await self._search(key)
        if result is None or result.item_url_path is None:
            return None
        try:
            return await self._open(result.item_url_path, key, kind)
        except BlockedError:
            if result.band_id is None:
                raise
            logger.debug("bandcamp page blocked; reading the mobile API instead")
            details = await self._details(result.band_id, result.id, result.type)
            if details is None:
                raise
            return p.details_record(details), None

    async def _open(
        self, url: str, key: RecordKey | None, kind: EntityKind | None
    ) -> tuple[p.Record, models.MobileDetails | None]:
        """Read a page, moving between a track's page and its album's page to match the kind."""
        record = await self._page(url)
        if kind is EntityKind.TRACK and record.kind is EntityKind.ALBUM and key is not None:
            track = p.track_url(record, key)
            if track is None:
                raise NotFoundError("the queried track is not on the Bandcamp album", url=url)
            record = await self._page(track)
        elif kind is EntityKind.ALBUM and record.kind is EntityKind.TRACK:
            if record.album is None or record.album.url is None:
                raise NotFoundError("the Bandcamp track page names no album", url=url)
            record = await self._page(record.album.url)
        details = None
        if record.band_id is not None and record.id is not None:
            item_type = "t" if record.kind is EntityKind.TRACK else "a"
            details = await self._details(record.band_id, record.id, item_type)
        return record, details

    async def _page(self, url: str) -> p.Record:
        response = await self.client.get(p.page_url(url))
        record = p.page_record(p.read_page(response.content, response.url))
        if record is None:
            raise SourceError("the page has no release data", url=response.url)
        return record

    async def _details(
        self, band_id: int, item_id: int, item_type: str
    ) -> models.MobileDetails | None:
        """Ask the mobile API, which names the label; its failure costs only the label."""
        params = {"band_id": str(band_id), "tralbum_id": str(item_id), "tralbum_type": item_type}
        try:
            response = await self.client.get(MOBILE_API, params=params)
            return models.MobileDetails.model_validate_json(response.content)
        except SourceError, ValueError:
            logger.debug("bandcamp mobile API gave no details for %s", item_id, exc_info=True)
            return None

    async def _search(self, key: RecordKey) -> models.SearchResult | None:
        """Search with the autocomplete endpoint; the HTML search page only when it fails."""
        item_type = "t" if key.kind is EntityKind.TRACK else "a"
        body = {
            "search_text": f"{key.artist} {key.title}",
            "search_filter": item_type,
            "full_page": False,
            "fan_id": None,
        }
        try:
            response = await self.client.request(
                "POST",
                SEARCH_API,
                headers={"content-type": "application/json", "accept": "application/json"},
                body=json.dumps(body).encode(),
            )
            results = models.SearchResponse.model_validate_json(response.content).auto.results
        except SourceError, ValueError:
            logger.debug("bandcamp search endpoint failed", exc_info=True)
        else:
            return p.pick_result(key, results)
        response = await self.client.get(
            SEARCH_PAGE, params={"q": f"{key.artist} {key.title}", "item_type": item_type}
        )
        return p.pick_result(key, p.html_search(response.content))

    async def _label_releases(self, record: p.Record) -> list[Relation]:
        """List the label's other releases when the release is sold from the label's account."""
        if not (record.label and record.seller_url and p.same_name(record.label, record.seller)):
            return []
        try:
            response = await self.client.get(f"{record.seller_url.rstrip('/')}/music")
        except SourceError:
            logger.debug("bandcamp label page failed", exc_info=True)
            return []
        return p.label_releases(response.content, response.url, record.label, record.id)


def _known_pages(context: LookupContext, kind: EntityKind | None) -> list[str]:
    """Bandcamp pages earlier passes found, the queried kind first."""
    pages = [url for url in context.urls("bandcamp") if recognize_url(url)[0] is not None]
    return sorted(pages, key=lambda url: recognize_url(url)[0] is not kind)
