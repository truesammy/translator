"""Flag buttons: their custom ids and how they look."""

from .languages import language_name

FLAG_TEMPLATE = r"flag:(?P<channel>\d+):(?P<message>\d+):(?P<code>[\w-]+)"

# Only languages with one obvious flag; the others show their name.
_COUNTRIES = {
    "ar": "SA", "bg": "BG", "cs": "CZ", "da": "DK", "de": "DE", "el": "GR", "en": "GB", "es": "ES", "et": "EE",
    "fa": "IR", "fi": "FI", "fr": "FR", "ga": "IE", "hi": "IN", "hr": "HR", "hu": "HU", "id": "ID", "is": "IS",
    "it": "IT", "iw": "IL", "ja": "JP", "ko": "KR", "lt": "LT", "lv": "LV", "ms": "MY", "nl": "NL", "no": "NO",
    "pl": "PL", "pt": "PT", "ro": "RO", "ru": "RU", "sk": "SK", "sl": "SI", "sr": "RS", "sv": "SE", "th": "TH",
    "tl": "PH", "tr": "TR", "uk": "UA", "vi": "VN", "zh-CN": "CN", "zh-TW": "TW",
}


def flag_id(channel_id: int, message_id: int, code: str) -> str:
    """Custom id of the button that shows message `message_id` of `channel_id` in language `code`."""
    return f"flag:{channel_id}:{message_id}:{code}"


def flag_look(code: str) -> tuple[str | None, str | None]:
    """(emoji, label) of a flag button: the flag alone, or the language name when there is no flag."""
    country = _COUNTRIES.get(code)
    if country is None:
        return None, language_name(code)
    return "".join(chr(0x1F1E6 + ord(letter) - ord("A")) for letter in country), None
