import discord

from translator_bot.commands.setup import format_links, language_choices, missing_target_permissions
from translator_bot.models import Link


def test_format_links():
    links = [Link(1, 100, 202, "fr", 5), Link(1, 100, 201, "de", None), Link(1, 300, 301, "ja", None)]
    assert format_links(links, {100: None, 300: "en"}) == (
        "<#100> (source language: auto)\n→ <#201> German\n→ <#202> French, pings <@&5>\n\n"
        "<#300> (source language: English)\n→ <#301> Japanese"
    )


def test_format_links_empty():
    assert format_links([], {}) == "No links yet."


def test_missing_target_permissions():
    assert missing_target_permissions(discord.Permissions.all()) == []
    perms = discord.Permissions(view_channel=True, send_messages=True, embed_links=True, attach_files=True)
    assert missing_target_permissions(perms) == ["Manage Webhooks", "Manage Messages"]
    assert len(missing_target_permissions(discord.Permissions.none())) == 6


def test_language_choices():
    assert language_choices("germ")[0] == ("German (de)", "de")
    assert len(language_choices("")) == 25


def test_language_choices_with_auto_first():
    choices = language_choices("", with_auto=True)
    assert choices[0] == ("Detect automatically", "auto") and len(choices) == 25
    assert language_choices("germ", with_auto=True)[0] == ("German (de)", "de")
