from deadwax import Rating, Relation, SourceAccess, VersionInfo

# HTML transports that drive a browser and so run headless or headed.
_BROWSER_TRANSPORTS = frozenset({"patchright", "nodriver"})


def access_label(access: SourceAccess) -> str:
    """Describe the configured routes to a source in their attempt order."""
    parts = ["API (httpx)"] if access.api else []
    if access.browser_headless is not None:
        mode = "headless" if access.browser_headless else "headed"
        if access.browser_headless and access.headed_fallback:
            mode = "headless → headed"
        steps = [
            f"{step} [{mode}]" if step in _BROWSER_TRANSPORTS else step
            for step in access.html_transports
        ]
        parts.append(f"HTML ({' → '.join(steps) if steps else 'no permitted transports'})")
    return "; ".join(parts)


def number(value: float, *, grouped: bool = False) -> str:
    """Write a whole number without a decimal point, optionally with thousands separators."""
    if not value.is_integer():
        return f"{value:g}"
    return f"{int(value):,}" if grouped else str(int(value))


def rating(value: Rating | None) -> str:
    """Write a score as printed by its source, or as value and scale."""
    if value is None:
        return ""
    if value.text:
        return value.text
    if value.value is None:
        return ""
    scale = f"/{value.scale:g}" if value.scale is not None else ""
    return f"{value.value:g}{scale}"


def version_text(version: VersionInfo) -> str:
    """Write a version kind with its title marker."""
    return f"{version.kind} ({version.detail})" if version.detail else str(version.kind)


def relation_details(relation: Relation) -> list[str]:
    """List the note, sampled element, and offsets of a relation."""
    details = [item for item in (relation.note, relation.element) if item]
    if relation.recording_offset is not None:
        details.append(f"recording {relation.recording_offset}s")
    if relation.target_offset is not None:
        details.append(f"target {relation.target_offset}s")
    return details
