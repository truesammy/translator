import re

from translator_bot.flags import FLAG_TEMPLATE, flag_id, flag_look


def test_flag_id_round_trip():
    custom_id = flag_id(1234567890123456789, 1234567890123456780, "zh-CN")
    match = re.fullmatch(FLAG_TEMPLATE, custom_id)
    assert (match["channel"], match["message"], match["code"]) == ("1234567890123456789", "1234567890123456780", "zh-CN")
    assert len(custom_id) <= 100  # Discord's limit


def test_flag_look():
    assert flag_look("de") == ("🇩🇪", None)
    assert flag_look("zh-TW") == ("🇹🇼", None)
    assert flag_look("haw") == (None, "Hawaiian")
