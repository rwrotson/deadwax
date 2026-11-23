# Core

- Keep the core independent of the other layers and limit third-party imports to Pydantic. Follow the internal layer order and expose names needed by outer layers through `deadwax.core`. See [the core import contract](../../../architecture.md#r5-inside-core-contract) and [API surfaces](../../../architecture.md#r2-api-surfaces).
- Keep matching ahead of merging. Compare tracks and albums by `RecordKey` and artists and labels by `NameKey`. Reject unrelated candidates and keep facts from other versions out of the main record. Preserve provenance and identity discrepancies in the dossier. See [the lookup flow](../../../architecture.md#lookup-flow).
- Define new trace event names in `TraceEvent`, emit them through `trace()`, and update [the event table](../../../runs.md#events).
