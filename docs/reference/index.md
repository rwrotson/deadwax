# API Reference

The pages below are generated from public objects in `src/deadwax/`. Names exported from `deadwax` are the supported public API; `deadwax.logs` is supported for applications that install the `logs` extra.

| Module | Purpose |
|--------|---------|
| `deadwax.core.errors` | Define the library error hierarchy |
| `deadwax.core.events` | Emit structured trace events with fields bound by scope |
| `deadwax.core.query` | Parse 'Artist - Title' text and record page URLs into a query |
| `deadwax.core.models` | Define the dossier, its facts, provenance, and adapter results |
| `deadwax.core.normalize` | Build comparison keys for names, titles, and codes |
| `deadwax.core.versions` | Detect remix, live, demo, remaster, and other versions in titles |
| `deadwax.core.matching` | Compare a candidate with the queried record and its version |
| `deadwax.core.merge` | Combine adapter results into a dossier with discrepancies |
| `deadwax.core.markdown` | Render a dossier as Markdown |
| `deadwax.core.adapter` | Define the adapter protocol, source status, and lookup context |
| `deadwax.core.orchestrator` | Run adapters pass by pass and merge their results |
| `deadwax.sources.config` | Define HTTP, cache, and per-source settings |
| `deadwax.sources.lookup` | Build the adapters and look a query up |
| `deadwax.sources.musicbrainz.adapter` | Find recordings and release groups in MusicBrainz |
| `deadwax.sources.musicbrainz.parse` | Turn MusicBrainz responses into identity and facts |
| `deadwax.sources.musicbrainz.models` | Model MusicBrainz web service responses |
| `deadwax.sources.itunes` | Find Apple Music links and previews with the iTunes Search API |
| `deadwax.sources.deezer` | Find Deezer links, ISRCs and barcodes with the Deezer API |
| `deadwax.sources.odesli` | Read links on all platforms from the song.link page of a streaming link |
| `deadwax.sources.discogs.adapter` | Read masters, releases, versions, artists, labels, and reviews from Discogs |
| `deadwax.sources.discogs.parse` | Turn Discogs responses into identity and facts |
| `deadwax.sources.discogs.models` | Model Discogs API responses |
| `deadwax.sources.bandcamp.adapter` | Find and read Bandcamp album and track pages |
| `deadwax.sources.bandcamp.parse` | Read Bandcamp page data, JSON-LD, search results, and label pages |
| `deadwax.sources.bandcamp.models` | Model Bandcamp page data and API responses |
| `deadwax.sources.lastfm.adapter` | Read tracks, albums, tags, and similar items from Last.fm (API key) |
| `deadwax.sources.lastfm.parse` | Turn Last.fm responses into tags, texts, and relations |
| `deadwax.sources.lastfm.models` | Model Last.fm API responses |
| `deadwax.sources.wikipedia.adapter` | Read the Wikidata item and its Wikipedia articles |
| `deadwax.sources.wikipedia.parse` | Turn Wikidata statements, article sections, and ratings templates into facts |
| `deadwax.sources.wikipedia.models` | Model Wikidata and MediaWiki API responses |
| `deadwax.sources.listenbrainz.adapter` | Read listen counts, similar recordings and artists, and CritiqueBrainz reviews by MBID |
| `deadwax.sources.listenbrainz.parse` | Turn ListenBrainz and CritiqueBrainz responses into metrics, relations, and texts |
| `deadwax.sources.listenbrainz.models` | Model ListenBrainz and CritiqueBrainz API responses |
| `deadwax.sources.secondhandsongs.adapter` | Read originals, covers, adaptations, and writers of a song from SecondHandSongs |
| `deadwax.sources.secondhandsongs.parse` | Turn SecondHandSongs responses into identity, credits, and relations |
| `deadwax.sources.secondhandsongs.models` | Model SecondHandSongs API responses |
| `deadwax.sources.kexp.adapter` | Read plays of a record on KEXP with programs, hosts, and comments |
| `deadwax.sources.kexp.parse` | Turn KEXP plays into broadcast relations and host texts |
| `deadwax.sources.kexp.models` | Model KEXP API responses |
| `deadwax.sources.nts` | Read NTS episodes and their tracklists |
| `deadwax.sources.wfmu` | Read WFMU playlists and DJ comments |
| `deadwax.sources.spotify.adapter` | Read tracks and albums from the Spotify Web API (client credentials) |
| `deadwax.sources.spotify.parse` | Turn Spotify responses into identity, metrics, and links |
| `deadwax.sources.spotify.models` | Model Spotify Web API responses |
| `deadwax.sources.youtube` | Find links to uploads of a record on YouTube (API key) |
| `deadwax.sources.genius` | Read Genius song descriptions, annotations, credits, relations, and lyrics |
| `deadwax.sources.allmusic` | Read AllMusic reviews, tags, credits, and similar albums |
| `deadwax.sources.albumoftheyear` | Read Album of the Year scores, genres, and review links |
| `deadwax.sources.press` | Read linked reviews from Pitchfork, The Quietus, and The Wire |
| `deadwax.sources.residentadvisor` | Read linked Resident Advisor reviews and biographies |
| `deadwax.sources.soundcloud.adapter` | Read uploads and their reposters from SoundCloud (client ID) |
| `deadwax.sources.soundcloud.parse` | Turn SoundCloud uploads into identity, tags, texts, metrics, relations, and links |
| `deadwax.sources.soundcloud.models` | Model SoundCloud API responses |
| `deadwax.sources.beatport.adapter` | Search Beatport and read track and release pages |
| `deadwax.sources.beatport.parse` | Turn Beatport page state into identity with tempo and key, tags, credits, and links |
| `deadwax.sources.beatport.models` | Model the tracks and releases of Beatport's page state |
| `deadwax.sources.hardwax.adapter` | Search Hard Wax's feed and read its product pages |
| `deadwax.sources.hardwax.parse` | Turn Hard Wax feeds and pages into identity, shop texts, genres, and links |
| `deadwax.sources.hardwax.models` | Model Hard Wax's JSON search feed |
| `deadwax.sources.soundohm.adapter` | Search Soundohm and read its product pages |
| `deadwax.sources.soundohm.parse` | Turn Soundohm pages into identity, shop texts, genres, and links |
| `deadwax.sources.juno.adapter` | Search Juno and read its product pages |
| `deadwax.sources.juno.parse` | Turn Juno pages into identity, shop texts, tags, relations, and links |
| `deadwax.sources.bleep.adapter` | Search Bleep and read release pages |
| `deadwax.sources.bleep.parse` | Extract Bleep descriptions and release details |
| `deadwax.sources.forcedexposure.adapter` | Search Forced Exposure and read product pages |
| `deadwax.sources.forcedexposure.parse` | Extract Forced Exposure label copy and release details |
| `deadwax.sources.phonica.adapter` | Search Phonica and read product pages |
| `deadwax.sources.phonica.parse` | Extract Phonica release facts and search results |
| `deadwax.sources.phonica.models` | Model Phonica search responses |
| `deadwax.sources.boomkat.adapter` | Search Boomkat and read release pages |
| `deadwax.sources.boomkat.parse` | Extract Boomkat descriptions and genres |
| `deadwax.sources.norman.adapter` | Read Norman Records product URLs |
| `deadwax.sources.norman.parse` | Extract Norman Records release identity and genres |
| `deadwax.logs.settings` | Define logging settings |
| `deadwax.logs.setup` | Configure console and file logging for applications |
| `deadwax.logs.runs` | Journal each lookup run to its own event file and an index of runs |
| `deadwax.cli.settings` | Load command settings from the environment |
| `deadwax.cli.app` | Define the `deadwax` command |
| `deadwax.main` | Run the `deadwax` console script |
