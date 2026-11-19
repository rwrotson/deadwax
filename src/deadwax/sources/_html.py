import json
import logging
from collections.abc import Iterator
from typing import Any

from selectolax.lexbor import LexborHTMLParser, LexborNode

logger = logging.getLogger(__name__)

type Document = LexborHTMLParser
type Node = LexborNode
type JsonObject = dict[str, Any]


def parse_html(content: bytes | str) -> Document:
    """Parse an HTML page."""
    text = content.decode("utf-8", "replace") if isinstance(content, bytes) else content
    return LexborHTMLParser(text)


def text_of(node: Node | None) -> str | None:
    """Return the stripped text of a node with collapsed whitespace, or None when empty."""
    if node is None:
        return None
    text = " ".join(node.text(separator=" ").split())
    return text or None


def prose(node: Node | None) -> str | None:
    """Return the text of a node with collapsed whitespace, without spaces around inline markup."""
    if node is None:
        return None

    # Text nodes are joined as written: a separator would put spaces before punctuation after links.
    return " ".join(node.text(separator="").split()) or None


def attribute(node: Node | None, name: str) -> str | None:
    """Return a non-empty attribute value."""
    if node is None:
        return None
    value = node.attributes.get(name)
    return value or None


def attribute_json(document: Document, name: str) -> JsonObject | None:
    """Decode the JSON object stored in the first `name` attribute of the page."""
    value = attribute(document.css_first(f"[{name}]"), name)
    if value is None:
        return None
    try:
        decoded = json.loads(value)
    except ValueError:
        logger.debug("invalid JSON in %s", name)
        return None
    return decoded if isinstance(decoded, dict) else None


def _objects(value: object) -> Iterator[JsonObject]:
    if isinstance(value, list):
        for item in value:
            yield from _objects(item)
    elif isinstance(value, dict):
        yield value
        yield from _objects(value.get("@graph"))


def _types(item: JsonObject) -> set[str]:
    value = item.get("@type")
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {v for v in value if isinstance(v, str)}
    return set()


def json_ld(document: Document, *types: str) -> list[JsonObject]:
    """Return the JSON-LD objects of the page, only those of the given types when any are named."""
    found: list[JsonObject] = []
    for script in document.css('script[type="application/ld+json"]'):
        try:
            decoded = json.loads(script.text())
        except ValueError:
            logger.debug("invalid JSON-LD block")
            continue
        found.extend(item for item in _objects(decoded) if not types or _types(item) & set(types))
    return found
