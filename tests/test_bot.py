from types import SimpleNamespace

import discord
from cryptography.fernet import Fernet

import translator_bot.bot as bot_module
from translator_bot.bot import TranslatorBot
from translator_bot.db import Store
from translator_bot.commands.embed import register_embed_commands
from translator_bot.commands.flags import register_flag_commands
from translator_bot.commands.setup import register_setup_commands
from translator_bot.config import Config
from translator_bot.relay import Relay
from fakes import FakePoster


async def test_all_commands_register_and_are_admin_only(tmp_path):
    bot = TranslatorBot(Config("token", Fernet.generate_key(), tmp_path / "bot.db"))
    register_setup_commands(bot)
    register_embed_commands(bot)
    register_flag_commands(bot)
    commands = {command.name: command for command in bot.tree.get_commands()}
    assert set(commands) == {"link", "source-language", "apikey", "embed", "flags", "Add translate button", "Translate"}
    assert {c.name for c in commands["flags"].commands} == {"add", "remove", "list"}
    assert {c.name for c in commands["link"].commands} == {"add", "remove", "list"}
    assert {c.name for c in commands["apikey"].commands} == {"set", "remove", "status"}
    assert {c.name for c in commands["embed"].commands} == {"create", "edit"}
    for command in commands.values():
        assert command.guild_only and command.default_permissions.manage_guild
        command.to_dict(bot.tree)  # fails on anything Discord would reject at sync time
    await bot.close()


def make_bot(tmp_path):
    return TranslatorBot(Config("token", Fernet.generate_key(), tmp_path / "bot.db"))


def test_replies_to_slash_commands_of_other_bots_are_relayed():
    assert discord.MessageType.chat_input_command in bot_module.RELAYED_TYPES
    assert discord.MessageType.context_menu_command in bot_module.RELAYED_TYPES


async def test_undecryptable_key_falls_back_to_the_free_providers(tmp_path, caplog):
    bot = make_bot(tmp_path)
    bot.store = await Store.open(":memory:")
    await bot.store.set_deepl_key(1, b"not encrypted with this key")
    chain = await bot.chain_for(1)
    assert [p.name for p in chain._providers] == ["google"]
    assert "cannot be decrypted" in caplog.text
    await bot.close()


async def test_catch_up_runs_again_after_a_reconnect(tmp_path, monkeypatch):
    runs = []

    async def fake_reconcile(*args):
        runs.append(1)

    async def fake_prune(*args):
        pass

    monkeypatch.setattr(bot_module, "reconcile", fake_reconcile)
    monkeypatch.setattr(bot_module, "prune", fake_prune)
    bot = make_bot(tmp_path)
    bot.store = bot.relay = None
    bot.start_catch_up()
    first = bot._catch_up
    bot.start_catch_up()
    assert bot._catch_up is first  # still running: no second one
    await first
    bot.start_catch_up()
    await bot._catch_up
    assert len(runs) == 2


async def test_reply_of_a_message_deleted_while_offline_is_deleted(tmp_path):
    bot = make_bot(tmp_path)
    bot.store = await Store.open(":memory:")
    poster = FakePoster()
    bot.relay = Relay(bot.store, poster, None)
    await bot.store.add_flag_reply(1, 5, 100, 6)  # message 5 is gone
    await bot.store.add_flag_reply(1, 7, 100, 8)  # message 7 still exists

    async def fetch_message(message_id):
        if message_id == 5:
            raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")
        return SimpleNamespace(id=message_id)

    bot.get_channel = lambda channel_id: SimpleNamespace(id=channel_id, fetch_message=fetch_message)
    await bot._drop_orphan_flag_replies()
    assert poster.deleted == [(100, 6)]
    assert await bot.store.flag_reply_messages() == [(7, 100)]
    await bot.close()


async def test_history_without_the_permission_to_read_it_counts_as_unreadable(tmp_path):
    # Discord answers with an empty list then, which catch-up would take for "everything was deleted".
    bot = make_bot(tmp_path)
    permissions = SimpleNamespace(read_message_history=False)
    channel = SimpleNamespace(guild=SimpleNamespace(me=None), permissions_for=lambda member: permissions)
    bot.get_channel = lambda channel_id: channel
    assert await bot._fetch_history(100, 0) is None
    await bot.close()
