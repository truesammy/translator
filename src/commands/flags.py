import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from ..chain import AllProvidersFailed
from ..discord_io import data_to_embed, flag_view, snapshot
from ..flags import FLAG_TEMPLATE, flag_id
from ..languages import get_language, language_name
from .setup import ADMIN_ONLY, language_choices

if TYPE_CHECKING:
    from ..bot import TranslatorBot

log = logging.getLogger(__name__)

MAX_FLAGS = 25  # buttons Discord allows on one message


class FlagButton(discord.ui.DynamicItem[discord.ui.Button], template=FLAG_TEMPLATE):
    """Answers a press on any flag button, also on messages posted before a restart."""

    def __init__(self, channel_id: int, message_id: int, code: str):
        super().__init__(discord.ui.Button(custom_id=flag_id(channel_id, message_id, code)))
        self.channel_id, self.message_id, self.code = channel_id, message_id, code

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match):
        return cls(int(match["channel"]), int(match["message"]), match["code"])

    async def callback(self, interaction: discord.Interaction) -> None:
        async def answer(text: str) -> None:
            await interaction.followup.send(text, ephemeral=True)

        await interaction.response.defer(ephemeral=True, thinking=True)
        bot: "TranslatorBot" = interaction.client
        channel = bot.get_channel(self.channel_id)
        # The original may sit in a channel the presser cannot see, but never in another server.
        if channel is None or channel.guild.id != interaction.guild_id:
            return await answer("This message is no longer available.")
        try:
            message = await channel.fetch_message(self.message_id)
        except discord.HTTPException:
            return await answer("This message is no longer available.")
        try:
            parts = await bot.relay.private_translation(snapshot(message, own_webhook_ids=set()), self.code)
        except AllProvidersFailed as error:
            log.warning("Private translation of %s to %s failed: %s", self.message_id, self.code, error)
            return await answer("The translation failed. Try again later.")
        parts = [part for part in parts if part.content or part.embeds]
        if not parts:
            return await answer("There is no text to translate.")
        for part in parts:
            await interaction.followup.send(
                part.content,
                embeds=[data_to_embed(embed) for embed in part.embeds],
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )


def register_flag_commands(bot: "TranslatorBot") -> None:
    bot.add_dynamic_items(FlagButton)

    async def reply(interaction: discord.Interaction, text: str) -> None:
        await interaction.response.send_message(text, ephemeral=True)

    async def show(interaction: discord.Interaction) -> None:
        codes = await bot.store.flag_languages(interaction.guild_id)
        await reply(interaction, f"Flag languages: {', '.join(map(language_name, codes)) or 'none'}.")

    async def flags_for(message: discord.Message) -> discord.ui.View | None:
        codes = await bot.store.flag_languages(message.guild.id)
        return flag_view(tuple(flag_id(message.channel.id, message.id, code) for code in codes))

    async def language_autocomplete(interaction: discord.Interaction, current: str):
        return [app_commands.Choice(name=name, value=value) for name, value in language_choices(current)]

    flags = app_commands.Group(
        name="flags", description="Manage the flag buttons for private translations", guild_only=True,
        default_permissions=ADMIN_ONLY,
    )

    @flags.command(name="add", description="Offer a language on the flag buttons")
    @app_commands.describe(language="Language to offer")
    @app_commands.autocomplete(language=language_autocomplete)
    async def flags_add(interaction: discord.Interaction, language: str) -> None:
        if get_language(language) is None:
            return await reply(interaction, "Unknown language. Pick one from the list.")
        codes = await bot.store.flag_languages(interaction.guild_id)
        if language not in codes and len(codes) >= MAX_FLAGS:
            return await reply(interaction, f"A message can carry at most {MAX_FLAGS} buttons.")
        await bot.store.add_flag_language(interaction.guild_id, language)
        await show(interaction)

    @flags.command(name="remove", description="Stop offering a language on the flag buttons")
    @app_commands.describe(language="Language to remove")
    @app_commands.autocomplete(language=language_autocomplete)
    async def flags_remove(interaction: discord.Interaction, language: str) -> None:
        if not await bot.store.remove_flag_language(interaction.guild_id, language):
            return await reply(interaction, "That language has no flag.")
        await show(interaction)

    @flags.command(name="list", description="Show the languages on the flag buttons")
    async def flags_list(interaction: discord.Interaction) -> None:
        await show(interaction)

    bot.tree.add_command(flags)

    @bot.tree.context_menu(name="Add translation flags")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def add_flags(interaction: discord.Interaction, message: discord.Message) -> None:
        view = await flags_for(message)
        if view is None:
            return await reply(interaction, "Add languages with /flags add first.")
        try:
            sent = await message.reply(view=view, mention_author=False)
        except discord.HTTPException as error:
            return await reply(interaction, f"Could not reply there: {error.text or error.status}")
        await bot.store.add_flag_reply(interaction.guild_id, message.id, message.channel.id, sent.id)
        await reply(interaction, "Flags added.")

    # Admin-only at first; admins open it to everyone in Server Settings → Integrations.
    @bot.tree.context_menu(name="Translate")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def translate(interaction: discord.Interaction, message: discord.Message) -> None:
        view = await flags_for(message)
        if view is None:
            return await reply(interaction, "There are no languages to translate to yet.")
        await interaction.response.send_message("Pick a language.", view=view, ephemeral=True)
