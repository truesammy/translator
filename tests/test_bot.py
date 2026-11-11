from cryptography.fernet import Fernet

from translator_bot.bot import TranslatorBot
from translator_bot.commands.embed import register_embed_commands
from translator_bot.commands.setup import register_setup_commands
from translator_bot.config import Config


async def test_all_commands_register_and_are_admin_only(tmp_path):
    bot = TranslatorBot(Config("token", Fernet.generate_key(), tmp_path / "bot.db"))
    register_setup_commands(bot)
    register_embed_commands(bot)
    commands = {command.name: command for command in bot.tree.get_commands()}
    assert set(commands) == {"link", "source-language", "apikey", "embed"}
    assert {c.name for c in commands["link"].commands} == {"add", "remove", "list"}
    assert {c.name for c in commands["apikey"].commands} == {"set", "remove", "status"}
    assert {c.name for c in commands["embed"].commands} == {"create", "edit"}
    for command in commands.values():
        assert command.guild_only and command.default_permissions.manage_guild
        command.to_dict(bot.tree)  # fails on anything Discord would reject at sync time
    await bot.close()
