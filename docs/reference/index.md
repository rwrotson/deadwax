# API Reference

The pages below are generated from public objects in `src/deadwax/`. Names exported from `deadwax` are the supported public API; `deadwax.logs` is supported for applications that install the `logs` extra.

| Module | Purpose |
|--------|---------|
| `deadwax.core.errors` | Define the library error hierarchy |
| `deadwax.core.query` | Parse 'Artist - Title' text and record page URLs into a query |
| `deadwax.core.models` | Define the dossier, its facts, provenance, and adapter results |
| `deadwax.core.normalize` | Build comparison keys for names, titles, and codes |
| `deadwax.core.versions` | Detect remix, live, demo, remaster, and other versions in titles |
| `deadwax.core.matching` | Compare a candidate with the queried record and its version |
| `deadwax.core.merge` | Combine adapter results into a dossier with discrepancies |
| `deadwax.core.markdown` | Render a dossier as Markdown |
| `deadwax.core.adapter` | Define the adapter protocol, source status, and lookup context |
| `deadwax.core.orchestrator` | Run adapters in two passes and merge their results |
| `deadwax.sources.config` | Define HTTP, cache, and per-source settings |
| `deadwax.sources.lookup` | Build the adapters and look a query up |
| `deadwax.sources.musicbrainz.adapter` | Find recordings and release groups in MusicBrainz |
| `deadwax.sources.musicbrainz.parse` | Turn MusicBrainz responses into identity and facts |
| `deadwax.sources.musicbrainz.models` | Model MusicBrainz web service responses |
| `deadwax.sources.itunes` | Find Apple Music links and previews with the iTunes Search API |
| `deadwax.sources.deezer` | Find Deezer links, ISRCs and barcodes with the Deezer API |
| `deadwax.sources.odesli` | Expand a streaming link to all platforms with Odesli (API key) |
| `deadwax.logs.settings` | Define logging settings |
| `deadwax.logs.setup` | Configure console and file logging for applications |
| `deadwax.cli.settings` | Load command settings from the environment |
| `deadwax.cli.app` | Define the `deadwax` command |
| `deadwax.main` | Run the `deadwax` console script |
