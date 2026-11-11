import pytest

from translator_bot.commands.embed import (
    EmbedInputError,
    build_embed,
    format_color,
    parse_color,
    parse_image_url,
    parse_message_ref,
)


@pytest.mark.parametrize(
    "text,expected", [("", None), ("#ff8800", 0xFF8800), ("FF8800", 0xFF8800), (" #5865f2 ", 0x5865F2)]
)
def test_parse_color(text, expected):
    assert parse_color(text) == expected


@pytest.mark.parametrize("text", ["red", "#12", "#gggggg", "1234567"])
def test_parse_color_rejects(text):
    with pytest.raises(EmbedInputError, match="hex"):
        parse_color(text)


def test_format_color_round_trips():
    assert format_color(0x00FF8) == "#000FF8" and format_color(None) == ""
    assert parse_color(format_color(0x5865F2)) == 0x5865F2


def test_parse_image_url():
    assert parse_image_url("") is None
    assert parse_image_url(" https://x/y.png ") == "https://x/y.png"
    with pytest.raises(EmbedInputError):
        parse_image_url("x/y.png")


@pytest.mark.parametrize("text", ["1234567890", "https://discord.com/channels/1/2/1234567890", " 1234567890 "])
def test_parse_message_ref(text):
    assert parse_message_ref(text) == 1234567890


def test_parse_message_ref_rejects():
    with pytest.raises(EmbedInputError):
        parse_message_ref("not a message")


def test_build_embed():
    embed = build_embed("T", "Body", "#ff0000", "https://i/x.png", "F")
    assert (embed.title, embed.description, embed.color, embed.image_url, embed.footer_text) == (
        "T",
        "Body",
        0xFF0000,
        "https://i/x.png",
        "F",
    )


def test_build_embed_blank_optionals_become_none():
    embed = build_embed("", "Body", "", "", " ")
    assert (embed.title, embed.color, embed.image_url, embed.footer_text) == (None, None, None, None)


def test_build_embed_needs_text():
    with pytest.raises(EmbedInputError):
        build_embed("T", "   ", "", "", "")
