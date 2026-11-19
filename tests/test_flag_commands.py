from types import SimpleNamespace

import pytest

from fakes import FakePoster, chain, make_link
from test_discord_io import fake_message
from translator_bot.commands.flags import format_flag_languages, send_translation, translate_for_presser
from translator_bot.db import Store
from translator_bot.relay import Relay


def test_format_flag_languages():
    assert format_flag_languages([("de", 7), ("fr", None)]) == "German → <@&7>\nFrench"
    assert format_flag_languages([]) == "No languages yet."


class FakeInteraction:
    """A press in `channel_id` by someone with `roles`; records every answer."""

    def __init__(self, bot, channel_id, roles=()):
        self.client, self.channel_id, self.guild_id = bot, channel_id, 1
        self.user = SimpleNamespace(roles=[SimpleNamespace(id=role) for role in roles])
        self.answers = []
        self.response = SimpleNamespace(defer=self._defer, send_message=self._send)
        self.followup = SimpleNamespace(send=self._send)

    async def _defer(self, **options):
        pass

    async def _send(self, content=None, **options):
        self.answers.append(content)


@pytest.fixture
async def bot():
    store = await Store.open(":memory:")
    await store.add_link(make_link(language="original", target=201))  # copies of channel 100 land in 201

    async def chain_for(guild_id):
        return chain()

    async def fetch_message(message_id):
        return fake_message(id=message_id, content="hello")

    source = SimpleNamespace(id=100, guild=SimpleNamespace(id=1), fetch_message=fetch_message)
    yield SimpleNamespace(
        store=store, relay=Relay(store, FakePoster(), chain_for), get_channel=lambda cid: source if cid == 100 else None
    )
    await store.close()


@pytest.mark.parametrize("pressed_in", [100, 201])  # the message's own channel, a channel with its copies
async def test_translation_of_a_message_shown_here(bot, pressed_in):
    interaction = FakeInteraction(bot, pressed_in)
    await send_translation(interaction, 100, 1, "de")
    assert interaction.answers == ["[de] hello"]


async def test_a_button_naming_a_channel_without_copies_here_reads_nothing(bot):
    # Its ids come from the client: they must not open a channel the presser cannot see.
    interaction = FakeInteraction(bot, 300)
    await send_translation(interaction, 100, 1, "de")
    assert interaction.answers == ["This message is no longer available."]


async def test_presser_gets_the_language_of_their_role_or_picks_one(bot):
    await bot.store.add_flag_language(1, "de", 7)
    await bot.store.add_flag_language(1, "fr", 8)
    reader = FakeInteraction(bot, 201, roles=[7, 99])
    await translate_for_presser(reader, 100, 1)
    assert reader.answers == ["[de] hello"]
    stranger = FakeInteraction(bot, 201, roles=[99])
    await translate_for_presser(stranger, 100, 1)
    assert stranger.answers == ["Pick a language."]
