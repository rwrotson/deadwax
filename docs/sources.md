# Sources

`deadwax sources` lists every source with its group, whether it is in the default set, its pass, the record kinds it looks up, what it contributes, and whether it can run. Genius, SecondHandSongs, NTS, WFMU, 1001Tracklists, and WhoSampled look up tracks only and do not run for an album. Each source has the settings `enabled`, `rate` (requests per second), `ttl` (cache lifetime), `user_agent`, and `proxy`, set as `DEADWAX_SOURCES__<SOURCE>__<SETTING>` or in a `[<source>]` TOML table; see [Configuration](configuration.md).

Its Access column shows the configured retrieval methods: API requests use httpx; HTML pages use the listed transports in order. `impersonate` uses curl_cffi, `patchright` uses Patchright, and `nodriver` uses Nodriver. Browser transports show their configured `headed` or `headless` mode; `headless → headed` means a challenged headless page is retried in a window (`http.headed_fallback`). If the global allowlist leaves an HTML source with no transport, `sources` shows `HTML (no permitted transports)` and a disabled status; lookups omit that source, including any API work it could do. The list does not check whether optional packages are installed or whether a site will accept a request. Flags on a separate lookup can override its browser mode.

Lookup errors marked `blocked` carry the source's access configuration for that run. The terminal and Markdown error tables show it in an Access column; JSON has a structured `access` field with `api`, `html_transports`, `browser_headless`, and `headed_fallback`; `deadwax sources --format json` nests the same field in each source.

## Groups and the default set

Every source belongs to one group: `core` (the v1 sources), `shops`, `press`, `catalogues`, `radio`, `streaming`, or `samples`. `--sources` and `--exclude` take source and group names, comma-separated; `--sources all` selects every source, while `--sources shops --exclude boomkat` runs every shop except Boomkat. Disabled sources are still omitted, and sources missing credentials are reported as skipped. An unknown name is a usage error that lists the known sources and groups.

Without `--sources`, a lookup uses `DEADWAX_DEFAULT_SOURCES`, which accepts source and group names. Its default contains 29 sources.

```text
musicbrainz,itunes,odesli,bandcamp,wikipedia,lastfm,discogs,listenbrainz,secondhandsongs,kexp,spotify,youtube,genius,albumoftheyear,allmusic,beatport,bleep,deezer,forcedexposure,hardwax,juno,nts,phonica,pressreviews,ra,rateyourmusic,soundcloud,soundohm,wfmu
```

Boomkat, Norman Records, WhoSampled, and 1001Tracklists are opt-in because they start in a visible browser. The automatic headed fallback still applies to eligible challenges in headless browsers. `DEADWAX_SOURCES__<SOURCE>__ENABLED=false` disables an individual source even when selected.

`DEADWAX_CONCURRENCY` (default 8) caps how many sources of one lookup run at once. A source's `adapter_timeout` starts when it begins running, not while it waits for a slot.

## How a lookup runs

1. **URL resolution.** For a URL query, the first ready source that recognises the URL reads it alone. Its record becomes the reference, and for a URL that does not reveal its kind it sets the kind. The order is Spotify, MusicBrainz, Odesli, iTunes, Deezer, Discogs, Bandcamp, SoundCloud, Beatport, Hard Wax, Soundohm, Juno: Spotify reads Spotify URLs when it has credentials, MusicBrainz otherwise.
2. **Identity pass.** MusicBrainz finds the recording or release group and gives later sources its IDs and links: ISRCs, barcodes, Discogs, Wikidata, Bandcamp, and streaming URLs.
3. **Enrichment pass.** All other sources except Odesli run concurrently, at most `concurrency` at once. Each one uses the IDs and links from the identity pass first and falls back to its own search.
4. **Links pass.** Odesli opens the song.link page of a streaming URL found by any earlier source, such as the Apple Music link from iTunes. YouTube searches uploads of the record.

