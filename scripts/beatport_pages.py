import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from selectolax.lexbor import LexborHTMLParser

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "beatport" / "pages"

# Page properties dropped from fixtures: the anonymous session holds an access token.
DROPPED = frozenset({"anonSession", "_nextI18Next"})

# Longest list kept from a prefetched query, so that fixtures stay small.
KEPT_ITEMS = 12


def page_source(text: str) -> str:
    """The page's HTML, also from a page saved from the browser's view-source tab."""
    document = LexborHTMLParser(text)
    lines = document.css("td.line-content")
    return "\n".join(line.text(deep=True) for line in lines) if lines else text


def trimmed(props: dict[str, Any]) -> dict[str, Any]:
    """Page properties without the session and with long query lists cut."""
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


def fixture(text: str) -> str:
    """A minimal page holding only the trimmed Next.js state."""
    script = LexborHTMLParser(page_source(text)).css_first("script#__NEXT_DATA__")
    if script is None:
        raise ValueError("no __NEXT_DATA__ state")
    state = json.loads(script.text())
    state["props"]["pageProps"] = trimmed(state["props"]["pageProps"])
    encoded = json.dumps(state, ensure_ascii=False, indent=1).replace("</", "<\\/")
    if re.search(r"access_token|Bearer ", encoded):
        raise ValueError("a token is left in the state")
    return f'<script id="__NEXT_DATA__" type="application/json">{encoded}</script>\n'


def main() -> None:
    """Turn Beatport pages saved from a browser into test fixtures."""
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("pages", nargs="+", type=Path, help="saved .html pages")
    parser.add_argument("--name", action="append", default=[], help="fixture name per page")
    args = parser.parse_args()
    if args.name and len(args.name) != len(args.pages):
        parser.error("give one --name per page, or none")

    FIXTURES.mkdir(parents=True, exist_ok=True)
    names = args.name or [page.stem for page in args.pages]
    for page, name in zip(args.pages, names, strict=True):
        target = FIXTURES / f"{name}.html"
        target.write_text(fixture(page.read_text("utf-8")))
        sys.stdout.write(f"{page.name} -> {target.relative_to(FIXTURES.parent.parent.parent)}\n")


if __name__ == "__main__":
    main()
