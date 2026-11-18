from translator_bot.commands.flags import format_flag_languages


def test_format_flag_languages():
    assert format_flag_languages([("de", 7), ("fr", None)]) == "German → <@&7>\nFrench"
    assert format_flag_languages([]) == "No languages yet."
