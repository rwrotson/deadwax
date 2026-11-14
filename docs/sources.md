# Sources

`deadwax sources` lists every source with its group, whether it is in the default set, its pass, what it contributes, and whether it can run. Each source has the settings `enabled`, `rate` (requests per second), `ttl` (cache lifetime), `user_agent`, and `proxy`, set as `DEADWAX_<SOURCE>__<SETTING>` or in a `[<source>]` TOML table; see [Configuration](configuration.md).

## Groups and the default set

Every source belongs to one group: `core` (the v1 sources), `shops`, `press`, `catalogues`, `radio`, `streaming`, or `samples`. `--sources` and `--exclude` take source and group names, comma-separated; `--sources shops --exclude boomkat` runs every shop except Boomkat. An unknown name is a usage error that lists the known sources and groups.

Without `--sources`, a lookup runs the sources named by `DEADWAX_DEFAULT_SOURCES`, which also takes source and group names; the default is `core,listenbrainz,secondhandsongs,kexp,spotify,youtube`. Sources with official or open APIs join the default set as they are added; sources that scrape shop, press, radio, and sample pages run only when named. `DEADWAX_<SOURCE>__ENABLED=false` turns a source off even when it is named.

`DEADWAX_CONCURRENCY` (default 8) caps how many sources of one lookup run at once. A source's `adapter_timeout` starts when it begins running, not while it waits for a slot.

## How a lookup runs

1. **URL resolution.** For a URL query, the first ready source that recognises the URL reads it alone. Its record becomes the reference, and for a URL that does not reveal its kind it sets the kind. The order is Spotify, MusicBrainz, Odesli, iTunes, Deezer, Discogs, Bandcamp, SoundCloud, Beatport, Hard Wax, Soundohm, Juno: Spotify reads Spotify URLs when it has credentials, MusicBrainz otherwise.
2. **Identity pass.** MusicBrainz finds the recording or release group and gives later sources its IDs and links: ISRCs, barcodes, Discogs, Wikidata, Bandcamp, and streaming URLs.
3. **Enrichment pass.** All other sources except Odesli run concurrently, at most `concurrency` at once. Each one uses the IDs and links from the identity pass first and falls back to its own search.
4. **Links pass.** Odesli opens the song.link page of a streaming URL found by any earlier source, such as the Apple Music link from iTunes. YouTube searches uploads of the record.

Each source runs under `adapter_timeout` (`--timeout`). Every candidate passes the version-aware matching gate described in [Output](output.md).

## Tiers

| Tier | Sources | Role |
|------|---------|------|
| 1, identity and links | MusicBrainz, iTunes Search, Deezer, Odesli | Which exact recording or release this is; listening links |
| 2, enrichment | Discogs, Bandcamp, Last.fm, Wikipedia/Wikidata, ListenBrainz, SecondHandSongs, KEXP, Spotify, SoundCloud, Beatport, Hard Wax, Soundohm, Juno | Tags, credits, texts, relations, metrics |
| 3, links | Odesli, YouTube | Listening links |

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

