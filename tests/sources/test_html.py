from deadwax.sources._html import attribute, attribute_json, json_ld, parse_html, text_of


def test_text_and_attributes() -> None:
    document = parse_html(b'<p data-x="1"> a\n  b </p><i data-y=""></i><b> </b>')

    assert text_of(document.css_first("p")) == "a b"
    assert text_of(document.css_first("b")) is None
    assert text_of(None) is None
    assert attribute(document.css_first("p"), "data-x") == "1"
    assert attribute(document.css_first("i"), "data-y") is None
    assert attribute(None, "data-x") is None


def test_attribute_json() -> None:
    document = parse_html(
        '<a data-ok="{&quot;a&quot;: 1}"></a><a data-list="[1]"></a><a data-bad="{oops"></a>',
    )

    assert attribute_json(document, "data-ok") == {"a": 1}
    assert attribute_json(document, "data-list") is None
    assert attribute_json(document, "data-bad") is None
    assert attribute_json(document, "data-missing") is None


def test_json_ld_types_lists_and_graphs() -> None:
    document = parse_html(
        """
        <script type="application/ld+json">{"@type": "MusicAlbum", "name": "A"}</script>
        <script type="application/ld+json">
          [{"@type": ["Product", "MusicRelease"], "name": "B"}]
        </script>
        <script type="application/ld+json">{"@graph": [{"@type": "Person", "name": "C"}]}</script>
        <script type="application/ld+json">{not json</script>
        <script type="application/ld+json">{"name": "untyped"}</script>
        """,
    )

    assert [item["name"] for item in json_ld(document, "MusicAlbum", "MusicRelease")] == ["A", "B"]
    assert [item.get("name") for item in json_ld(document, "Person")] == ["C"]
    assert len(json_ld(document)) == 5
