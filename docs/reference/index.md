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
| `deadwax.sources.services` | Name the streaming and store service of a URL and what it opens |
| `deadwax.sources.adapters.musicbrainz.adapter` | Find recordings and release groups in MusicBrainz |
| `deadwax.sources.adapters.musicbrainz.parse` | Turn MusicBrainz responses into identity and facts |
| `deadwax.sources.adapters.musicbrainz.models` | Model MusicBrainz web service responses |
| `deadwax.sources.adapters.itunes.adapter` | Find Apple Music links and previews with the iTunes Search API |
| `deadwax.sources.adapters.itunes.parse` | Turn iTunes Search responses into identity and facts |
| `deadwax.sources.adapters.itunes.models` | Model iTunes Search responses |
| `deadwax.sources.adapters.deezer.adapter` | Find Deezer links, ISRCs and barcodes with the Deezer API |
| `deadwax.sources.adapters.deezer.parse` | Turn Deezer responses into identity and facts |
| `deadwax.sources.adapters.deezer.models` | Model Deezer responses |
| `deadwax.sources.adapters.odesli.adapter` | Read links on all platforms from the song.link page of a streaming link |
| `deadwax.sources.adapters.odesli.parse` | Turn song.link responses into identity and facts |
| `deadwax.sources.adapters.odesli.models` | Model song.link responses |
| `deadwax.sources.adapters.discogs.adapter` | Read masters, releases, versions, artists, labels, and reviews from Discogs |
| `deadwax.sources.adapters.discogs.parse` | Turn Discogs responses into identity and facts |
| `deadwax.sources.adapters.discogs.models` | Model Discogs API responses |
| `deadwax.sources.adapters.bandcamp.adapter` | Find and read Bandcamp album and track pages |
| `deadwax.sources.adapters.bandcamp.parse` | Read Bandcamp page data, JSON-LD, search results, and label pages |
| `deadwax.sources.adapters.bandcamp.models` | Model Bandcamp page data and API responses |
| `deadwax.sources.adapters.lastfm.adapter` | Read tracks, albums, tags, and similar items from Last.fm (API key) |
| `deadwax.sources.adapters.lastfm.parse` | Turn Last.fm responses into tags, texts, and relations |
| `deadwax.sources.adapters.lastfm.models` | Model Last.fm API responses |
| `deadwax.sources.adapters.wikipedia.adapter` | Read the Wikidata item and its Wikipedia articles |
| `deadwax.sources.adapters.wikipedia.parse` | Turn Wikidata statements, article sections, and ratings templates into facts |
| `deadwax.sources.adapters.wikipedia.models` | Model Wikidata and MediaWiki API responses |
| `deadwax.sources.adapters.listenbrainz.adapter` | Read listen counts, similar recordings and artists, and CritiqueBrainz reviews by MBID |
| `deadwax.sources.adapters.listenbrainz.parse` | Turn ListenBrainz and CritiqueBrainz responses into metrics, relations, and texts |
| `deadwax.sources.adapters.listenbrainz.models` | Model ListenBrainz and CritiqueBrainz API responses |
| `deadwax.sources.adapters.secondhandsongs.adapter` | Read originals, covers, adaptations, and writers of a song from SecondHandSongs |
| `deadwax.sources.adapters.secondhandsongs.parse` | Turn SecondHandSongs responses into identity, credits, and relations |
| `deadwax.sources.adapters.secondhandsongs.models` | Model SecondHandSongs API responses |
| `deadwax.sources.adapters.kexp.adapter` | Read plays of a record on KEXP with programs, hosts, and comments |
| `deadwax.sources.adapters.kexp.parse` | Turn KEXP plays into broadcast relations and host texts |
| `deadwax.sources.adapters.kexp.models` | Model KEXP API responses |
| `deadwax.sources.adapters.nts.adapter` | Read NTS episodes and their tracklists |
| `deadwax.sources.adapters.nts.parse` | Turn NTS responses into identity and facts |
| `deadwax.sources.adapters.wfmu.adapter` | Read WFMU playlists and DJ comments |
| `deadwax.sources.adapters.wfmu.parse` | Turn WFMU responses into identity and facts |
| `deadwax.sources.adapters.spotify.adapter` | Read tracks and albums from the Spotify Web API (client credentials) |
| `deadwax.sources.adapters.spotify.parse` | Turn Spotify responses into identity, metrics, and links |
| `deadwax.sources.adapters.spotify.models` | Model Spotify Web API responses |
| `deadwax.sources.adapters.youtube.adapter` | Find links to uploads of a record on YouTube (API key) |
| `deadwax.sources.adapters.youtube.parse` | Turn YouTube Data API responses into identity and facts |
| `deadwax.sources.adapters.youtube.models` | Model YouTube Data API responses |
| `deadwax.sources.adapters.genius.adapter` | Read Genius song descriptions, annotations, credits, relations, and lyrics |
| `deadwax.sources.adapters.genius.parse` | Turn Genius responses into identity and facts |
| `deadwax.sources.adapters.allmusic.adapter` | Read AllMusic reviews, tags, credits, and similar albums |
| `deadwax.sources.adapters.allmusic.parse` | Turn AllMusic responses into identity and facts |
| `deadwax.sources.adapters.albumoftheyear.adapter` | Read Album of the Year scores, genres, and review links |
| `deadwax.sources.adapters.albumoftheyear.parse` | Turn Album of the Year responses into identity and facts |
| `deadwax.sources.adapters.rateyourmusic.adapter` | Read Rate Your Music genres, ratings, charts, and reviews |
| `deadwax.sources.adapters.rateyourmusic.parse` | Turn Rate Your Music responses into identity and facts |
| `deadwax.sources.adapters.whosampled.adapter` | Read recording samples, covers, and remixes |
| `deadwax.sources.adapters.whosampled.parse` | Turn WhoSampled responses into identity and facts |
| `deadwax.sources.adapters.tracklists.adapter` | Read DJ sets containing a track |
| `deadwax.sources.adapters.tracklists.parse` | Turn 1001Tracklists responses into identity and facts |
| `deadwax.sources.adapters.pressreviews.adapter` | Read linked reviews from Pitchfork, The Quietus, and The Wire |
| `deadwax.sources.adapters.pressreviews.parse` | Turn press review responses into identity and facts |
| `deadwax.sources.adapters.ra.adapter` | Read linked Resident Advisor reviews and biographies |
| `deadwax.sources.adapters.ra.parse` | Turn Resident Advisor responses into identity and facts |
| `deadwax.sources.adapters.soundcloud.adapter` | Read uploads and their reposters from SoundCloud (client ID) |
| `deadwax.sources.adapters.soundcloud.parse` | Turn SoundCloud uploads into identity, tags, texts, metrics, relations, and links |
| `deadwax.sources.adapters.soundcloud.models` | Model SoundCloud API responses |
| `deadwax.sources.adapters.beatport.adapter` | Search Beatport and read track and release pages |
| `deadwax.sources.adapters.beatport.parse` | Turn Beatport page state into identity with tempo and key, tags, credits, and links |
| `deadwax.sources.adapters.beatport.models` | Model the tracks and releases of Beatport's page state |
| `deadwax.sources.adapters.hardwax.adapter` | Search Hard Wax's feed and read its product pages |
| `deadwax.sources.adapters.hardwax.parse` | Turn Hard Wax feeds and pages into identity, shop texts, genres, and links |
| `deadwax.sources.adapters.hardwax.models` | Model Hard Wax's JSON search feed |
| `deadwax.sources.adapters.soundohm.adapter` | Search Soundohm and read its product pages |
| `deadwax.sources.adapters.soundohm.parse` | Turn Soundohm pages into identity, shop texts, genres, and links |
| `deadwax.sources.adapters.juno.adapter` | Search Juno and read its product pages |
| `deadwax.sources.adapters.juno.parse` | Turn Juno pages into identity, shop texts, tags, relations, and links |
| `deadwax.sources.adapters.bleep.adapter` | Search Bleep and read release pages |
| `deadwax.sources.adapters.bleep.parse` | Extract Bleep descriptions and release details |
| `deadwax.sources.adapters.forcedexposure.adapter` | Search Forced Exposure and read product pages |
| `deadwax.sources.adapters.forcedexposure.parse` | Extract Forced Exposure label copy and release details |
| `deadwax.sources.adapters.phonica.adapter` | Search Phonica and read product pages |
| `deadwax.sources.adapters.phonica.parse` | Extract Phonica release facts and search results |
| `deadwax.sources.adapters.phonica.models` | Model Phonica search responses |
| `deadwax.sources.adapters.boomkat.adapter` | Search Boomkat and read release pages |
| `deadwax.sources.adapters.boomkat.parse` | Extract Boomkat descriptions and genres |
| `deadwax.sources.adapters.norman.adapter` | Read Norman Records product URLs |
| `deadwax.sources.adapters.norman.parse` | Extract Norman Records release identity and genres |
| `deadwax.logs.settings` | Define logging settings |
| `deadwax.logs.setup` | Configure console and file logging for applications |
| `deadwax.logs.runs` | Journal each lookup run to its own event file and an index of runs |
| `deadwax.cli.settings` | Load command settings from the environment |
| `deadwax.cli.app` | Define the `deadwax` command |
| `deadwax.main` | Run the `deadwax` console script |
