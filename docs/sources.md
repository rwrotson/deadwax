# Sources

`deadwax sources` lists every source with its group, whether it is in the default set, its pass, what it contributes, and whether it can run. Each source has the settings `enabled`, `rate` (requests per second), `ttl` (cache lifetime), `user_agent`, and `proxy`, set as `DEADWAX_<SOURCE>__<SETTING>` or in a `[<source>]` TOML table; see [Configuration](configuration.md).

## Groups and the default set

Every source belongs to one group: `core` (the v1 sources), `shops`, `press`, `catalogues`, `radio`, `streaming`, or `samples`. `--sources` and `--exclude` take source and group names, comma-separated; `--sources shops --exclude boomkat` runs every shop except Boomkat. An unknown name is a usage error that lists the known sources and groups.

Without `--sources`, a lookup runs the sources named by `DEADWAX_DEFAULT_SOURCES`, which also takes source and group names; the default is `core`. Sources with official or open APIs join the default set as they are added; sources that scrape shop, press, radio, and sample pages run only when named. `DEADWAX_<SOURCE>__ENABLED=false` turns a source off even when it is named.

`DEADWAX_CONCURRENCY` (default 8) caps how many sources of one lookup run at once. A source's `adapter_timeout` starts when it begins running, not while it waits for a slot.

## How a lookup runs

1. **URL resolution.** For a URL query, the first ready source that recognises the URL reads it alone. Its record becomes the reference, and for a URL that does not reveal its kind it sets the kind. The order is MusicBrainz, Odesli, iTunes, Deezer, Discogs, Bandcamp.
2. **Identity pass.** MusicBrainz finds the recording or release group and gives later sources its IDs and links: ISRCs, barcodes, Discogs, Wikidata, Bandcamp, and streaming URLs.
3. **Enrichment pass.** All other sources except Odesli run concurrently. Each one uses the IDs and links from the identity pass first and falls back to its own search.
4. **Links pass.** Odesli opens the song.link page of a streaming URL found by any earlier source, such as the Apple Music link from iTunes.

Each source runs under `adapter_timeout` (`--timeout`). Every candidate passes the version-aware matching gate described in [Output](output.md).

## Tiers

| Tier | Sources | Role |
|------|---------|------|
| 1, identity and links | MusicBrainz, iTunes Search, Deezer, Odesli | Which exact recording or release this is; listening links |
| 2, enrichment | Discogs, Bandcamp, Last.fm, Wikipedia/Wikidata | Tags, credits, texts, relations |

The README lists sources planned for later versions and those deadwax will not use.

## MusicBrainz

- **Access:** WS/2 JSON API, keyless, 1 request a second, with the `deadwax/<version> (+contact)` User-Agent that the API requires.
- **Pass:** identity.
- **Finds the record by:** MusicBrainz IDs in the query; any URL through `ws/2/url`; an ISRC; or a search. Track searches look at official album, EP and single releases first, then a plain search, then the base title. DJ-mix excerpts and videos are excluded.
- **Contributes:** artist, title, version, date, ISRCs, labels and catalog numbers, barcode; credits (producer, engineer, instruments, vocals, remixer, writers from the work); tags and genres with vote weights; members and projects; covers, remixes, samples, mixes, appearances on releases and compilations; streaming and shop links; Discogs, Wikidata and Bandcamp IDs.
- **Limits:** the public server answers "503 server busy" under load. Retries use `http.retry_base` and usually recover.

## iTunes Search

- **Access:** `itunes.apple.com/search` and `/lookup`, keyless, about 20 requests a minute.
- **Finds the record by:** the Apple Music link that MusicBrainz curates, else a search; it resolves Apple Music URLs.
- **Contributes:** Apple Music track, album and artist links with previews, release date, and primary genre.
- **Limits:** names are compared as written, so "Kino" does not match "Кино" and gives `no_match`.

## Deezer

