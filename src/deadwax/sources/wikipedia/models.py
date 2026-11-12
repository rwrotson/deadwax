from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    """Base for Wikidata and MediaWiki API responses; unknown fields are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class ApiError(ApiModel):
    """Error reported inside a successful HTTP response."""

    code: str = ""
    info: str = ""


class Envelope(ApiModel):
    """Any response, checked for an error first."""

    error: ApiError | None = None


class DataValue(ApiModel):
    """Value of a snak: an item reference, a string, a time, or another type."""

    type: str
    value: Any


class Snak(ApiModel):
    """Property and value of a statement or qualifier; 'novalue' and 'somevalue' have none."""

    prop: str = Field(alias="property")
    snaktype: str = "value"
    datavalue: DataValue | None = None

    @property
    def item(self) -> str | None:
        """Referenced item ID, if the value is an item."""
        value = self.datavalue.value if self.datavalue is not None else None
        if isinstance(value, dict) and isinstance(value.get("id"), str):
            return str(value["id"])
        return None

    @property
    def text(self) -> str | None:
        """String value, if the value is a string."""
        value = self.datavalue.value if self.datavalue is not None else None
        return value if isinstance(value, str) and value else None

    @property
    def time(self) -> tuple[str, int] | None:
        """Time value with its precision (9 year, 10 month, 11 day)."""
        value = self.datavalue.value if self.datavalue is not None else None
        if isinstance(value, dict) and isinstance(value.get("time"), str):
            return str(value["time"]), int(value.get("precision", 11))
        return None


class Statement(ApiModel):
    """Claim with its qualifiers."""

    mainsnak: Snak
    rank: str = "normal"
    qualifiers: dict[str, list[Snak]] = {}


class LanguageValue(ApiModel):
    """Label in one language."""

    language: str
    value: str


class Sitelink(ApiModel):
    """Article about the item on one wiki."""

    site: str
    title: str


class Item(ApiModel):
    """Wikidata item with the requested parts."""

    id: str
    labels: dict[str, LanguageValue] = {}
    aliases: dict[str, list[LanguageValue]] = {}
    claims: dict[str, list[Statement]] = {}
    sitelinks: dict[str, Sitelink] = {}

    def statements(self, prop: str) -> list[Statement]:
        """Statements of a property, without deprecated ones."""
        return [s for s in self.claims.get(prop, []) if s.rank != "deprecated"]

    def items(self, prop: str) -> list[str]:
        """Item IDs a property refers to, in order and without repeats."""
        found = (s.mainsnak.item for s in self.statements(prop))
        return list(dict.fromkeys(i for i in found if i is not None))

    def texts(self, prop: str) -> list[str]:
        """String values of a property."""
        return [t for s in self.statements(prop) if (t := s.mainsnak.text) is not None]

    def label(self, languages: tuple[str, ...]) -> str | None:
        """Label in the first of the languages that has one."""
        return next((self.labels[lang].value for lang in languages if lang in self.labels), None)

    def names(self, languages: tuple[str, ...]) -> list[str]:
        """Labels, then aliases, in the given languages, without repeats."""
        labels = [self.labels[lang].value for lang in languages if lang in self.labels]
        aliases = [alias.value for lang in languages for alias in self.aliases.get(lang, [])]
        return list(dict.fromkeys(labels + aliases))


class Entities(ApiModel):
    """Response of wbgetentities; missing items have no labels or claims."""

    entities: dict[str, Item] = {}


class Claims(ApiModel):
    """Response of wbgetclaims."""

    claims: dict[str, list[Statement]] = {}


class SearchHit(ApiModel):
    """Page found by a search; on Wikidata its title is the item ID."""

    title: str


class SearchResults(ApiModel):
    """Search results."""

    search: list[SearchHit] = []


class Search(ApiModel):
    """Response of list=search."""

    query: SearchResults = SearchResults()


class Page(ApiModel):
    """Rendered article with its wikitext."""

    title: str
    text: str = ""
    wikitext: str = ""


class Parse(ApiModel):
    """Response of action=parse."""

    parse: Page
