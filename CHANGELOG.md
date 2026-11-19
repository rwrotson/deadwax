# Changelog

All notable changes to this project will be documented in this file.

## v0.1.0 (2026-11-20)

### Feat

- expose Bandcamp stream previews and accept ISRC in queries
- **sources**: add LB Radio, Last.fm similar artists for tracks, and MusicBrainz associated artists
- request dossiers by facets through a long-lived Deadwax client
- **sources**: drop Deezer from the default source set
- **albumoftheyear**: find a track through a release that lists it
- **sources**: share browser sessions per lookup and retry blocked headless pages headed
- **output**: show configured access for blocked sources
- **cli**: support all as a source selector
- **cli**: show configured source access methods and browser modes
- **sources**: add 1001Tracklists DJ set relations
- **sources**: add WhoSampled recording relations and sample offsets
- **sources**: add preliminary Rate Your Music adapter
- **sources**: add NTS and WFMU radio adapters
- **sources**: complete press and Resident Advisor reviews
- **sources**: add Resident Advisor reviews and verify press parsing
- **sources**: add linked press review adapter
- **sources**: add profile-based Phonica, Boomkat and Norman adapters
- **cli**: add per-lookup browser and HTML transport flags
- **sources**: share persistent Patchright profile across HTML sources
- **sources**: add optional persistent browser profiles
- **sources**: improve Patchright and Nodriver page readiness
- **sources**: add initial AllMusic and Album of the Year support
- **sources**: add Genius adapter
- **sources**: add Bleep and Forced Exposure and repair Nodriver
- **deezer**: read public record pages instead of the API
- add Patchright and Nodriver browser transports
- **sources**: add Phonica adapter on saved pages
- **sources**: add Juno adapter on saved pages and detect Sucuri challenges
- **sources**: add Hard Wax and Soundohm adapters and merge repeated shop texts
- **sources**: fit Beatport to its real page state, add DJ charts, drop Juno Download
- **sources**: add Beatport and Juno Download adapters with BPM and key
- **sources**: add Spotify, YouTube and SoundCloud adapters
- **cli**: journal every command run and add the runs command
- **logs**: add an opt-in run journal with per-run event files and an index
- **core**: emit structured trace events for matching, passes, merge and HTTP requests
- **sources**: add ListenBrainz, SecondHandSongs and KEXP adapters
- **sources**: add source groups and a concurrency cap for v2 sources
- **sources**: add a proxy setting per source, with "direct" to bypass the environment proxy
- **core**: run Odesli in a links pass after enrichment so it can start from iTunes and Deezer URLs
- **sources**: add Last.fm and Wikipedia adapters and read Odesli from song.link pages
- **sources**: add bandcamp and discogs adapters
- **cli**: add lookup and sources commands
- **sources**: add MusicBrainz, iTunes, Deezer and Odesli adapters with lookup()
- **sources**: add adapter orchestration and resilient HTTP stack
- **core**: add dossier model, query parsing and version-aware matching

### Fix

- **matching**: match alternative titles in brackets, skip headed fallback on refusals, and keep partial WFMU results
- **sources**: read browser pages only once loaded and ask for help only with solvable challenges
- **sources**: keep headed browser work out of adapter timeouts and report refused pages accurately
- **sources**: give each proxy route its own browser profile and bring headed challenges to the front
- **sources**: exclude browser profile queue waits from adapter timeout
- **sources**: disable sources without permitted HTML transports
- **sources**: restore NTS and WFMU radio discovery
- **sources**: parse live NTS and WFMU episode fields
- **sources**: recognize Cloudflare precursor on normal pages
- **sources**: parse Album of the Year reviews from real pages
- **sources**: verify AllMusic parsing on real album pages
- **sources**: load Patchright pages with working Chrome and detect AWS WAF
- **bandcamp**: verify direct release pages when search fails
- **cli**: keep normal output quiet and await Nodriver shutdown
- **sources**: retry Beatport pages missing required state
- **core**: treat explicit versions as the original recording
- **sources**: drop Odesli links that name another record on the seed's own platform
- **sources**: treat a missing browser as an unavailable escalation step and cache blocked pages

### Refactor

- name trace events with an enum, archive closed v2 stages, and rewrite the architecture docs
- **core**: add a Facts base and a deadline module, and render Markdown and access labels in the CLI
- **sources**: move source defaults into per-source settings and share LookupConfig with the CLI
- **sources**: move service hosts and URL rules into a service catalogue
- **sources**: share prose(), read NTS, RA and Genius JSON through models, and describe access on adapters
- **sources**: move adapters into per-source packages and rename residentadvisor to ra
- **sources**: defer Phonica adapter to blocked-sources work
