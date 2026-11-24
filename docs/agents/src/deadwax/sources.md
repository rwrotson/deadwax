# Sources

- Each adapter is a package `adapters/<name>/` with `adapter` (class and requests), `parse` (pure functions from responses to facts), and optional `models` (Pydantic models of JSON responses), layered in that order.
- Adapters never import each other. Data found by one adapter reaches another only through `LookupContext`. Shared code lives in `_search`, `_adapter`, `services`, `_html`, `_http`, or `config`.
- Import the core only from the `deadwax.core` package, never its submodules. httpx and selectolax stay in `sources`; curl_cffi, Patchright, and Nodriver only in their `_http` modules, imported lazily (R6, R7 in `docs/architecture.md`).
- A failing adapter records its failure in the dossier's `errors`; it never raises out of a lookup.
- Before changing a v1 adapter, read its rows in the [v1 decision log](../../../../plans/v1.md). For a v2 adapter, read its stages and evidence in the [v2 archive](../../../../plans/v2.md) and the [closing handoff](../../../../plans/v2-handoff.md).
- Adding a source: follow the checklist in `docs/architecture.md` "Adding a source".
- A setting that holds a credential (token, API key, client ID or secret) gets step-by-step instructions for obtaining it in README's "Credentials" section, in the same change.
