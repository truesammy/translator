import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from ..chain import AllProvidersFailed
from ..discord_io import button_view, data_to_embed, snapshot
from ..flags import FLAG_TEMPLATE, TRANSLATE_TEMPLATE, flag_id, pick_language, translate_id
from ..languages import get_language, language_name
from .setup import ADMIN_ONLY, language_choices

if TYPE_CHECKING:
    from ..bot import TranslatorBot

log = logging.getLogger(__name__)

MAX_FLAGS = 25  # buttons Discord allows on one message


async def translate_for_presser(interaction: discord.Interaction, channel_id: int, message_id: int) -> None:
    """Answer in the language of the presser's role, or let them pick one with flags."""
    bot: "TranslatorBot" = interaction.client
    languages = await bot.store.flag_languages(interaction.guild_id)
    code = pick_language(languages, {role.id for role in interaction.user.roles})
    if code is not None:
        return await send_translation(interaction, channel_id, message_id, code)
    view = button_view(tuple(flag_id(channel_id, message_id, code) for code, _ in languages))
    if view is None:
        return await interaction.response.send_message("There are no languages to translate to yet.", ephemeral=True)
    await interaction.response.send_message("Pick a language.", view=view, ephemeral=True)


async def send_translation(interaction: discord.Interaction, channel_id: int, message_id: int, code: str) -> None:
    async def answer(text: str) -> None:
        await interaction.followup.send(text, ephemeral=True)

    await interaction.response.defer(ephemeral=True, thinking=True)
    bot: "TranslatorBot" = interaction.client
    channel = bot.get_channel(channel_id)
    # The original may sit in a channel the presser cannot see, but never in another server.
    if channel is None or channel.guild.id != interaction.guild_id:
        return await answer("This message is no longer available.")
    try:
        message = await channel.fetch_message(message_id)
    except discord.HTTPException:
        return await answer("This message is no longer available.")
    try:
        parts = await bot.relay.private_translation(snapshot(message, own_webhook_ids=set()), code)
    except AllProvidersFailed as error:
        log.warning("Private translation of %s to %s failed: %s", message_id, code, error)
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


# Both buttons answer presses also on messages posted before a restart.
class TranslateButton(discord.ui.DynamicItem[discord.ui.Button], template=TRANSLATE_TEMPLATE):
    def __init__(self, channel_id: int, message_id: int):
        super().__init__(discord.ui.Button(custom_id=translate_id(channel_id, message_id)))
        self.channel_id, self.message_id = channel_id, message_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match):
        return cls(int(match["channel"]), int(match["message"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await translate_for_presser(interaction, self.channel_id, self.message_id)


class FlagButton(discord.ui.DynamicItem[discord.ui.Button], template=FLAG_TEMPLATE):
    def __init__(self, channel_id: int, message_id: int, code: str):
        super().__init__(discord.ui.Button(custom_id=flag_id(channel_id, message_id, code)))
        self.channel_id, self.message_id, self.code = channel_id, message_id, code

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match):
        return cls(int(match["channel"]), int(match["message"]), match["code"])

    async def callback(self, interaction: discord.Interaction) -> None:
        await send_translation(interaction, self.channel_id, self.message_id, self.code)


def format_flag_languages(languages: list[tuple[str, int | None]]) -> str:
    if not languages:
        return "No languages yet."
    return "\n".join(
        f"{language_name(code)} → <@&{role_id}>" if role_id else language_name(code) for code, role_id in languages
    )


def register_flag_commands(bot: "TranslatorBot") -> None:
    bot.add_dynamic_items(TranslateButton, FlagButton)

    async def reply(interaction: discord.Interaction, text: str) -> None:
        await interaction.response.send_message(text, ephemeral=True)

    async def show(interaction: discord.Interaction) -> None:
        await reply(interaction, format_flag_languages(await bot.store.flag_languages(interaction.guild_id)))

    async def language_autocomplete(interaction: discord.Interaction, current: str):
        return [app_commands.Choice(name=name, value=value) for name, value in language_choices(current)]

    flags = app_commands.Group(
        name="flags", description="Manage the languages of the Translate button", guild_only=True,
        default_permissions=ADMIN_ONLY,
    )

    @flags.command(name="add", description="Offer a language, translated for everyone with its role")
    @app_commands.describe(language="Language to offer", role="Role of the people who read this language")
    @app_commands.autocomplete(language=language_autocomplete)
    async def flags_add(interaction: discord.Interaction, language: str, role: discord.Role | None = None) -> None:
        if get_language(language) is None:
            return await reply(interaction, "Unknown language. Pick one from the list.")
        codes = [code for code, _ in await bot.store.flag_languages(interaction.guild_id)]
        if language not in codes and len(codes) >= MAX_FLAGS:
            return await reply(interaction, f"At most {MAX_FLAGS} languages fit on the buttons.")
        await bot.store.add_flag_language(interaction.guild_id, language, role.id if role else None)
        await show(interaction)

    @flags.command(name="remove", description="Stop offering a language")
    @app_commands.describe(language="Language to remove")
    @app_commands.autocomplete(language=language_autocomplete)
    async def flags_remove(interaction: discord.Interaction, language: str) -> None:
        if not await bot.store.remove_flag_language(interaction.guild_id, language):
            return await reply(interaction, "That language is not offered.")
        await show(interaction)

    @flags.command(name="list", description="Show the offered languages and their roles")
    async def flags_list(interaction: discord.Interaction) -> None:
        await show(interaction)

    bot.tree.add_command(flags)

    @bot.tree.context_menu(name="Add translate button")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def add_button(interaction: discord.Interaction, message: discord.Message) -> None:
        view = button_view((translate_id(message.channel.id, message.id),))
        try:
            sent = await message.reply(view=view, mention_author=False)
        except discord.HTTPException as error:
            return await reply(interaction, f"Could not reply there: {error.text or error.status}")
        await bot.store.add_flag_reply(interaction.guild_id, message.id, message.channel.id, sent.id)
        await reply(interaction, "Translate button added.")

    # Admin-only at first; admins open it to everyone in Server Settings → Integrations.
    @bot.tree.context_menu(name="Translate")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def translate(interaction: discord.Interaction, message: discord.Message) -> None:
        await translate_for_presser(interaction, message.channel.id, message.id)
