from types import SimpleNamespace

import discord
import pytest

from translator_bot.discord_io import data_to_embed, embed_to_data, sanitize_username, snapshot


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


def fake_message(*, from_bot=False, **overrides):
    author = SimpleNamespace(display_name="Mika", display_avatar=SimpleNamespace(url="https://a"), bot=from_bot)
    values = dict(
        id=1,
        guild=SimpleNamespace(id=1),
        channel=SimpleNamespace(id=100),
        author=author,
        content="hi",
        embeds=[],
        attachments=[],
        webhook_id=None,
        mention_everyone=False,
        role_mentions=[],
    )
    return SimpleNamespace(**{**values, **overrides})


def test_snapshot_basics():
    msg = snapshot(fake_message(webhook_id=7), own_webhook_ids={7})
    assert (msg.id, msg.guild_id, msg.channel_id, msg.author_name, msg.content) == (1, 1, 100, "Mika", "hi")
    assert msg.from_own_webhook and not msg.mention_everyone and msg.role_mention_ids == ()


def test_snapshot_ignores_embeds_on_user_messages():
    # People cannot send embeds, so an embed on their message is a link preview.
    message = fake_message(content="https://x.com/a/status/1", embeds=[discord.Embed(title="Tweet")])
    assert snapshot(message, own_webhook_ids=set()).embeds == ()


def test_snapshot_keeps_embeds_of_bots():
    message = fake_message(from_bot=True, content="", embeds=[discord.Embed(title="News")])
    assert [e.title for e in snapshot(message, own_webhook_ids=set()).embeds] == ["News"]


def test_snapshot_drops_bot_embed_that_previews_a_link_in_the_text():
    preview = discord.Embed(title="Tweet", url="https://x.com/a/status/1")
    message = fake_message(from_bot=True, content="see https://x.com/a/status/1", embeds=[preview])
    assert snapshot(message, own_webhook_ids=set()).embeds == ()


def test_snapshot_records_what_really_pinged():
    message = fake_message(mention_everyone=True, role_mentions=[SimpleNamespace(id=7)])
    msg = snapshot(message, own_webhook_ids=set())
    assert msg.mention_everyone and msg.role_mention_ids == (7,)


@pytest.mark.parametrize("raw", ["everyone", "Here"])
def test_sanitize_username_breaks_forbidden_names(raw):
    assert sanitize_username(raw).lower() != raw.lower()