Each source runs under `adapter_timeout` (`--timeout`). Waiting for another source to release a shared persistent browser profile does not consume that budget; active fetching and parsing do. A full lookup may take longer as browser sources queue for the profile. Every candidate passes the version-aware matching gate described in [Output](output.md).

## Tiers

| Tier | Sources | Role |
|------|---------|------|
| 1, identity and links | MusicBrainz, iTunes Search, Deezer, Odesli | Which exact recording or release this is; listening links |
| 2, enrichment | Discogs, Bandcamp, Last.fm, Wikipedia/Wikidata, ListenBrainz, SecondHandSongs, Genius, Album of the Year, Rate Your Music, KEXP, NTS, WFMU, 1001Tracklists, Spotify, SoundCloud, Beatport, Hard Wax, Soundohm, Juno, Forced Exposure, Bleep, Phonica, Boomkat, Norman Records, AllMusic, WhoSampled | Tags, credits, texts, relations, metrics |
| 3, links | Odesli, YouTube, press reviews, Resident Advisor | Listening links; reviews found through links of earlier passes |

The README lists deferred sources and those deadwax will not use.

## MusicBrainz

- **Access:** WS/2 JSON API, keyless, 1 request a second, with the `deadwax/<version> (+contact)` User-Agent that the API requires.
- **Pass:** identity.
- **Finds the record by:** MusicBrainz IDs in the query; any URL through `ws/2/url`; the query's ISRC (`ws/2/isrc`, ranked through the matching gate); or a search. Track searches look at official album, EP and single releases first, then a plain search, then the base title. DJ-mix excerpts and videos are excluded.
- **Contributes:** artist, title, version, date, ISRCs, labels and catalog numbers, barcode; credits (producer, engineer, instruments, vocals, remixer, writers from the work); tags and genres with vote weights; members and projects of the first credited artist, and its other artist relations (is person, collaboration, supporting musicians, subgroup, founder, rename, tribute, producer) as `associated` with the type in the note; covers, remixes, samples, mixes, appearances on releases and compilations; streaming and shop links; Discogs, Wikidata and Bandcamp IDs.
- **Artists and labels:** found by MusicBrainz IDs from the query or an earlier pass, a URL through `ws/2/url`, or a name search ranked through the matching gate. Contributes name, disambiguation, type, country, begin and end dates, Discogs and Wikidata IDs; tags and genres; aliases without search hints as `alias`; for an artist, members, projects and other artist relations, labels with a recording contract as `label`, and up to 25 official albums and EPs without secondary types as `release`; for a label, owners and imprints as `parent_label` and `sublabel`, and founders and signed artists as `associated`; streaming and shop links of the artist or label.
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
- **Credentials:** `DEADWAX_SOURCES__DISCOGS__TOKEN` (personal access token), needed for search and compilations. Without it, Discogs reads profiles and records by ID from the query or MusicBrainz at 25 requests a minute. A lookup that needs search is `skipped`.
- **Contributes:** genres and styles, credits with roles and tracks, database notes, labels and catalog numbers, barcodes, other versions of the master, compilations, the label's other releases, members, groups and aliases.
- **Artists and labels:** identity, profile text, and links. For artists, Discogs provides real names where listed, members, groups, aliases and name variations, and up to 12 main masters from the first page of the discography sorted by year. For labels, it provides parent labels, sublabels, and up to 12 catalog releases from the first page.
- **Reviews:** user reviews come from the release page through the browser profile and the escalation ladder. A refused page is reported as `blocked` with a `reviews:` reason and loses only the reviews.
- **Limits:** "Not On Label" and placeholder aliases are not treated as labels or relations.

## Bandcamp

