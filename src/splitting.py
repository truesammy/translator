def split_text(text: str, limit: int = 2000) -> list[str]:
    """Split at a blank line, else a newline, else a space, else mid-word."""
    # shortcut: a split can cut a code block in two, add fence balancing if announcements carry long code
    parts: list[str] = []
    rest = text
    while len(rest) > limit:
        for separator in ("\n\n", "\n", " "):
            cut = rest.rfind(separator, 0, limit + len(separator))
            if cut > 0:
                parts.append(rest[:cut])
                rest = rest[cut + len(separator) :]
                break
        else:
            parts.append(rest[:limit])
            rest = rest[limit:]
    if rest.strip():
        parts.append(rest)
    return parts


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