- **Access:** `api.deezer.com`, keyless.
- **Finds the record by:** ISRC (track) or barcode (album) from the identity pass, else a search; it resolves Deezer URLs.
- **Contributes:** Deezer links and previews, ISRC, barcode, label, and genres.
- **Limits:** Akamai refuses some networks with an "Access Denied" page. This is reported as `blocked`. Behind a refused proxy, see [Proxies](#proxies).

## Odesli (song.link)

- **Access:** the song.link web page of a streaming link, fetched with the browser profile and the escalation ladder. Odesli has had no public API since 2026-07-31.
- **Finds the record by:** the query URL, or a Spotify, Apple Music, Deezer, Tidal or YouTube link found by an earlier source. Without one it reports `not_found`.
- **Contributes:** links on every platform Odesli matches, plus the title, artist, and ISRC or UPC of the record.
- **Limits:** a platform that spells the artist differently gives `no_match`. song.link sometimes links another version on the seed's own platform, such as an instrumental; a link there that does not name the seed's ID is dropped. Links on other platforms are taken as song.link gives them.

## Discogs

- **Access:** API v2. Discogs refused every User-Agent naming deadwax on 2026-11-12, so httpx's own User-Agent is sent (`discogs.user_agent` overrides it).
- **Credentials:** `DEADWAX_DISCOGS__TOKEN` (personal access token), needed for search and compilations. Without it, Discogs reads records by the Discogs IDs from MusicBrainz at 25 requests a minute, and a lookup that would need a search is `skipped`.
- **Contributes:** genres and styles, credits with roles and tracks, database notes, labels and catalog numbers, barcodes, other versions of the master, compilations, the label's other releases, members, groups and aliases.
- **Reviews:** user reviews come from the release page through the browser profile and the escalation ladder. A refused page is reported as `blocked` with a `reviews:` reason and loses only the reviews.
- **Limits:** "Not On Label" and placeholder aliases are not treated as labels or relations.

## Bandcamp

- **Access:** no API. The album or track page (`data-tralbum`, `data-embed`, JSON-LD), the mobile `tralbum_details` API, and the search endpoint are read with the browser profile and the escalation ladder.
- **Finds the record by:** the query URL, a Bandcamp link from MusicBrainz, else a search. The HTML search page (behind a Fastly challenge) is tried only when the search endpoint fails.
- **Contributes:** tags, About and Credits texts, simple credits, fan comments, recommendations as `similar`, the label from the mobile API, and the label's other releases when the label is the selling account.
- **Limits:** a track found on another artist's album (a compilation or third-party upload) contributes only its identity, links, own notes, and a `compilation` relation.

## Last.fm

- **Access:** API with `DEADWAX_LASTFM__API_KEY`. The source is `skipped` without the key.
- **Contributes:** `track.getInfo` or `album.getInfo` tags with weights (artist-wide tags are marked `artist`), wiki texts, and similar tracks (for a track) or similar artists (for an album).
- **Limits:** errors arrive inside 200 responses: code 6 means not found, 29 means rate limited.

## Wikipedia and Wikidata

- **Access:** MediaWiki and Wikidata APIs, keyless, honest User-Agent.
- **Finds the record by:** the Wikidata ID from MusicBrainz, else a Wikidata search by title, type, and performer.
- **Contributes:** genres, producers, composers, lyricists, labels, release date, the album a song is on, review scores (Wikidata P444 and the ratings templates of the articles), and the lead plus music-related sections of the English article and the article in the record's original language.
- **Limits:** section headings are recognised in English, Russian, Japanese, German, and French; other languages contribute only the lead. A sitelink that redirects (a song's link to its album) is skipped.

## Escalation ladder

Bandcamp pages, the song.link page, and Discogs review pages use browser-like headers, HTTP/2, and cookies. When the response is a challenge page (Cloudflare, Akamai, DataDome, PerimeterX, Fastly, or a captcha on 403/429/503), the client switches to a stronger transport and keeps using it for that source:

| Step | Requires |
|------|----------|
| httpx | base install |
| curl_cffi with Chrome TLS impersonation | `deadwax[stealth]` |
| Playwright Chromium | `deadwax[browser]` and `playwright install chromium` |

`DEADWAX_HTTP__ESCALATION=none|impersonate|browser` caps the ladder. By default it goes up to the strongest available step: when a step cannot run (the `browser` extra is installed but Chromium is not), the ladder ends below it and the page is reported as `blocked` with the reason and the install hint. A step chosen explicitly that cannot run is a configuration error. API sources never escalate.

A refused page is remembered in the cache for `cache.blocked_ttl` (default one day) and reported as `blocked … (cached)` without a request. After installing an escalation step, run once with `--no-cache`.

## Proxies

By default every transport except Chromium uses the proxy from `HTTPS_PROXY`, `HTTP_PROXY`, `ALL_PROXY`, and `NO_PROXY` in the process environment. `.env` does not set these variables: deadwax reads it into its own settings only.

`DEADWAX_HTTP__PROXY` sets the proxy of every source, and `DEADWAX_<SOURCE>__PROXY` overrides it for one source. The value is `direct` (no proxy, the environment ignored) or an `http://` or `https://` proxy URL with a port, optionally with `user:password@`. The setting applies to httpx, curl_cffi, and Chromium. Bot protection sometimes refuses a proxy's exit address, for example Akamai for Deezer or Cloudflare for Discogs review pages. In that case, `DEADWAX_DEEZER__PROXY=direct` sends that source's requests past the proxy.

A page refused on one route does not count as refused on another: changing a source's proxy ignores its cached `blocked` entries.

All sources share per-host rate limits with jitter, bounded retries with backoff that honours `Retry-After`, a response size cap, and the response cache (`--no-cache` bypasses it).