- **Access** uses public HTML for release and account pages and plain HTTP for the autocomplete and mobile `tralbum_details` endpoints.
- **Finds the record by:** the query URL, a Bandcamp link from MusicBrainz, else a search. The HTML search page is tried when the search endpoint fails. If both search routes fail, a direct artist-subdomain URL is accepted only after its page confirms the requested artist, title, and kind.
- **Contributes:** tags, About and Credits texts, simple credits, fan comments, recommendations as `similar`, the label from the mobile API, and the label's other releases when the label is the selling account; for a track page whose track can be played, the `mp3-128` stream as the track link's `preview_url` (an `https` URL on `bcbits.com`; nothing is downloaded).
- **Artists and labels** use a direct Bandcamp account URL, a link from MusicBrainz, or an autocomplete name search. The account's `is_label` field resolves its URL to an artist or label. Account pages contribute a name, profile location, biography when present, Bandcamp link, and up to 12 albums from the visible catalogue as `release` or `label_release` relations.
- **Limits:** a track found on another artist's album (a compilation or third-party upload) contributes only its identity, links, own notes, stream, and a `compilation` relation. The stream URL is signed and expires about 24 hours after the page was fetched; pages are cached for 12 hours (`DEADWAX_SOURCES__BANDCAMP__TTL`), so a returned URL stays valid for at least about 12 hours. Fetch a new dossier to play it later. Album pages give no preview.

## Last.fm

- **Access:** API with `DEADWAX_SOURCES__LASTFM__API_KEY`. The source is `skipped` without the key.
- **Tracks and albums:** weighted tags, wiki texts, similar tracks (for a track), and up to 10 similar artists. Artist-wide facts have scope `artist`.
- **Artists:** looks up a known MusicBrainz artist ID or searches by name with autocorrection. Accepts Last.fm artist profile URLs. Returns artist identity, biography, up to 10 weighted tags and 10 similar artists, and lifetime listener and scrobble counts.
- **Limits:** errors arrive inside 200 responses: code 6 means not found, 29 means rate limited.

## Wikipedia and Wikidata

