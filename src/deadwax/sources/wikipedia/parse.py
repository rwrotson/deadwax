import re
from collections.abc import Collection, Iterator, Mapping, Sequence
from urllib.parse import quote

from deadwax.core import (
    CandidateLabel,
    Credit,
    Entity,
    EntityKind,
    EntityType,
    IdKind,
    NotFoundError,
    Provenance,
    Rating,
    RecordCandidate,
    RecordKey,
    Relation,
    RelationKind,
    Scope,
    SourceError,
    Tag,
    TagKind,
    Text,
    TextKind,
    Verdict,
    compare,
    normalize_text,
)
from deadwax.sources._html import Node, parse_html, text_of
from deadwax.sources.wikipedia import models

SOURCE = "wikipedia"
PUBLICATION = "Wikipedia"
WIKIDATA = "https://www.wikidata.org"

# Instance-of (P31) values accepted for each kind of record.
KIND_TYPES: dict[EntityKind, frozenset[str]] = {
    EntityKind.TRACK: frozenset({"Q7366", "Q134556", "Q105543609", "Q2188189"}),
    EntityKind.ALBUM: frozenset(
        {"Q482994", "Q208569", "Q169930", "Q209939", "Q222910", "Q186588", "Q20711488"}
    ),
}

# Properties whose values are items named in the dossier.
PERFORMER = "P175"
GENRE = "P136"
LABEL = "P264"
PART_OF = "P361"
LANGUAGE = "P407"
DATE = "P577"
REVIEW_SCORE = "P444"
REVIEWER = "P447"
WIKI_LANGUAGE_CODE = "P424"
_CREDITS = {"P162": "producer", "P86": "composer", "P676": "lyricist"}
REFERENCED = (PERFORMER, GENRE, LABEL, PART_OF, LANGUAGE, *_CREDITS)

# Identifiers an item records; a song's release IDs are those of its single, so only albums.
_ALBUM_IDS = {"P436": IdKind.MUSICBRAINZ_RELEASE_GROUP, "P1954": IdKind.DISCOGS_MASTER}
_TRACK_IDS = {"P435": IdKind.MUSICBRAINZ_WORK}

# Language of a search for text in a non-Latin script.
_SCRIPTS = (
    (re.compile(r"[Ѐ-ӿ]"), "ru"),
    (re.compile(r"[぀-ヿ]"), "ja"),
    (re.compile(r"[가-힯]"), "ko"),
    (re.compile(r"[一-鿿]"), "ja"),
    (re.compile(r"[Ͱ-Ͽ]"), "el"),
)

# Section headings worth reading, by wiki language: kept when they contain an allowed
# fragment and none of the denied ones. Other languages contribute the lead only.
_SECTIONS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "en": (
        ("background", "writing", "recording", "production", "composition", "music", "lyric",
         "theme", "style", "release", "reception", "critical", "legacy", "influence"),
        ("video", "track listing", "personnel", "chart", "certification", "reference", "note",
         "link", "reading", "cover version", "release history"),
    ),
    "ru": (
        ("смысл", "истори", "запис", "музык", "композиц", "текст", "отзыв", "критик",
         "восприят", "наследи", "влияни", "отражени", "значени"),
        ("участ", "список", "перезапис", "видео", "версии", "примечани", "ссылк", "литератур",
         "комментари"),
    ),
    "ja": (
        ("背景", "制作", "録音", "音楽", "評価", "歌詞", "概要", "解説", "批評"),
        ("リスト", "参加", "クレジット", "脚注", "出典", "外部リンク", "収録曲"),
    ),
    "de": (
        ("entstehung", "hintergrund", "aufnahme", "musik", "text", "rezeption", "kritik",
         "stil"),
        ("titelliste", "besetzung", "chart", "einzelnachweis", "weblink", "literatur"),
    ),
    "fr": (
        ("genèse", "contexte", "enregistrement", "musique", "composition", "paroles", "accueil",
         "critique", "style", "héritage"),
        ("liste des titres", "personnel", "classement", "référence", "lien", "note"),
    ),
}  # fmt: skip

