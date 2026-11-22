from deadwax import EntityKind
from deadwax.sources import LookupConfig, PerSourceSettings, SourceSettings, build_adapters
from deadwax.sources._http import HttpResources
from deadwax.sources.registry import ADAPTERS


def test_every_adapter_has_a_settings_section_and_no_section_is_stale() -> None:
    assert [adapter.name for adapter in ADAPTERS] != []
    assert {adapter.name for adapter in ADAPTERS} == set(PerSourceSettings.model_fields)
    assert len({adapter.name for adapter in ADAPTERS}) == len(ADAPTERS)


def test_sections_are_distinct_settings_classes() -> None:
    classes = [field.annotation for field in PerSourceSettings.model_fields.values()]

    assert all(isinstance(cls, type) and issubclass(cls, SourceSettings) for cls in classes)
    assert len(set(classes)) == len(classes)


def test_required_settings_exist_in_their_source_section() -> None:
    config = LookupConfig()

    for adapter in build_adapters(config, HttpResources()):
        for requirement in adapter.requires:
            section, source, name = requirement.setting.split(".")
            assert (section, source) == ("sources", adapter.name)
            assert name in type(config.sources.of(source)).model_fields


def test_adapters_read_their_own_section() -> None:
    config = LookupConfig()

    for adapter in build_adapters(config, HttpResources()):
        assert adapter.settings is getattr(config.sources, adapter.name)


TRACKS_ONLY = {"genius", "nts", "secondhandsongs", "tracklists", "wfmu", "whosampled"}

# Sources that also look up artists or labels.
NAMES = {
    "musicbrainz": frozenset(EntityKind),
    "discogs": frozenset(EntityKind),
    "lastfm": frozenset({EntityKind.TRACK, EntityKind.ALBUM, EntityKind.ARTIST}),
}

# Without a service of their own, they still find the kind: from a streaming URL, a Wikidata item.
UNRESOLVED_WITHOUT_SERVICE = {"odesli", "wikipedia"}


def test_adapters_declare_the_record_kinds_they_look_up() -> None:
    adapters = build_adapters(LookupConfig(), HttpResources())

    kinds = {adapter.name: adapter.lookups.kinds for adapter in adapters}
    unresolved = {adapter.name for adapter in adapters if adapter.lookups.unresolved is not None}

    assert {name for name, found in kinds.items() if found == {EntityKind.TRACK}} == TRACKS_ONLY
    records = {EntityKind.TRACK, EntityKind.ALBUM}
    assert all(
        found == NAMES.get(name, records)
        for name, found in kinds.items()
        if name not in TRACKS_ONLY
    )
    readers = {adapter.name for adapter in adapters if adapter.service is not None}
    assert unresolved == (readers - {"genius", "lastfm"}) | UNRESOLVED_WITHOUT_SERVICE