- **Access:** MediaWiki and Wikidata APIs, keyless, honest User-Agent.
- **Finds the record by:** the Wikidata ID from MusicBrainz, else a Wikidata search by title, type, and performer.
- **Finds the artist or label by:** a known Wikidata ID, then exact MusicBrainz or Discogs ID statements. Without those IDs it searches by name for items with a MusicBrainz artist or label ID and compares their labels and aliases.
- **Contributes for tracks and albums:** genres, producers, composers, lyricists, labels, release date, the album a song is on, review scores (Wikidata P444 and article ratings templates), and the lead and music-related sections of the English and original-language articles.
- **Contributes for artists and labels:** identity fields and external IDs, genres, artists' labels, members and projects, parent labels and sublabels, plus article leads and sections on career, history, style, and influences when available.
- **Limits:** section headings are recognised in English, Russian, Japanese, German, and French; other languages contribute only the lead. A sitelink that redirects (a song's link to its album) is skipped.

## ListenBrainz

- **Group:** `catalogues`; in the default set.
- **Access:** ListenBrainz API, its labs similarity endpoints, and the CritiqueBrainz API; keyless, honest User-Agent.
- **Finds the record by:** the MusicBrainz recording, release group, and artist IDs from the identity pass; without them the source is `not_found`. It reports no candidate, since the IDs belong to the matched record.
- **Contributes:** listen and listener counts as `metrics`; for a track, up to 20 recordings and 10 artists listened to in the same sessions as `similar`; LB Radio recordings by similar artists of the first credited artist as `similar_artist_recording` (`sources.listenbrainz.radio_artists` artists, 8 by default, × `radio_per_artist` recordings, 2 by default; easy mode, every popularity; the artist's own recordings dropped, titles and artist credits from the metadata endpoint); CritiqueBrainz reviews of the recording and release group, as `user` texts, or as `review` texts naming the publication when CritiqueBrainz republishes one (such as BBC Music).
- **Limits:** the labs endpoints are experimental; an empty answer gives no facts.

## SecondHandSongs

- **Group:** `catalogues`; in the default set. Optional `DEADWAX_SOURCES__SECONDHANDSONGS__API_KEY` raises the request limit.
- **Access:** the JSON API at `api.secondhandsongs.com`, keyless; the website is behind a Cloudflare challenge and is not used.
- **Finds the record by:** a performance search by title and performer, through the matching gate. Songs only: it does not run for an album.
- **Contributes:** the performance's first release date; writers of the work as `writer` credits; for an original, its covers as `covered_by`; for a cover, the work and the dated original as `cover_of`; for a later recording by the original artist, the first performance as `other_version` and that performance's covers; adaptations (translations, new lyrics) as `cover_of` or `covered_by` works with the note `adaptation`.
- **Limits:** without a key the API allows about 10–20 requests a minute; the default rate is 0.25 per second. Covers carry no dates, which would take one request per cover.

## KEXP

- **Group:** `radio`; in the default set.
- **Access:** KEXP API v2, keyless.
- **Finds the record by:** the MusicBrainz recording ID, else artist and title (the API ignores release group IDs, so albums are found by artist and album title); plays of other records or versions are dropped by the matching gate.
- **Contributes:** the latest 25 plays as `broadcast` relations (program, date, hosts, playlist page); host comments as `broadcast` texts, split at dashed separator lines, with a repeated comment merged into one text.

## NTS

- **Group:** `radio`; in the default set.
- **Access:** public NTS JSON track search (`version=2`) and episode endpoints. Search results are checked by artist and title before at most ten matching episodes are read.
- **Contributes:** matching episodes as `broadcast` relations, the immediately preceding and following tracks as `co_played` relations, and episode genres as tags with `context_url` set to the episode URL.

## WFMU

- **Group:** `radio`; in the default set.
- **Access:** the public artist browser and playlist HTML. The basic and advanced search forms report that searches cannot run, but the artist browser still lists plays. Up to ten recent matching playlists are read and checked by artist, title, and version.
- **Contributes:** dated playlists as `broadcast` relations and comments attached to the matching row as `broadcast` texts. A host is named as the text's author only when the program title identifies one.

## Rate Your Music

- **Group:** `catalogues`; in the default set. Automated access requires express permission from RYM.
- **Access:** browser first, using the `browser` extra. Searches releases or songs and reads the matched page.
- **Contributes:** primary and secondary genres, descriptors, average user score and rating count, chart relations with displayed position, and up to ten visible full user reviews.
- **Limits:** live page parsing is unverified while DNS access to RYM is unavailable in the development environment.

## 1001Tracklists

- **Group:** `radio`; opt-in.
- **Access:** public track search form followed by track and set pages through a visible browser by default. The adapter waits eight seconds between requests by default; use `--timeout 120` for a lookup with up to five sets.
- **Contributes:** up to five verified `mix` relations with set date and supporting DJ, plus immediate neighbours as `co_played` relations. Sets are checked against the track and version before contributing facts.

## WhoSampled

- **Group:** `samples`; opt-in.
- **Access:** direct recording pages through a visible browser by default. The site's search path is excluded by `robots.txt`, so the adapter constructs the record URL from artist and title and verifies the page's identity.
- **Contributes:** directional sample, cover, and remix relations; sample element and offsets from linked connection pages when shown.

## Spotify

- **Group:** `streaming`; in the default set.
- **Access:** Web API with the client credentials of a Spotify app (`DEADWAX_SOURCES__SPOTIFY__CLIENT_ID`, `DEADWAX_SOURCES__SPOTIFY__CLIENT_SECRET`); without both the source is `skipped`. The access token is fetched once per lookup and never written to the cache.
- **Finds the record by:** a Spotify URL in the query or from an earlier source; the query's ISRC, else an ISRC or barcode from the identity pass; or a search of at most 10 results through the matching gate.
- **Contributes:** artist, title, release date, ISRC or barcode, ℗ and © lines of the album, the Spotify ID; track, album and artist links. Audio features are never used. Label, popularity (0–100, a metric), and previews are read when Spotify gives them, but it leaves them out for apps in development mode (checked 2026-11-13); such a field stays empty. Search returns at most 10 results.

## YouTube

- **Group:** `streaming`; in the default set.
- **Access:** Data API v3 with a key (`DEADWAX_SOURCES__YOUTUBE__API_KEY`); without it the source is `skipped`. A search costs 100 of the 10,000 daily quota units, about 100 lookups a day; a refused search names the quota or the key.
- **Pass:** links.
- **Finds the record by:** a search of music videos (playlists for an album). An upload counts only when the matching gate says it is the record: a Topic channel ("<artist> - Topic") names the artist, other uploads need an "Artist - Title" title; live takes, covers, and other versions are dropped.
- **Contributes:** links only, at most three: the Topic channel first, then a channel named like the artist (or its VEVO channel), then others. No candidate, tags, texts, or metrics.

## SoundCloud

- **Group:** `streaming`; in the default set.
- **Access:** the `api-v2.soundcloud.com` API with a client ID (`DEADWAX_SOURCES__SOUNDCLOUD__CLIENT_ID`); without it the source is `skipped`. SoundCloud registers no new API apps, and the ID of its web client changes now and then: a refused request reports `failed` and asks whether the ID is stale. deadwax never extracts an ID from the site.
- **Finds the record by:** a SoundCloud URL in the query or from an earlier source, else a track or album search through the matching gate. A set that is a listener's playlist rather than an album or EP is not a record.
- **Contributes:** artist (the distributor's, else an "Artist - Title" title, else the uploader), title, date, ISRC or barcode, ℗ and © lines; the uploader's description as a `label` text; genre and tags; plays, likes, and reposts as metrics; notable reposting accounts as `reposted_by` relations; the upload's link and the uploader's page (`artist` when the uploader is the artist). Edits and bootlegs that only SoundCloud has become `other_version` relations through the matching gate. Of the first 50 reposting accounts, only verified ones or those with at least 1,000 followers become relations; the others are mostly listeners.

## Beatport

- **Group:** `streaming`; in the default set.
- **Access:** scraped pages; the record lives in the Next.js state (`__NEXT_DATA__`) of search, track, and release pages. A rendered page without that state triggers the next HTML transport. Beatport answers plain requests with a Cloudflare challenge; each available transport may still be blocked.
- **Finds the record by:** a Beatport track or release URL in the query or from an earlier source, else a track or release search through the matching gate. Each result's mix name is part of its title, so an Extended Mix found for an Original Mix query becomes an `other_version` relation.
- **Contributes:** for a track: artist (remixers apart), title with mix name and the version it denotes, the release's date, tempo, key, ISRC, label and catalog number; genre and sub-genre as `genre` and `style` tags; remixers as credits; the DJ charts that list it as `charted_by` relations; the page's link. For a release: artist, title, date, barcode, label and catalog number, remixers, and the link; release pages list no genres or tempos.

## Hard Wax

- **Group:** `shops`; in the default set.
- **Access:** the shop's JSON search feed (`/feeds/search.json`) and its product pages; plain HTML, no challenge.
- **Finds the record by:** a Hard Wax product URL in the query or from an earlier source, else a feed search through the matching gate. The feed lists each release's tracks, so a track is found on the release that holds it.
- **Contributes:** the release's one-line description as a `shop` text, its store section as a `genre` tag (format and catalogue sections such as "Label Catalog" and "CDs" are left out), label and catalog number, the product link; for a track, the artist of its tracklist entry and an `appears_on` relation to the release. Hard Wax gives no release dates.

## Soundohm

- **Group:** `shops`; in the default set.
- **Access:** scraped search and product pages; plain HTML with JSON-LD, no challenge.
- **Finds the record by:** a Soundohm product URL in the query or from an earlier source, else a product search through the matching gate. Product pages list no tracks, so a track query is `not_found`.
- **Contributes:** the full product description as a `shop` text (it often reprints the label's press release, which the merge joins with other copies), the genre, label and catalog number, the year, and the product link. Related products are not used: they are not bought-together lists.

## Juno

- **Group:** `shops`; in the default set.
- **Access:** scraped search and product pages of juno.co.uk. Juno answers plain requests with a Cloudflare challenge, so it needs the escalation ladder (`deadwax[stealth]` or `deadwax[browser]`); otherwise it reports `blocked`. The parser was built on pages saved from a browser.
- **Finds the record by:** a Juno product URL in the query or from an earlier source, else a search through the matching gate. Search results list each release's tracks, so a track is found on the release that holds it; Juno's mix names ("Todd Terry club mix") are part of the track's title.
- **Contributes:** the shop review as a `shop` text, the genre as a `genre` tag and Juno's tags as `tag` tags, label and catalog number ("unknown label" is left out), the release date, the product link; for a track, an `appears_on` relation to the release. Artists are as Juno prints them, in capitals. "People also bought" is loaded by the page's scripts and is not read.

## Forced Exposure and Bleep

Both are in the default set and search release titles through the matching gate. Forced Exposure gives label copy, genre, date, label, catalog number, and related releases. Bleep gives editorial copy, genre sections, date, label, catalog number, and an `appears_on` relation when a track is found on a release. Both try Patchright first.

## Phonica, Boomkat, and Norman Records

Phonica is in the default set. It uses headless Patchright and sends search POSTs from the browser page with its profile cookies, searching the release title and artist separately. Boomkat and Norman Records are opt-in. Boomkat searches through the matching gate and reads its editorial description and genres; it uses visible Patchright by default. Norman Records uses visible Nodriver and reads a direct product URL or one supplied by an earlier source; its text search is unavailable. The verified *Untrue* product has no staff review, so it contributes identity and genres only. Boomkat and Norman Records returned Cloudflare challenges in headless mode during the live probe.

## Genius

- **Group:** `catalogues`; in the default set.
- **Access:** Genius API with `DEADWAX_SOURCES__GENIUS__TOKEN`; the song page is fetched separately for lyrics. Without a token the source is `skipped`.
- **Finds the record by:** track search through the matching gate. Album queries contribute no facts.
- **Contributes:** description and annotations as texts, writers and producers as credits, samples, covers, remixes and interpolations as directional relations, a song link, and full lyrics when present in the page HTML. A blocked page leaves API facts available and records an error.

## AllMusic

- **Pass:** enrichment; in the default set; group `press`.
- **Contributes:** review text, score and critic; styles, moods, themes, credits, and similar albums.
- **Limits:** the *OK Computer* search and album page were verified through a persistent Patchright profile. Direct requests may still meet Cloudflare 403; similar-album extraction has not been verified on a live page.

## Album of the Year

- **Pass:** enrichment; in the default set; group `catalogues`.
- **Contributes:** critic scores by publication, user score as a metric, genres, and links to original reviews for the later press pass.
- **Tracks:** a track query searches releases and accepts one, such as the track's single, only when its tracklist lists the track; the track is related to that release, and the release's scores keep the release-group scope.
- **Limits:** Cloudflare refuses direct requests. The parser was checked against saved real pages, and live lookups succeeded through a headed Patchright persistent profile after a manual challenge solve.

## Press reviews

- **Pass:** links; in the default set; group `press`.
- **Contributes:** full accessible review text, author, score when present, and review-page provenance from Pitchfork, The Quietus, and The Wire.
- **Limits:** reads review links found by earlier sources; inaccessible pages and pages without a matching record contribute no text. Pitchfork, The Quietus, and The Wire parsers were checked on live pages.

## Resident Advisor

- **Pass:** links; in the default set; group `press`.
- **Contributes:** full available review text, author, and artist and label biographies from GraphQL for linked RA reviews.
- **Limits:** finds reviews by GraphQL search or an earlier review link. [RA discontinued DJ charts](https://ra.co/news/74703), so no chart relations are extracted.

## Escalation ladder

Bandcamp, Beatport, Hard Wax, Soundohm, and Juno pages, the song.link page, and Discogs review pages use browser-like headers, HTTP/2, and cookies. When the response is a challenge page (Cloudflare, Akamai, DataDome, PerimeterX, Fastly, Sucuri, AWS WAF, or a captcha on 403/429/503), the client switches to a stronger transport and keeps using it for that source:

| Step | Requires |
|------|----------|
| httpx | base install |
| curl_cffi with Chrome TLS impersonation | `deadwax[stealth]` |
| Patchright Chromium | `deadwax[browser]` or `deadwax[patchright]`, then `patchright install chromium` |
| Nodriver Chrome | `deadwax[nodriver]` and a local Chrome installation |

Each HTML source has an ordered `html_transports` list. The default is `httpx,impersonate,browser,nodriver`, except Beatport (`nodriver,browser,impersonate,httpx`), Juno (`impersonate,browser,nodriver,httpx`), Bleep and Forced Exposure (`browser,httpx,impersonate,nodriver`), Phonica, Boomkat, Rate Your Music, WhoSampled and 1001Tracklists (`browser`), and Norman Records (`nodriver`); each default lives in the source's settings class in `deadwax.sources.config`. `browser` means Patchright. Set a source's list in Python with `LookupConfig.model_validate({"sources": {"beatport": {"html_transports": ["nodriver", "browser"]}}})`, in TOML with `[sources.beatport] html_transports = ["nodriver", "browser"]`, or in the command environment with `DEADWAX_SOURCES__BEATPORT__HTML_TRANSPORTS='["nodriver","browser"]'`. `http.escalation` is a JSON or TOML list of optional transports allowed globally; its default allows all three. A missing or unlaunchable transport is skipped. API requests use httpx only, including Bandcamp's JSON endpoints and the Hard Wax search feed. Browser mode defaults to headless except for Boomkat, Norman Records, WhoSampled and 1001Tracklists. `patchright` is accepted as another name of `browser`; a list that repeats a transport is rejected when the settings load. Set `DEADWAX_SOURCES__<SOURCE>__BROWSER_HEADLESS` to override one source; `--headless` and `--headed` override all selected sources for one lookup.

A refused page is remembered in the cache for `cache.blocked_ttl` (default one day) and reported as `blocked … (cached)` without a request. After installing an escalation step, run once with `--no-cache`.

## Proxies

By default HTTP transports use proxy variables from the environment; browsers use their own proxy configuration. `.env` does not set proxy variables for other processes.

`DEADWAX_HTTP__PROXY` sets the proxy of every source, and `DEADWAX_SOURCES__<SOURCE>__PROXY` overrides it for one source. The value is `direct` or an `http://` or `https://` proxy URL with a port. Nodriver cannot use a proxy that requires a user name and password; it reports a configuration error in that case. Bot protection can refuse a proxy's exit address; `DEADWAX_SOURCES__DEEZER__PROXY=direct` bypasses it for Deezer. `DEADWAX_HTTP__NODRIVER_BROWSER_PATH` selects a Chrome executable; `DEADWAX_HTTP__NODRIVER_SANDBOX=false` disables Chrome's sandbox only when explicitly chosen. On this Mac, system Chrome 157 fails external navigation with `ERR_INVALID_HANDLE`; Chrome for Testing 156 works with Nodriver when both settings are supplied.

A page refused on one route does not count as refused on another: changing a source's proxy ignores its cached `blocked` entries.

For a local browser check, set `DEADWAX_HTTP__BROWSER_HEADLESS=false` and `DEADWAX_HTTP__PATCHRIGHT_CHANNEL=chrome` after installing Chrome. This Patchright mode uses a temporary profile without a custom user agent, language header, or viewport. Nodriver can use the same visible mode and its existing executable path setting. Browser transports return a ready page immediately; they wait up to `DEADWAX_HTTP__BROWSER_CHALLENGE_WAIT` seconds (default 5) only while a challenge or required page marker remains. Browser profiles are removed after the lookup. Use `--no-cache --timeout 60` when comparing browser transports on protected sources.

If Chrome leaves a tab at `about:blank` with `net::ERR_INVALID_HANDLE`, it has failed before loading the site's challenge. On this Mac, system Chrome 157 has that failure; Patchright with its bundled Chrome for Testing 156 (`patchright_channel=chromium`) loaded Bleep in both headed and headless modes. Use a separate profile directory when switching Chrome versions.

Within one lookup, all sources share one browser per transport, launch settings, and proxy, and open their pages as tabs. The browser starts headless. When a source needs a window, either because it is configured headed or because of a fallback, deadwax waits for the open headless pages to finish and reopens the browser headed. That headed browser then serves every source until the lookup ends, so each lookup launches a browser at most twice.

When a headless Patchright or Nodriver page shows a challenge a visitor can complete, the source retries it in the headed browser and stays headed for the rest of the lookup. A refusal of the address, such as an Akamai block, is reported without a headed retry; for Deezer it depends on the network route (`DEADWAX_SOURCES__DEEZER__PROXY`). In a headed browser, a page that still shows a challenge a visitor can complete (a Cloudflare challenge or Turnstile, a captcha, or an AWS WAF, Fastly, or Sucuri challenge) after `browser_challenge_wait` is brought to the front; a refusal such as an Akamai or Cloudflare block page is reported at once. For a solvable challenge, the command prints `solve the challenge in the browser window: <url>` to stderr. The page then waits up to `DEADWAX_HTTP__HEADED_CHALLENGE_WAIT` seconds (default 60) for the challenge to be completed by hand. Challenged pages take the front one at a time; the others wait their turn. A page counts as ready only once its document has finished loading, so a page that reloads after a challenge is not read half-loaded. This applies both to sources configured headed and to the fallback. Every request served by a headed browser, browser launches, and any wait for the shared browser do not count toward the adapter timeout; headless requests do. A headless source whose request was served by the already headed browser counts as headed for the rest of the lookup and is not retried as a fallback. Set `DEADWAX_HTTP__HEADED_FALLBACK=false` to report the source as blocked instead. Without a persistent profile, the fallback helps only the current lookup.

To keep a browser session between runs, set `DEADWAX_HTTP__PATCHRIGHT_PROFILE_DIR` or `DEADWAX_HTTP__NODRIVER_PROFILE_DIR` to a dedicated directory. Set only the transport you intend to use for that source, for example `DEADWAX_SOURCES__BEATPORT__HTML_TRANSPORTS='["browser"]'`. Run the first lookup with `--no-cache`: a challenged source opens the headed fallback, and the cookies obtained there go into the profile. Later headless runs reuse that transport's cookies and browser storage. A source with its own route, such as `DEADWAX_SOURCES__DEEZER__PROXY=direct`, uses a sibling profile (`<dir>-direct`, or `<dir>-<host>-<port>` for a proxy), because Chrome cannot open one profile twice and challenge cookies are tied to the network address. Headless Chrome reports `HeadlessChrome` in its User-Agent, so a site that ties its clearance cookie to the User-Agent may ask again in headless runs. Do not point either setting at your regular Chrome profile, share one directory between transports, open the same directory in two processes, or commit it. When no profile path is configured, the temporary-profile behavior above remains. A profile can contain login credentials, and a previously solved challenge may still recur.

All sources share per-host rate limits with jitter, bounded retries with backoff that honours `Retry-After`, a response size cap, and the response cache (`--no-cache` bypasses it).

The Patchright profile path is global: any current or future HTML source that selects the `browser` transport uses the same profile. With a persistent profile, deadwax serializes browser requests within a lookup and closes each browser after its request so concurrent sources do not open the same Chrome profile together. API-only sources do not use a browser profile. A new site's cookies appear in the profile only after that site has been visited. To allow Patchright for every HTML source without selecting a source list, set `DEADWAX_HTTP__ESCALATION='["browser"]'`; each source still keeps its own transport order after this global filter.

For one lookup, `--headless` or `--headed` overrides shared and per-source browser modes, and `--html-transport browser,nodriver` sets the exact HTML transport order for every selected HTML source. The listed optional transports are allowed for that run even when `http.escalation` in `.env` is narrower; `httpx` runs only if listed. Omit the flags to use saved settings. For example: `uv run deadwax lookup "Burial - Untrue" --album --sources bleep --no-cache --timeout 180 --headless --html-transport browser,nodriver`. API requests always use httpx.