# Elements whose text is not part of the prose.
_NOISE = (
    "style, sup.reference, sup.noprint, .mw-editsection, .mw-empty-elt, .hatnote, "
    "table, figure, .navbox, .metadata, .reflist, .mw-references-wrap"
)

# Ratings templates and the aggregator parameters they take.
_RATINGS_TEMPLATES = frozenset({"album ratings", "music ratings", "рейтинги альбома"})
_AGGREGATORS = {"mc": "Metacritic", "adm": "AnyDecentMusic?", "aoty": "Album of the Year"}

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_REF = re.compile(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", re.DOTALL | re.IGNORECASE)
_INNER_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
_WIKILINK = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")
_EXTERNAL_LINK = re.compile(r"\[\S+\s+([^\]]+)\]")
_TAG = re.compile(r"<[^>]+>")
_RATING = re.compile(r"\{\{\s*rating\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)", re.IGNORECASE)
_FRACTION = re.compile(r"^([\d.]+)\s*/\s*([\d.]+)$")
_REVIEW_PARAM = re.compile(r"^(rev|agg)(\d+)$")


def check(content: bytes, url: str) -> None:
    """Raise for an error the API reports inside an HTTP 200 response."""
    error = models.Envelope.model_validate_json(content).error
    if error is None:
        return
    if error.code in {"missingtitle", "no-such-entity"}:
        raise NotFoundError(error.info or error.code, url=url)
    raise SourceError(f"{error.code}: {error.info}", url=url)


def entity_url(qid: str) -> str:
    """Return the Wikidata page of an item."""
    return f"{WIKIDATA}/wiki/{qid}"


def article_url(language: str, title: str) -> str:
    """Return the address of an article."""
    return f"https://{language}.wikipedia.org/wiki/{quote(title.replace(' ', '_'), safe='()_,:!')}"


def search_language(text: str) -> str:
    """Guess the language whose labels to compare from the script of a name."""
    return next((lang for pattern, lang in _SCRIPTS if pattern.search(text)), "en")


def type_filter(kind: EntityKind) -> str:
    """CirrusSearch filter for items of the kind's types."""
    return "haswbstatement:" + "|".join(f"P31={qid}" for qid in sorted(KIND_TYPES[kind]))


def fits(item: models.Item, kind: EntityKind) -> bool:
    """Whether the item is an instance of a type of the kind."""
    return bool(set(item.items("P31")) & KIND_TYPES[kind])


def languages(original: str | None, *fallback: str) -> tuple[str, ...]:
    """Label languages in order of preference, without repeats."""
    return tuple(dict.fromkeys(lang for lang in (original, *fallback, "mul", "en") if lang))


def referenced(item: models.Item) -> list[str]:
    """Items whose labels the dossier needs."""
    found = [qid for prop in REFERENCED for qid in item.items(prop)]
    found += [
        qid
        for statement in item.statements(REVIEW_SCORE)
        for snak in statement.qualifiers.get(REVIEWER, [])
        if (qid := snak.item) is not None
    ]
    return list(dict.fromkeys(found))


def wiki_code(claims: models.Claims) -> str | None:
    """Wikimedia language code of a language item."""
    for statement in claims.claims.get(WIKI_LANGUAGE_CODE, []):
        if (code := statement.mainsnak.text) is not None:
            return code
    return None


def pick(
    key: RecordKey,
    items: Sequence[models.Item],
    performers: Mapping[str, models.Item],
    language: str,
) -> str | None:
    """Return the first item of the kind whose performer and title match the key."""
    langs = languages(language)
    for item in items:
        if key.kind is not None and not fits(item, key.kind):
            continue
        titles = item.names(langs)
        artists = [
            name
            for qid in item.items(PERFORMER)
            if (performer := performers.get(qid)) is not None
            for name in performer.names(langs)
        ]
        for artist in artists:
            for title in titles:
                found = RecordKey(artist=artist, title=title, kind=key.kind)
                if compare(key, found).verdict is not Verdict.NO_MATCH:
                    return item.id
    return None


def same_artist(left: str, right: str) -> bool:
    """Whether two artist names match as the core's matching compares them."""
    keys = RecordKey(artist=left, title="x"), RecordKey(artist=right, title="x")
    return compare(*keys).verdict is Verdict.MATCH


def _date(item: models.Item) -> str | None:
    """Earliest publication date, cut to its precision."""
    dates = []
    for statement in item.statements(DATE):
        found = statement.mainsnak.time
        if found is None:
            continue
        time, precision = found
        match = re.match(r"^\+?(\d{4})-(\d{2})-(\d{2})", time)
        if match is None:
            continue
        year, month, day = match.groups()
        if precision <= 9 or month == "00":  # noqa: PLR2004 -- Wikidata's year precision
            dates.append(year)
        elif precision == 10 or day == "00":  # noqa: PLR2004 -- Wikidata's month precision
            dates.append(f"{year}-{month}")
        else:
            dates.append(f"{year}-{month}-{day}")
    return min(dates, default=None)


class Labels:
    """Labels of the items an item refers to, by language preference."""

    def __init__(self, items: Mapping[str, models.Item], original: str | None) -> None:
        self.items = items
        self.name_languages = languages(original)
        self.term_languages = languages("en", original or "en")

    def name(self, qid: str) -> str | None:
        """Name of a person, group, label, or release, as written in its original language."""
        item = self.items.get(qid)
        return item.label(self.name_languages) if item is not None else None

    def performer(self, qid: str, wanted: str | None) -> str | None:
        """Name of a performer: the label or alias matching the wanted name, else the label."""
        item = self.items.get(qid)
        if item is None:
            return None
        if wanted is not None:
            for name in item.names(self.name_languages):
                if same_artist(wanted, name):
                    return name
        return item.label(self.name_languages)

    def term(self, qid: str) -> str | None:
        """Genre or publication, in English when possible."""
        item = self.items.get(qid)
        return item.label(self.term_languages) if item is not None else None


def candidate(
    item: models.Item,
    kind: EntityKind,
    labels: Labels,
    original: str | None,
    artist: str | None = None,
) -> RecordCandidate:
    """Describe the record from its Wikidata statements.

    A performer is named by the label or alias that matches the expected artist, so an
    artist listed under another name (Pendant for Huerco S.) is still recognized.
    """
    url = entity_url(item.id)
    performers = [
        name for qid in item.items(PERFORMER) if (name := labels.performer(qid, artist)) is not None
    ]
    title = item.label(languages(original))
    if not performers or title is None:
        raise NotFoundError("the Wikidata item names no performer or title", url=url)
    ids = {IdKind.WIKIDATA: item.id}
    for prop, id_kind in (_ALBUM_IDS if kind is EntityKind.ALBUM else _TRACK_IDS).items():
        if values := item.texts(prop):
            ids[id_kind] = values[0]
    return RecordCandidate(
        kind=kind,
        artist=", ".join(performers),
        title=title,
        date=_date(item),
        labels=[
            CandidateLabel(name=name)
            for qid in item.items(LABEL)
            if (name := labels.name(qid)) is not None
        ],
        ids=ids,
        url=url,
    )


def claim_tags(item: models.Item, labels: Labels, scope: Scope) -> list[Tag]:
    """Genres stated on the item."""
    sources = [Provenance(source=SOURCE, url=entity_url(item.id))]
    return [
        Tag(name=name, kind=TagKind.GENRE, scope=scope, sources=sources)
        for qid in item.items(GENRE)
        if (name := labels.term(qid)) is not None
    ]


def claim_credits(item: models.Item, labels: Labels, scope: Scope) -> list[Credit]:
    """Producers, composers, and lyricists stated on the item."""
    sources = [Provenance(source=SOURCE, url=entity_url(item.id))]
    return [
        Credit(role=role, name=name, scope=scope, sources=sources)
        for prop, role in _CREDITS.items()
        for qid in item.items(prop)
        if (name := labels.name(qid)) is not None
    ]


def claim_relations(
    item: models.Item, labels: Labels, scope: Scope, albums: Collection[str] = ()
) -> list[Relation]:
    """Labels of the record and the albums it is part of; other 'part of' items are lists."""
    sources = [Provenance(source=SOURCE, url=entity_url(item.id))]
    kinds = ((LABEL, RelationKind.LABEL, EntityType.LABEL),
             (PART_OF, RelationKind.APPEARS_ON, EntityType.RELEASE))  # fmt: skip
    return [
        Relation(
            kind=relation,
            target=Entity(type=entity, name=name, url=entity_url(qid), ids={IdKind.WIKIDATA: qid}),
            scope=Scope.LABEL if relation is RelationKind.LABEL else scope,
            sources=sources,
        )
        for prop, relation, entity in kinds
        for qid in item.items(prop)
        if (name := labels.name(qid)) is not None and (prop != PART_OF or qid in albums)
    ]


def score(value: str) -> Rating | None:
    """Read a score such as '{{Rating|4|5}}', '8.6/10', or 'B+'."""
    value = _REF.sub("", _COMMENT.sub("", value))
    stars = _RATING.search(value)
    if stars is not None:
        return Rating(value=float(stars[1]), scale=float(stars[2]))
    text = clean(value)
    if not text:
        return None
    fraction = _FRACTION.match(text)
    if fraction is not None:
        return Rating(value=float(fraction[1]), scale=float(fraction[2]))
    return Rating(text=text)


def claim_ratings(item: models.Item, labels: Labels, scope: Scope, known: set[str]) -> list[Text]:
    """Review scores stated on the item, for publications the articles do not rate."""
    sources = [Provenance(source=SOURCE, url=entity_url(item.id))]
    result = []
    for statement in item.statements(REVIEW_SCORE):
        reviewers = [s.item for s in statement.qualifiers.get(REVIEWER, []) if s.item]
        publication = labels.term(reviewers[0]) if reviewers else None
        rating = score(statement.mainsnak.text or "")
        if publication is None or rating is None or normalize_text(publication) in known:
            continue
        result.append(
            Text(
                kind=TextKind.REVIEW,
                body="",
                publication=publication,
                rating=rating,
                scope=scope,
                sources=sources,
            )
        )
    return result


def clean(value: str) -> str:
    """Wikitext as plain text: no comments, references, templates, links, or markup."""
    value = _REF.sub("", _COMMENT.sub("", value))
    while (stripped := _INNER_TEMPLATE.sub("", value)) != value:
        value = stripped
    value = _EXTERNAL_LINK.sub(r"\1", _WIKILINK.sub(r"\1", value))
    value = _TAG.sub("", value).replace("'''", "").replace("''", "")
    return " ".join(value.split())


def _closing(wikitext: str, start: int) -> int:
    """Index after the '}}' closing the template that opens at `start`."""
    depth, index = 0, start
    while index < len(wikitext) - 1:
        pair = wikitext[index : index + 2]
        if pair == "{{":
            depth += 1
            index += 2
        elif pair == "}}":
            depth -= 1
            index += 2
            if depth == 0:
                return index
        else:
            index += 1
    return len(wikitext)


def templates(wikitext: str, names: frozenset[str]) -> Iterator[str]:
    """Bodies of the named templates, between the name and the closing braces."""
    for match in re.finditer(r"\{\{\s*([^|{}]+?)\s*(?=[|}])", wikitext):
        name = match[1].replace("_", " ").strip().lower()
        if name in names:
            end = _closing(wikitext, match.start())
            yield wikitext[match.end() : end - 2]


def parameters(body: str) -> dict[str, str]:
    """Named parameters of a template body, split at top-level pipes."""
    parts, depth, current = [], 0, []
    index = 0
    while index < len(body):
        pair = body[index : index + 2]
        if pair in {"{{", "[["}:
            depth += 1
            current.append(pair)
            index += 2
            continue
        if pair in {"}}", "]]"}:
            depth -= 1
            current.append(pair)
            index += 2
            continue
        if body[index] == "|" and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(body[index])
        index += 1
    parts.append("".join(current))
    result = {}
    for part in parts:
        name, sep, value = part.partition("=")
        if sep:
            result[name.strip().lower()] = value.strip()
    return result


def ratings(wikitext: str, language: str, scope: Scope, url: str) -> list[Text]:
    """Scores from the ratings templates of an article."""
    sources = [Provenance(source=SOURCE, url=url)]
    result = []
    for body in templates(wikitext, _RATINGS_TEMPLATES):
        params = parameters(body)
        title = clean(params.get("title", "")) or None
        reviews = [(_AGGREGATORS[key], value) for key, value in params.items()
                   if key in _AGGREGATORS]  # fmt: skip
        numbered = sorted(
            (int(m[2]), m[1], key) for key in params if (m := _REVIEW_PARAM.match(key))
        )
        reviews += [(params[key], params.get(f"{key}score", "")) for _, _, key in numbered]
        for name, value in reviews:
            publication = clean(name)
            rating = score(value)
            if not publication or rating is None:
                continue
            result.append(
                Text(
                    kind=TextKind.REVIEW,
                    body="",
                    title=title,
                    publication=publication,
                    rating=rating,
                    language=language,
                    scope=scope,
                    sources=sources,
                )
            )
    return result


def _heading(node: Node) -> Node | None:
    """The h2 element of a level-2 heading, in current or older markup."""
    if node.tag == "h2":
        return node
    classes = (node.attributes.get("class") or "").split()
    return node.css_first("h2") if node.tag == "div" and "mw-heading2" in classes else None


def _wanted(heading: str, language: str) -> bool:
    allowed, denied = _SECTIONS.get(language, ((), ()))
    heading = heading.lower()
    return any(a in heading for a in allowed) and not any(d in heading for d in denied)


def _prose(nodes: Sequence[Node]) -> str | None:
    paragraphs = []
    for node in nodes:
        found = [node] if node.tag in {"p", "blockquote"} else node.css("p, blockquote")
        paragraphs += [text for p in found if (text := text_of(p)) is not None]
    return "\n\n".join(paragraphs) or None


def sections(html: str, title: str, language: str, scope: Scope, url: str) -> list[Text]:
    """The lead and the sections about the music, without references, tables, or images."""
    document = parse_html(html)
    for node in document.css(_NOISE):
        node.decompose()
    root = document.css_first("div.mw-parser-output") or document.body
    if root is None:
        return []
    groups: list[tuple[str | None, str | None, list[Node]]] = [(None, None, [])]
    for node in root.iter():
        element = _heading(node)
        if element is not None:
            groups.append((text_of(element), element.attributes.get("id"), []))
        else:
            groups[-1][2].append(node)

    result = []
    for index, (heading, anchor, nodes) in enumerate(groups):
        if index > 0 and (heading is None or not _wanted(heading, language)):
            continue
        body = _prose(nodes)
        if body is None:
            continue
        result.append(
            Text(
                kind=TextKind.WIKI,
                body=body,
                title=heading or title,
                publication=PUBLICATION,
                language=language,
                scope=scope,
                sources=[Provenance(source=SOURCE, url=f"{url}#{anchor}" if anchor else url)],
            )
        )
    return result
