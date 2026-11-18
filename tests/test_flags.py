import re

from translator_bot.flags import FLAG_TEMPLATE, TRANSLATE_TEMPLATE, button_look, flag_id, pick_language, translate_id


def test_custom_ids_round_trip():
    custom_id = flag_id(1234567890123456789, 1234567890123456780, "zh-CN")
    match = re.fullmatch(FLAG_TEMPLATE, custom_id)
    assert (match["channel"], match["message"], match["code"]) == ("1234567890123456789", "1234567890123456780", "zh-CN")
    assert len(custom_id) <= 100  # Discord's limit
    match = re.fullmatch(TRANSLATE_TEMPLATE, translate_id(1, 2))
    assert (match["channel"], match["message"]) == ("1", "2")


def test_button_look():
    assert button_look(translate_id(1, 2)) == ("🌐", "Translate")
    assert button_look(flag_id(1, 2, "de")) == ("🇩🇪", None)
    assert button_look(flag_id(1, 2, "zh-TW")) == ("🇹🇼", None)
    assert button_look(flag_id(1, 2, "haw")) == (None, "Hawaiian")


def test_pick_language_by_role():
    languages = [("de", 7), ("en", 8), ("fr", None)]
    assert pick_language(languages, {7, 99}) == "de"
    assert pick_language(languages, {99}) is None
    assert pick_language(languages, {7, 8}) is None  # several: let them pick