- **Access:** public HTML at `www.deezer.com`, without an API key.
- **Finds the record by:** a Deezer URL from the query or earlier sources, else HTML search and verification of the linked record pages.
- **Contributes:** Deezer links, and ISRC, barcode, label, and genres when present in the page's embedded data.
- **Limits:** HTML may be blocked on some networks or omit fields; no API fallback is used. Behind a refused proxy, see [Proxies](#proxies).

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
- **Finds the record by:** the query URL, a Bandcamp link from MusicBrainz, else a search. The HTML search page is tried when the search endpoint fails. If both search routes fail, a direct artist-subdomain URL is accepted only after its page confirms the requested artist, title, and kind.
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

## ListenBrainz

- **Group:** `catalogues`; in the default set.
- **Access:** ListenBrainz API, its labs similarity endpoints, and the CritiqueBrainz API; keyless, honest User-Agent.
- **Finds the record by:** the MusicBrainz recording, release group, and artist IDs from the identity pass; without them the source is `not_found`. It reports no candidate, since the IDs belong to the matched record.
- **Contributes:** listen and listener counts as `metrics`; for a track, up to 20 recordings and 10 artists listened to in the same sessions as `similar`; CritiqueBrainz reviews of the recording and release group, as `user` texts, or as `review` texts naming the publication when CritiqueBrainz republishes one (such as BBC Music).
- **Limits:** the labs endpoints are experimental; an empty answer gives no facts.

## SecondHandSongs

- **Group:** `catalogues`; in the default set. Optional `DEADWAX_SECONDHANDSONGS__API_KEY` raises the request limit.
- **Access:** the JSON API at `api.secondhandsongs.com`, keyless; the website is behind a Cloudflare challenge and is not used.
- **Finds the record by:** a performance search by title and performer, through the matching gate. Songs only: an album query contributes nothing.
- **Contributes:** the performance's first release date; writers of the work as `writer` credits; for an original, its covers as `covered_by`; for a cover, the work and the dated original as `cover_of`; for a later recording by the original artist, the first performance as `other_version` and that performance's covers; adaptations (translations, new lyrics) as `cover_of` or `covered_by` works with the note `adaptation`.
- **Limits:** without a key the API allows about 10–20 requests a minute; the default rate is 0.25 per second. Covers carry no dates, which would take one request per cover.

## KEXP

- **Group:** `radio`; in the default set.
- **Access:** KEXP API v2, keyless.
- **Finds the record by:** the MusicBrainz recording ID, else artist and title (the API ignores release group IDs, so albums are found by artist and album title); plays of other records or versions are dropped by the matching gate.
- **Contributes:** the latest 25 plays as `broadcast` relations (program, date, hosts, playlist page); host comments as `broadcast` texts, split at dashed separator lines, with a repeated comment merged into one text.

## Spotify

- **Group:** `streaming`; in the default set.
- **Access:** Web API with the client credentials of a Spotify app (`DEADWAX_SPOTIFY__CLIENT_ID`, `DEADWAX_SPOTIFY__CLIENT_SECRET`); without both the source is `skipped`. The access token is fetched once per lookup and never written to the cache.
- **Finds the record by:** a Spotify URL in the query or from an earlier source; an ISRC or barcode from the identity pass; or a search of at most 10 results through the matching gate.
- **Contributes:** artist, title, release date, ISRC or barcode, ℗ and © lines of the album, the Spotify ID; track, album and artist links. Audio features are never used. Label, popularity (0–100, a metric), and previews are read when Spotify gives them, but it leaves them out for apps in development mode (checked 2026-11-13); such a field stays empty. Search returns at most 10 results.

## YouTube

- **Group:** `streaming`; in the default set.
- **Access:** Data API v3 with a key (`DEADWAX_YOUTUBE__API_KEY`); without it the source is `skipped`. A search costs 100 of the 10,000 daily quota units, about 100 lookups a day; a refused search names the quota or the key.
- **Pass:** links.
- **Finds the record by:** a search of music videos (playlists for an album). An upload counts only when the matching gate says it is the record: a Topic channel ("<artist> - Topic") names the artist, other uploads need an "Artist - Title" title; live takes, covers, and other versions are dropped.
- **Contributes:** links only, at most three: the Topic channel first, then a channel named like the artist (or its VEVO channel), then others. No candidate, tags, texts, or metrics.

## SoundCloud

- **Group:** `streaming`; opt-in.
- **Access:** the `api-v2.soundcloud.com` API with a client ID (`DEADWAX_SOUNDCLOUD__CLIENT_ID`); without it the source is `skipped`. SoundCloud registers no new API apps, and the ID of its web client changes now and then: a refused request reports `failed` and asks whether the ID is stale. deadwax never extracts an ID from the site.
- **Finds the record by:** a SoundCloud URL in the query or from an earlier source, else a track or album search through the matching gate. A set that is a listener's playlist rather than an album or EP is not a record.
- **Contributes:** artist (the distributor's, else an "Artist - Title" title, else the uploader), title, date, ISRC or barcode, ℗ and © lines; the uploader's description as a `label` text; genre and tags; plays, likes, and reposts as metrics; notable reposting accounts as `reposted_by` relations; the upload's link and the uploader's page (`artist` when the uploader is the artist). Edits and bootlegs that only SoundCloud has become `other_version` relations through the matching gate. Of the first 50 reposting accounts, only verified ones or those with at least 1,000 followers become relations; the others are mostly listeners.

## Beatport

- **Group:** `streaming`; opt-in.
- **Access:** scraped pages; the record lives in the Next.js state (`__NEXT_DATA__`) of search, track, and release pages. A rendered page without that state triggers the next HTML transport. Beatport answers plain requests with a Cloudflare challenge; each available transport may still be blocked.
- **Finds the record by:** a Beatport track or release URL in the query or from an earlier source, else a track or release search through the matching gate. Each result's mix name is part of its title, so an Extended Mix found for an Original Mix query becomes an `other_version` relation.
- **Contributes:** for a track: artist (remixers apart), title with mix name and the version it denotes, the release's date, tempo, key, ISRC, label and catalog number; genre and sub-genre as `genre` and `style` tags; remixers as credits; the DJ charts that list it as `charted_by` relations; the page's link. For a release: artist, title, date, barcode, label and catalog number, remixers, and the link; release pages list no genres or tempos.

## Hard Wax

- **Group:** `shops`; opt-in.
- **Access:** the shop's JSON search feed (`/feeds/search.json`) and its product pages; plain HTML, no challenge.
- **Finds the record by:** a Hard Wax product URL in the query or from an earlier source, else a feed search through the matching gate. The feed lists each release's tracks, so a track is found on the release that holds it.
- **Contributes:** the release's one-line description as a `shop` text, its store section as a `genre` tag (format and catalogue sections such as "Label Catalog" and "CDs" are left out), label and catalog number, the product link; for a track, the artist of its tracklist entry and an `appears_on` relation to the release. Hard Wax gives no release dates.

## Soundohm

- **Group:** `shops`; opt-in.
- **Access:** scraped search and product pages; plain HTML with JSON-LD, no challenge.
- **Finds the record by:** a Soundohm product URL in the query or from an earlier source, else a product search through the matching gate. Product pages list no tracks, so a track query is `not_found`.
- **Contributes:** the full product description as a `shop` text (it often reprints the label's press release, which the merge joins with other copies), the genre, label and catalog number, the year, and the product link. Related products are not used: they are not bought-together lists.

## Juno

- **Group:** `shops`; opt-in.
- **Access:** scraped search and product pages of juno.co.uk. Juno answers plain requests with a Cloudflare challenge, so it needs the escalation ladder (`deadwax[stealth]` or `deadwax[browser]`); otherwise it reports `blocked`. The parser was built on pages saved from a browser.
- **Finds the record by:** a Juno product URL in the query or from an earlier source, else a search through the matching gate. Search results list each release's tracks, so a track is found on the release that holds it; Juno's mix names ("Todd Terry club mix") are part of the track's title.
- **Contributes:** the shop review as a `shop` text, the genre as a `genre` tag and Juno's tags as `tag` tags, label and catalog number ("unknown label" is left out), the release date, the product link; for a track, an `appears_on` relation to the release. Artists are as Juno prints them, in capitals. "People also bought" is loaded by the page's scripts and is not read.

## Forced Exposure and Bleep

Both are opt-in `shops` sources and search release titles through the matching gate. Forced Exposure gives label copy, genre, date, label, catalog number, and related releases. Bleep gives editorial copy, genre sections, date, label, catalog number, and an `appears_on` relation when a track is found on a release. Both try Patchright first. Boomkat and Norman Records remain deferred because their product pages answer Cloudflare challenges even through Nodriver with a working Chrome for Testing executable.

## Genius

- **Access:** Genius API with `DEADWAX_GENIUS__TOKEN`; the song page is fetched separately for lyrics. Without a token the source is `skipped`.
- **Finds the record by:** track search through the matching gate. Album queries contribute no facts.
- **Contributes:** description and annotations as texts, writers and producers as credits, samples, covers, remixes and interpolations as directional relations, a song link, and full lyrics when present in the page HTML. A blocked page leaves API facts available and records an error.

## AllMusic

- **Pass:** enrichment; opt-in; group `press`.
- **Contributes:** review text, score and critic; styles, moods, themes, credits, and similar albums.
- **Limits:** direct requests currently meet Cloudflare 403 from the development network. The extraction selectors require verification against a saved page.

## Album of the Year

- **Pass:** enrichment; opt-in; group `catalogues`.
- **Contributes:** critic scores by publication, user score as a metric, genres, and links to original reviews for the later press pass.
- **Limits:** direct requests currently meet Cloudflare 403 from the development network. The extraction selectors require verification against a saved page.

## Escalation ladder

Bandcamp, Beatport, Hard Wax, Soundohm, and Juno pages, the song.link page, and Discogs review pages use browser-like headers, HTTP/2, and cookies. When the response is a challenge page (Cloudflare, Akamai, DataDome, PerimeterX, Fastly, Sucuri, or a captcha on 403/429/503), the client switches to a stronger transport and keeps using it for that source:

| Step | Requires |
|------|----------|
| httpx | base install |
| curl_cffi with Chrome TLS impersonation | `deadwax[stealth]` |
| Patchright Chromium | `deadwax[browser]` or `deadwax[patchright]`, then `patchright install chromium` |
| Nodriver Chrome | `deadwax[nodriver]` and a local Chrome installation |

Each HTML source has an ordered `html_transports` list. The default is `httpx,impersonate,browser,nodriver`, except Beatport (`nodriver,browser,impersonate,httpx`) and Juno (`impersonate,browser,nodriver,httpx`). `browser` means Patchright. Set a source's list in Python with `SourceSettings(html_transports=(Escalation.HTTPX, ...))`, in TOML with `[beatport] html_transports = ["nodriver", "browser"]`, or in the command environment with `DEADWAX_BEATPORT__HTML_TRANSPORTS='["nodriver","browser"]'`. `http.escalation` is a JSON or TOML list of optional transports allowed globally; its default allows all three. A missing or unlaunchable transport is skipped. API requests use httpx only, including Bandcamp's JSON endpoints and the Hard Wax search feed. `DEADWAX_HTTP__BROWSER_HEADLESS=false` opens a visible browser window; the default is headless.

A refused page is remembered in the cache for `cache.blocked_ttl` (default one day) and reported as `blocked … (cached)` without a request. After installing an escalation step, run once with `--no-cache`.

## Proxies

By default HTTP transports use proxy variables from the environment; browsers use their own proxy configuration. `.env` does not set proxy variables for other processes.

`DEADWAX_HTTP__PROXY` sets the proxy of every source, and `DEADWAX_<SOURCE>__PROXY` overrides it for one source. The value is `direct` or an `http://` or `https://` proxy URL with a port. Nodriver cannot use a proxy that requires a user name and password; it reports a configuration error in that case. Bot protection can refuse a proxy's exit address; `DEADWAX_DEEZER__PROXY=direct` bypasses it for Deezer. `DEADWAX_HTTP__NODRIVER_BROWSER_PATH` selects a Chrome executable; `DEADWAX_HTTP__NODRIVER_SANDBOX=false` disables Chrome's sandbox only when explicitly chosen. On this Mac, system Chrome 157 fails external navigation with `ERR_INVALID_HANDLE`; Chrome for Testing 156 works with Nodriver when both settings are supplied.

A page refused on one route does not count as refused on another: changing a source's proxy ignores its cached `blocked` entries.

All sources share per-host rate limits with jitter, bounded retries with backoff that honours `Retry-After`, a response size cap, and the response cache (`--no-cache` bypasses it).
