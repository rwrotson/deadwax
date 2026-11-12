import pytest

from deadwax.core import (
    EntityKind,
    IdKind,
    NotFoundError,
    Rating,
    RecordKey,
    RelationKind,
    Scope,
    SourceError,
    TagKind,
    TextKind,
)
from deadwax.sources.wikipedia import models
from deadwax.sources.wikipedia import parse as p

URL = "https://en.wikipedia.org/wiki/Song"


def snak(prop: str, value: object, kind: str = "wikibase-entityid") -> dict[str, object]:
    return {"property": prop, "snaktype": "value", "datavalue": {"type": kind, "value": value}}


def ref(prop: str, qid: str, **extra: object) -> dict[str, object]:
    return {"mainsnak": snak(prop, {"id": qid}), **extra}


def string(prop: str, value: str) -> dict[str, object]:
    return {"mainsnak": snak(prop, value, "string")}


def time(value: str, precision: int) -> dict[str, object]:
    return {"mainsnak": snak("P577", {"time": value, "precision": precision}, "time")}


def labels(**by_language: str) -> dict[str, dict[str, str]]:
    return {lang: {"language": lang, "value": value} for lang, value in by_language.items()}


def item(qid: str, claims: dict[str, list[object]] | None = None, **fields: object) -> models.Item:
    return models.Item.model_validate({"id": qid, "claims": claims or {}, **fields})


SONG = item(
    "Q1",
    {
        "P31": [ref("P31", "Q7366")],
        "P175": [ref("P175", "Q10")],
        "P136": [ref("P136", "Q20"), ref("P136", "Q21", rank="deprecated")],
        "P162": [ref("P162", "Q30")],
        "P676": [ref("P676", "Q31")],
        "P264": [ref("P264", "Q40")],
        "P361": [ref("P361", "Q50"), ref("P361", "Q51")],
        "P407": [ref("P407", "Q7737")],
        "P577": [time("+1988-00-00T00:00:00Z", 9), time("+1990-05-01T00:00:00Z", 11)],
        "P435": [string("P435", "work-id")],
        "P436": [string("P436", "single-group")],
        "P444": [
            {"mainsnak": snak("P444", "4/5", "string"),
             "qualifiers": {"P447": [snak("P447", {"id": "Q60"})]}},
            {"mainsnak": snak("P444", "A", "string"),
             "qualifiers": {"P447": [snak("P447", {"id": "Q61"})]}},
            {"mainsnak": snak("P444", "9/10", "string")},
            {"mainsnak": {"property": "P444", "snaktype": "novalue"},
             "qualifiers": {"P447": [snak("P447", {"id": "Q60"})]}},
        ],
    },
    labels=labels(ru="Песня", en="Pesnya"),
)  # fmt: skip
REFERENCED = {
    "Q10": item("Q10", labels=labels(ru="Группа", mul="Gruppa"),
                aliases={"en": [{"language": "en", "value": "The Band"}]}),
    "Q20": item("Q20", labels=labels(en="post-punk", ru="пост-панк")),
    "Q30": item("Q30", labels=labels(en="Producer")),
    "Q31": item("Q31", labels=labels(ru="Поэт", en="Poet")),
    "Q40": item("Q40", labels=labels(en="Label")),
    "Q50": item("Q50", labels=labels(en="Album")),
    "Q51": item("Q51", labels=labels(en="List of albums")),
    "Q60": item("Q60", labels=labels(en="AllMusic")),
    "Q61": item("Q61", labels=labels(en="Robert Christgau")),
}  # fmt: skip
LABELS = p.Labels(REFERENCED, "ru")


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (b'{"error": {"code": "missingtitle", "info": "gone"}}', NotFoundError),
        (b'{"error": {"code": "no-such-entity"}}', NotFoundError),
        (b'{"error": {"code": "badvalue", "info": "bad"}}', SourceError),
    ],
)
def test_errors_in_the_body(body: bytes, error: type[SourceError]) -> None:
    with pytest.raises(error):
        p.check(body, URL)
    p.check(b"{}", URL)


def test_referenced_items() -> None:
    assert p.referenced(SONG) == [
        "Q10", "Q20", "Q40", "Q50", "Q51", "Q7737", "Q30", "Q31", "Q60", "Q61"
    ]  # fmt: skip


def test_candidate_uses_original_language_names() -> None:
    found = p.candidate(SONG, EntityKind.TRACK, LABELS, "ru")

    assert (found.artist, found.title, found.date) == ("Группа", "Песня", "1988")
    assert found.ids == {IdKind.WIKIDATA: "Q1", IdKind.MUSICBRAINZ_WORK: "work-id"}
    assert [label.name for label in found.labels] == ["Label"]
    assert found.url == "https://www.wikidata.org/wiki/Q1"


def test_candidate_takes_the_alias_matching_the_expected_artist() -> None:
    found = p.candidate(SONG, EntityKind.TRACK, LABELS, None, artist="The Band")

    assert (found.artist, found.title) == ("The Band", "Pesnya")
    assert p.candidate(SONG, EntityKind.TRACK, LABELS, None, "Nobody").artist == "Группа"


