from translator_bot.languages import LANGUAGES, deepl_code, get_language, search_languages


def test_deepl_codes():
    codes = [deepl_code(get_language(c)) for c in ("en", "pt", "zh-CN", "zh-TW", "de")]
    assert codes == ["EN-US", "PT-BR", "ZH-HANS", "ZH-HANT", "DE"]


def test_names_are_title_cased():
    assert get_language("de").name == "German"


def test_many_languages_available():
    assert len(LANGUAGES) > 100


def test_search():
    assert search_languages("germ")[0].code == "de"
    assert search_languages("DE")[0].code == "de"


def test_search_limit():
    assert len(search_languages("")) == 25
    assert len(search_languages("", limit=3)) == 3


def test_unknown_code():
    assert get_language("xx-nope") is None
