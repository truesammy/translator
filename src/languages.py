from dataclasses import dataclass

from deep_translator.constants import GOOGLE_LANGUAGES_TO_CODES


@dataclass(frozen=True)
class Language:
    code: str  # Google's code, e.g. "de", "zh-CN"
    name: str  # English name, e.g. "German"


LANGUAGES: dict[str, Language] = {
    code: Language(code, name.title()) for name, code in GOOGLE_LANGUAGES_TO_CODES.items()
}

_DEEPL_CODES = {"en": "EN-US", "pt": "PT-BR", "zh-CN": "ZH-HANS", "zh-TW": "ZH-HANT", "no": "NB", "iw": "HE"}


def get_language(code: str) -> Language | None:
    return LANGUAGES.get(code)


def deepl_code(lang: Language) -> str:
    """DeepL target code. Languages DeepL does not know are rejected by DeepL itself."""
    return _DEEPL_CODES.get(lang.code, lang.code.upper())


def search_languages(query: str, limit: int = 25) -> list[Language]:
    q = query.strip().lower()
    matches = [l for l in LANGUAGES.values() if q in l.name.lower() or l.code.lower().startswith(q)]
    matches.sort(key=lambda l: (l.code.lower() != q, l.name))
    return matches[:limit]