def test_album_candidate_keeps_release_ids() -> None:
    album = item("Q2", {"P175": [ref("P175", "Q10")], "P436": [string("P436", "rg")],
                        "P1954": [string("P1954", "7")],
                        "P577": [time("+2016-06-00T00:00:00Z", 11)]},
                 labels=labels(en="Record"))  # fmt: skip

    found = p.candidate(album, EntityKind.ALBUM, LABELS, None)

    assert found.ids == {
        IdKind.WIKIDATA: "Q2",
        IdKind.MUSICBRAINZ_RELEASE_GROUP: "rg",
        IdKind.DISCOGS_MASTER: "7",
    }
    assert found.date == "2016-06"


@pytest.mark.parametrize(
    ("dates", "expected"),
    [
        ([time("+1997-05-26T00:00:00Z", 11)], "1997-05-26"),
        ([time("+1997-05-26T00:00:00Z", 10)], "1997-05"),
        ([time("+1997-05-26T00:00:00Z", 9)], "1997"),
        ([time("+1997-00-00T00:00:00Z", 11)], "1997"),
        ([time("garbage", 11), {"mainsnak": {"property": "P577", "snaktype": "somevalue"}}], None),
    ],
)
def test_dates(dates: list[object], expected: str | None) -> None:
    record = item("Q3", {"P175": [ref("P175", "Q10")], "P577": dates}, labels=labels(en="X"))

    assert p.candidate(record, EntityKind.TRACK, LABELS, None).date == expected


def test_candidate_needs_a_performer() -> None:
    with pytest.raises(NotFoundError):
        p.candidate(item("Q4", labels=labels(en="X")), EntityKind.TRACK, LABELS, None)


def test_claim_facts() -> None:
    tags = p.claim_tags(SONG, LABELS, Scope.RECORDING)
    people = p.claim_credits(SONG, LABELS, Scope.RECORDING)
    relations = p.claim_relations(SONG, LABELS, Scope.RECORDING, albums={"Q50"})

    assert [(t.name, t.kind) for t in tags] == [("post-punk", TagKind.GENRE)]
    assert [(c.role, c.name) for c in people] == [("producer", "Producer"), ("lyricist", "Поэт")]
    assert [(r.kind, r.target.name, r.scope) for r in relations] == [
        (RelationKind.LABEL, "Label", Scope.LABEL),
        (RelationKind.APPEARS_ON, "Album", Scope.RECORDING),
    ]
    assert relations[1].target.ids == {IdKind.WIKIDATA: "Q50"}


def test_claim_ratings_skip_rated_publications() -> None:
    ratings = p.claim_ratings(SONG, LABELS, Scope.RECORDING, known={"allmusic"})

    assert [(t.publication, t.rating) for t in ratings] == [("Robert Christgau", Rating(text="A"))]
    assert ratings[0].kind is TextKind.REVIEW
    assert ratings[0].body == ""


def test_labels_of_unknown_items() -> None:
    assert LABELS.name("Q999") is None
    assert LABELS.term("Q999") is None
    assert LABELS.performer("Q999", "x") is None


@pytest.mark.parametrize(
    ("value", "rating"),
    [
        ("{{Rating|3.5|4}}<ref name=x/>", Rating(value=3.5, scale=4)),
        ("10/10<ref>{{cite web|title=a}}</ref>", Rating(value=10, scale=10)),
        ("''B+''<!-- note -->", Rating(text="B+")),
        ("(положительная){{sfn|Житинский|p=288|2015}}", Rating(text="(положительная)")),
        ("<ref name=x/>", None),
    ],
)
def test_scores(value: str, rating: Rating | None) -> None:
    assert p.score(value) == rating


def test_clean() -> None:
    assert p.clean("''[[Pitchfork (website)|Pitchfork]]''") == "Pitchfork"
    assert p.clean("[[NME]] {{a|{{b}}}} [https://x.example Site] <small>x</small>") == "NME Site x"


WIKITEXT = """
Intro {{Infobox song|name=X}}
{{Album ratings
| title = Contemporaneous reviews
| MC = 85/100<ref>{{cite web|url=https://x}}</ref>
| rev1 = ''[[Chicago Tribune]]''
| rev1score = {{Rating|3.5|4}}<ref name="t"/>
| rev2 = [[Spin (magazine)|Spin]]
| rev2Score = 8/10
| rev10 = [[Q (magazine)|Q]]
| rev10score = {{Rating|5|5}}
| rev3 = Nobody
| rev3score =
| rev4 =
| rev4score = 5/5
}}
{{music_ratings|rev1=AllMusic|rev1score={{Rating|5|5}}}}
{{Рейтинги альбома
|title = Рейтинги
| rev1 = [[Житинский, Александр Николаевич|Александр Житинский]]
| rev1Score = (положительная)
}}
{{Album ratings
"""


