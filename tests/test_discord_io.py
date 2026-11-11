import discord
import pytest

from translator_bot.discord_io import data_to_embed, embed_to_data, sanitize_username


@pytest.mark.parametrize(
    "raw,expected",
    [("Mika", "Mika"), ("  ", "Unknown"), ("", "Unknown"), ("x" * 100, "x" * 80), ("  Mika  ", "Mika")],
)
def test_sanitize_username(raw, expected):
    assert sanitize_username(raw) == expected


@pytest.mark.parametrize("raw", ["Discord Mod", "clyde", "DISCORD", "d" * 75 + "discord"])
def test_sanitize_username_breaks_reserved_words(raw):
    out = sanitize_username(raw).lower()
    assert "discord" not in out and "clyde" not in out and 0 < len(out) <= 80


def test_embed_round_trip():
    embed = discord.Embed(title="T", description="D", color=0x00FF00, url="https://u")
    embed.add_field(name="N", value="V", inline=True)
    embed.add_field(name="N2", value="V2", inline=False)
    embed.set_footer(text="F", icon_url="https://f")
    embed.set_author(name="A", url="https://a", icon_url="https://ai")
    embed.set_image(url="https://i")
    embed.set_thumbnail(url="https://t")
    assert data_to_embed(embed_to_data(embed)).to_dict() == embed.to_dict()


def test_embed_without_optional_parts():
    assert data_to_embed(embed_to_data(discord.Embed())).to_dict() == discord.Embed().to_dict()


def test_embed_data_holds_plain_values():
    data = embed_to_data(discord.Embed(title="T", color=0x00FF00))
    assert (data.title, data.color, data.description, data.fields) == ("T", 0x00FF00, None, ())
