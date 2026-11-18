"""Translate and flag buttons: their custom ids, how they look, and which language a press means."""

from .languages import language_name

TRANSLATE_TEMPLATE = r"translate:(?P<channel>\d+):(?P<message>\d+)"
FLAG_TEMPLATE = r"flag:(?P<channel>\d+):(?P<message>\d+):(?P<code>[\w-]+)"

# Only languages with one obvious flag; the others show their name.
_COUNTRIES = {
    "ar": "SA", "bg": "BG", "cs": "CZ", "da": "DK", "de": "DE", "el": "GR", "en": "GB", "es": "ES", "et": "EE",
    "fa": "IR", "fi": "FI", "fr": "FR", "ga": "IE", "hi": "IN", "hr": "HR", "hu": "HU", "id": "ID", "is": "IS",
    "it": "IT", "iw": "IL", "ja": "JP", "ko": "KR", "lt": "LT", "lv": "LV", "ms": "MY", "nl": "NL", "no": "NO",
    "pl": "PL", "pt": "PT", "ro": "RO", "ru": "RU", "sk": "SK", "sl": "SI", "sr": "RS", "sv": "SE", "th": "TH",
    "tl": "PH", "tr": "TR", "uk": "UA", "vi": "VN", "zh-CN": "CN", "zh-TW": "TW",
}


def translate_id(channel_id: int, message_id: int) -> str:
    """Custom id of the button that shows message `message_id` of `channel_id` in the presser's language."""
    return f"translate:{channel_id}:{message_id}"


def flag_id(channel_id: int, message_id: int, code: str) -> str:
    """Custom id of the button that shows message `message_id` of `channel_id` in language `code`."""
    return f"flag:{channel_id}:{message_id}:{code}"


def button_look(custom_id: str) -> tuple[str | None, str | None]:
    """(emoji, label) of a button: 🌐 Translate, a flag alone, or the language name when there is no flag."""
    if custom_id.startswith("translate:"):
        return "🌐", "Translate"
    code = custom_id.rsplit(":", 1)[1]
    country = _COUNTRIES.get(code)
    if country is None:
        return None, language_name(code)
    return "".join(chr(0x1F1E6 + ord(letter) - ord("A")) for letter in country), None


def pick_language(languages: list[tuple[str, int | None]], role_ids: set[int]) -> str | None:
    """The language of the presser's role, or None when they have none or several of them."""
    mine = [code for code, role_id in languages if role_id in role_ids]
    return mine[0] if len(mine) == 1 else None
