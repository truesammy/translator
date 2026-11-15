"""Hide everything a translator must not touch behind <m id="N"/> placeholders."""

import re
from collections.abc import Mapping

# Leftmost match wins; at the same position the earlier alternative wins.
_PROTECTED = re.compile(
    r"""
      ```[\s\S]*?```                                  # fenced code block
    | `[^`\n]+`                                       # inline code
    | <\s*m\s+id[^>\n]*>                              # text that already looks like a placeholder
    | @everyone | @here
    | <@[!&]?\d+> | <\#\d+>                           # user, role, channel mention
    | <a?:\w+:\d+>                                    # custom emoji
    | <t:-?\d+(?::[a-zA-Z])?>                         # timestamp
    | </[^>\n]+:\d+>                                  # command mention
    | \[(?=[^\]\n]*\]\(\s*<?https?://)                # opening bracket of [label](url)
    | \]\(\s*<?https?://[^\s)]+>?(?:\s+"[^"\n]*")?\)  # ](url) of a masked link
    | <https?://[^\s>]+>                              # <url>
    | https?://[^\s<>]+                               # bare url
    | ^[ \t]*(?:\#{1,3}|-\#|>>>|>|[-*]|\d+\.)[ \t]+   # heading, quote, list prefix
    | \*{1,3} | __ | ~~ | \|\|                        # inline markers
    | (?<![^\W_])_ | _(?![^\W_])                      # single underscore, not inside a word
    """,
    re.VERBOSE | re.MULTILINE,
)

# Tolerant: translators add spaces, drop the slash, swap quote characters, change case.
_QUOTE = "[\"'“”„«»‘’]?"
_PLACEHOLDER = re.compile(rf"<\s*m\s+id\s*=\s*{_QUOTE}\s*(\d+)\s*{_QUOTE}\s*/?\s*>", re.IGNORECASE)


def mask(text: str) -> tuple[str, list[str]]:
    spans: list[str] = []

    def hide(match: re.Match) -> str:
        spans.append(match.group(0))
        return f'<m id="{len(spans) - 1}"/>'

    return _PROTECTED.sub(hide, text), spans


def unmask(
    text: str, spans: list[str], replace: Mapping[str, str] | None = None, original: str | None = None
) -> str:
    """Restore the spans. With `original` (the masked source text), spaces a translator
    put next to a placeholder that had none there are removed again, so `** bold **`
    does not break the formatting."""
    replace = replace or {}
    tight_before: set[int] = set()
    tight_after: set[int] = set()
    for match in _PLACEHOLDER.finditer(original or ""):
        index = int(match.group(1))
        if match.start() > 0 and not original[match.start() - 1].isspace():
            tight_before.add(index)
        if match.end() < len(original) and not original[match.end()].isspace():
            tight_after.add(index)

    out: list[str] = []
    pos = 0
    for match in _PLACEHOLDER.finditer(text):
        index = int(match.group(1))
        if index >= len(spans):
            continue
        chunk = text[pos : match.start()]
        out.append(chunk.rstrip(" ") if index in tight_before else chunk)
        out.append(replace.get(spans[index], spans[index]))
        pos = match.end()
        if index in tight_after:
            while pos < len(text) and text[pos] == " ":
                pos += 1
    out.append(text[pos:])
    return "".join(out)


def _ids(text: str) -> list[int]:
    return sorted(int(match.group(1)) for match in _PLACEHOLDER.finditer(text))


def intact(masked: str, translated: str) -> bool:
    return _ids(masked) == _ids(translated)


def has_translatable_text(masked: str) -> bool:
    return any(char.isalpha() for char in _PLACEHOLDER.sub("", masked))
