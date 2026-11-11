import re

import pytest

from translator_bot.protect import has_translatable_text, intact, mask, unmask


def rt(s):
    masked, spans = mask(s)
    return unmask(masked, spans)


@pytest.mark.parametrize(
    "s",
    [
        "Hello **world**",
        "# Title\n- one\n- two\n> quote",
        "  - nested\n1. first\n2. second\n>>> block quote",
        "see <#123> and <@&456>, <@789>, <@!1>",
        "@everyone read https://example.com/a?b=c now",
        "[the docs](https://example.com) are ||secret||",
        "```py\nprint('hi')\n```\nand `x = 1`",
        "<:party:123> <a:spin:456> <t:1700000000:R> </ping:99>",
        "snake_case stays, _italic_ too",
        "-# small print",
        "***both*** __underline__ ~~strike~~ *one*",
        "<https://example.com/hidden> plain",
        "",
    ],
)
def test_round_trip_is_identity(s):
    assert rt(s) == s


def test_only_text_is_left_for_translation():
    masked, _ = mask("**Maintenance** starts <t:1700000000:F> in <#123>")
    assert re.sub(r'<m id="\d+"/>', "", masked) == "Maintenance starts  in "


def test_line_prefixes_are_hidden():
    masked, _ = mask("# Title\n- item\n> quote")
    assert re.sub(r'<m id="\d+"/>', "", masked) == "Title\nitem\nquote"


def test_link_label_is_translatable():
    masked, _ = mask("[the docs](https://example.com)")
    assert "the docs" in masked and "https://example.com" not in masked


def test_code_content_is_hidden():
    masked, _ = mask("run `rm -rf` then ```\nsecret\n```")
    assert "rm -rf" not in masked and "secret" not in masked


def test_markdown_inside_code_is_not_split():
    _, spans = mask("`a **b** c`")
    assert spans == ["`a **b** c`"]


def test_snake_case_is_not_split():
    masked, _ = mask("use snake_case here")
    assert "snake_case" in masked


def test_unmask_replace_everyone():
    masked, spans = mask("@everyone hi")
    assert unmask(masked, spans, {"@everyone": "<@&5>"}) == "<@&5> hi"


@pytest.mark.parametrize(
    "mangled", ['<m id = "0" />', '<m id="0">', "<M ID='0'/>", "<m id=“0”/>", "<m id=«0»/>", '< m id="0" / >']
)
def test_unmask_tolerates_mangled_placeholder(mangled):
    _, spans = mask("<@1>")
    assert unmask(f"hi {mangled}", spans) == "hi <@1>"


def test_unmask_repairs_spaces_added_around_markers():
    masked, spans = mask("# Title\n**Hello** world, see [docs](https://e.x)")
    translated = (
        '<m id="0"/> Titel\n<m id="1"/> Hallo <m id="2"/> Welt, siehe <m id="3"/> Doku <m id="4"/>'
    )
    assert unmask(translated, spans, original=masked) == "# Titel\n**Hallo** Welt, siehe [Doku](https://e.x)"


def test_unmask_keeps_spaces_that_were_in_the_original():
    masked, spans = mask("2 * 3 and <@1> hi")
    assert unmask(masked, spans, original=masked) == "2 * 3 and <@1> hi"


def test_literal_placeholder_in_source_survives():
    assert rt('weird <m id="0"/> text <@1>') == 'weird <m id="0"/> text <@1>'


def test_unknown_placeholder_id_is_left_alone():
    assert unmask('<m id="5"/>', ["x"]) == '<m id="5"/>'


def test_intact():
    masked, _ = mask("a <@1> b <@2>")
    assert intact(masked, 'x <m id="1"/> y <m id = "0" />')
    assert not intact(masked, 'x <m id="0"/>')
    assert not intact(masked, 'x <m id="0"/> <m id="0"/> <m id="1"/>')
    assert not intact(masked, 'x <m id="0"/> <m id="1"/> <m id="7"/>')


def test_intact_without_placeholders():
    assert intact("hello", "hallo")


@pytest.mark.parametrize(
    "s,expected",
    [("hello", True), ("<@1> https://x.y 🎉", False), ("", False), ("**12:30**", False), ("日本語", True)],
)
def test_has_translatable_text(s, expected):
    assert has_translatable_text(mask(s)[0]) is expected
