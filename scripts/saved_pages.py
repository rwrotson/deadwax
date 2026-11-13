import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from selectolax.lexbor import LexborHTMLParser

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# Beatport page properties dropped from fixtures: the anonymous session holds an access token.
DROPPED = frozenset({"anonSession", "_nextI18Next"})

# Longest list kept from a prefetched Beatport query, so that fixtures stay small.
KEPT_ITEMS = 12

# Page parts each shop's parser reads; everything else is dropped.
KEPT_BLOCKS = {
    "juno": ("#product-page-music", ".product-list"),
    "phonica": ("main",),
}

# Markup that parsers never read and that may carry session data.
REMOVED = "script, style, svg, form, iframe, noscript, template"

SECRETS = re.compile(r"access_token|Bearer |sessionid|csrf", re.IGNORECASE)


def page_source(text: str) -> str:
    """The page's HTML, also from a page saved from Chrome's or Firefox's view-source tab."""
    document = LexborHTMLParser(text)
    chrome = document.css("td.line-content")
    if chrome:
        return "\n".join(line.text(deep=True) for line in chrome)
    firefox = document.css('body#viewsource > span[id^="line"]')
    if firefox:
        return "".join(line.text(deep=True) for line in firefox)
    return text


def trimmed(props: dict[str, Any]) -> dict[str, Any]:
    """Beatport page properties without the session and with long query lists cut."""
    kept = {name: value for name, value in props.items() if name not in DROPPED}
    for query in kept.get("dehydratedState", {}).get("queries", []):
        data = query.get("state", {}).get("data")
        if isinstance(data, list):
            query["state"]["data"] = data[:KEPT_ITEMS]
        elif isinstance(data, dict):
            for name in ("data", "results"):
                if isinstance(data.get(name), list):
                    data[name] = data[name][:KEPT_ITEMS]
    return kept


def beatport_fixture(source: str) -> str:
    """A minimal page holding only the trimmed Next.js state."""
    script = LexborHTMLParser(source).css_first("script#__NEXT_DATA__")
    if script is None:
        raise ValueError("no __NEXT_DATA__ state")
    state = json.loads(script.text())
    state["props"]["pageProps"] = trimmed(state["props"]["pageProps"])
    encoded = json.dumps(state, ensure_ascii=False, indent=1).replace("</", "<\\/")
    return f'<script id="__NEXT_DATA__" type="application/json">{encoded}</script>\n'


def shop_fixture(source: str, shop: str) -> str:
    """A page holding the canonical link, Open Graph tags, and the blocks the parser reads."""
    document = LexborHTMLParser(source)
    head = [
        node.html or "" for node in document.css('link[rel="canonical"], meta[property^="og:"]')
    ]
    blocks = [node for selector in KEPT_BLOCKS[shop] for node in document.css(selector)]
    if not blocks:
        raise ValueError(f"no {', '.join(KEPT_BLOCKS[shop])} on the page")
    for block in blocks:
        for node in block.css(REMOVED):
            node.decompose()
    body = "\n".join(re.sub(r"\s*\n\s*", "\n", block.html or "") for block in blocks)
    return "<html><head>\n" + "\n".join(head) + f"\n</head><body>\n{body}\n</body></html>\n"


def fixture(text: str, shop: str) -> str:
    """Turn a saved page into a fixture, refusing one that still holds session data."""
    source = page_source(text)
    result = beatport_fixture(source) if shop == "beatport" else shop_fixture(source, shop)
    if SECRETS.search(result):
        raise ValueError("session data is left in the page")
    return result


def main() -> None:
    """Turn pages saved from a browser into test fixtures."""
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("pages", nargs="+", type=Path, help="saved .html pages")
    parser.add_argument("--shop", required=True, choices=["beatport", *KEPT_BLOCKS])
    parser.add_argument("--name", action="append", default=[], help="fixture name per page")
    args = parser.parse_args()
    if args.name and len(args.name) != len(args.pages):
        parser.error("give one --name per page, or none")

    target_dir = FIXTURES / args.shop / "pages"
    target_dir.mkdir(parents=True, exist_ok=True)
    names = args.name or [page.stem for page in args.pages]
    for page, name in zip(args.pages, names, strict=True):
        target = target_dir / f"{name}.html"
        target.write_text(fixture(page.read_text("utf-8"), args.shop))
        sys.stdout.write(f"{page.name} -> {target.relative_to(FIXTURES.parent.parent)}\n")


if __name__ == "__main__":
    main()