def test_ratings_templates() -> None:
    texts = p.ratings(WIKITEXT, "en", Scope.RELEASE_GROUP, URL)

    assert [(t.publication, t.rating, t.title) for t in texts] == [
        ("Metacritic", Rating(value=85, scale=100), "Contemporaneous reviews"),
        ("Chicago Tribune", Rating(value=3.5, scale=4), "Contemporaneous reviews"),
        ("Spin", Rating(value=8, scale=10), "Contemporaneous reviews"),
        ("Q", Rating(value=5, scale=5), "Contemporaneous reviews"),
        ("AllMusic", Rating(value=5, scale=5), None),
        ("Александр Житинский", Rating(text="(положительная)"), "Рейтинги"),
    ]
    assert {t.language for t in texts} == {"en"}
    assert texts[0].sources[0].url == URL


HTML = """
<div class="mw-content-ltr mw-parser-output">
<div role="note" class="hatnote">For other uses, see X.</div>
<table class="infobox"><tr><td>Infobox</td></tr></table>
<style>.x{}</style>
<p class="mw-empty-elt"></p>
<p>Lead <b>text</b>.<sup class="reference">[1]</sup></p>
<p>Second lead paragraph.</p>
<div class="mw-heading mw-heading2"><h2 id="Background">Background</h2></div>
<figure><figcaption>Caption</figcaption></figure>
<p>Background text.</p>
<div class="mw-heading mw-heading3"><h3 id="Sub">Sub</h3></div>
<p>Sub text.</p>
<blockquote><p>A quote.</p></blockquote>
<div class="quote"><blockquote><p>Wrapped <a href="/wiki/Q">quote</a>, once.</p></blockquote></div>
<div class="mw-heading mw-heading2"><h2 id="Music_video">Music video</h2></div>
<p>Video text.</p>
<div class="mw-heading mw-heading2"><h2 id="Reception">Reception</h2></div>
<div class="reflist"><p>Only references.</p></div>
<h2 id="Legacy">Legacy</h2>
<p>Old markup.</p>
</div>
"""


def test_sections() -> None:
    texts = p.sections(HTML, "Song", "en", Scope.RECORDING, URL)

    assert [(t.title, t.body) for t in texts] == [
        ("Song", "Lead text.\n\nSecond lead paragraph."),
        ("Background", "Background text.\n\nSub text.\n\nA quote.\n\nWrapped quote, once."),
        ("Legacy", "Old markup."),
    ]
    assert texts[1].sources[0].url == f"{URL}#Background"
    assert (texts[0].kind, texts[0].language, texts[0].publication) == (
        TextKind.WIKI,
        "en",
        "Wikipedia",
    )


def test_sections_of_other_languages() -> None:
    russian = HTML.replace("Background", "История песни").replace("Legacy", "Участники")
    japanese = HTML.replace("Background", "背景")

    assert [t.title for t in p.sections(russian, "Песня", "ru", Scope.RECORDING, URL)] == [
        "Песня",
        "История песни",
    ]
    assert [t.title for t in p.sections(japanese, "曲", "ja", Scope.RECORDING, URL)] == [
        "曲",
        "背景",
    ]
    assert [t.title for t in p.sections(HTML, "Lied", "nl", Scope.RECORDING, URL)] == ["Lied"]


def test_sections_of_an_empty_page() -> None:
    assert p.sections("", "X", "en", Scope.RECORDING, URL) == []


def test_pick_and_helpers() -> None:
    song = item("Q5", {"P31": [ref("P31", "Q134556")], "P175": [ref("P175", "Q10")]},
                labels=labels(en="Pesnya"))  # fmt: skip
    album = item("Q6", {"P31": [ref("P31", "Q482994")], "P175": [ref("P175", "Q10")]},
                 labels=labels(en="Pesnya"))  # fmt: skip
    other = item("Q7", {"P31": [ref("P31", "Q7366")], "P175": [ref("P175", "Q11")]},
                 labels=labels(en="Pesnya"))  # fmt: skip
    key = RecordKey(artist="The Band", title="Pesnya", kind=EntityKind.TRACK)

    assert p.pick(key, [album, other, song], REFERENCED, "en") == "Q5"
    assert p.pick(key, [album, other], REFERENCED, "en") is None
    assert p.pick(RecordKey(artist="Gruppa", title="Pesnya"), [album], REFERENCED, "en") == "Q6"
    assert p.search_language("Кино - Группа крови") == "ru"
    assert p.search_language("細野晴臣") == "ja"
    assert p.search_language("Radiohead") == "en"
    assert p.type_filter(EntityKind.TRACK).startswith("haswbstatement:P31=")
    code = models.Claims.model_validate({"claims": {"P424": [string("P424", "ru")]}})
    assert p.wiki_code(code) == "ru"
    assert p.wiki_code(models.Claims()) is None
    assert p.article_url("ru", "Группа крови (песня)").startswith(
        "https://ru.wikipedia.org/wiki/%D0%93"
    )
