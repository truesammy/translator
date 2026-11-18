import asyncio
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from ..crypto import decrypt, encrypt
from ..languages import ORIGINAL, get_language, language_name, search_languages
from ..models import Link
from ..providers.deepl_official import DeepLOfficial
from ..splitting import truncate

if TYPE_CHECKING:
    from ..bot import TranslatorBot

ADMIN_ONLY = discord.Permissions(manage_guild=True)
TARGET_PERMISSIONS = {
    "view_channel": "View Channel",
    "send_messages": "Send Messages",
    "manage_webhooks": "Manage Webhooks",
    "manage_messages": "Manage Messages",  # to delete translations, also those of an earlier webhook
    "embed_links": "Embed Links",
    "attach_files": "Attach Files",
}
AUTO = ("Detect automatically", "auto")
ORIGINAL_CHOICE = ("Original (no translation)", ORIGINAL)

_background: set[asyncio.Task] = set()  # keeps running cleanups from being garbage collected


def missing_target_permissions(perms: discord.Permissions) -> list[str]:
    return [label for name, label in TARGET_PERMISSIONS.items() if not getattr(perms, name)]


def language_choices(current: str, *, with_auto: bool = False, with_original: bool = False) -> list[tuple[str, str]]:
    """(label, value) pairs for autocomplete, at most 25 as Discord allows."""
    choices = [(f"{lang.name} ({lang.code})", lang.code) for lang in search_languages(current)]
    for wanted, extra in ((with_auto, AUTO), (with_original, ORIGINAL_CHOICE)):
        if wanted and current.strip().lower() in f"{extra[0]} {extra[1]}".lower():
            choices.insert(0, extra)
    return choices[:25]


def format_links(links: list[Link], source_languages: dict[int, str | None]) -> str:
    if not links:
        return "No links yet."
    blocks = []
    for source_id in sorted({link.source_channel_id for link in links}):
        code = source_languages.get(source_id)
        lines = [f"<#{source_id}> (source language: {get_language(code).name if code else 'auto'})"]
        for link in sorted(links, key=lambda link: link.target_channel_id):
            if link.source_channel_id == source_id:
                ping = f", pings <@&{link.role_id}>" if link.role_id else ""
                lines.append(f"→ <#{link.target_channel_id}> {language_name(link.language)}{ping}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


class KeyModal(discord.ui.Modal, title="DeepL API key"):
    key = discord.ui.TextInput(label="DeepL API key", max_length=100)

    def __init__(self, bot: "TranslatorBot"):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        key = self.key.value.strip()
        try:
            used, limit = await DeepLOfficial(key).usage()
        except Exception:
            await interaction.followup.send("DeepL rejected that key. Nothing was saved.", ephemeral=True)
            return
        await self.bot.store.set_deepl_key(interaction.guild_id, encrypt(self.bot.config.fernet_key, key))
        self.bot.start_catch_up()  # messages that failed without a key get their translation now
        await interaction.followup.send(
            f"DeepL key saved. {used:,} of {limit:,} characters used this period.", ephemeral=True
        )


def register_setup_commands(bot: "TranslatorBot") -> None:
    async def reply(interaction: discord.Interaction, text: str) -> None:
        await interaction.response.send_message(text, ephemeral=True)

    async def language_autocomplete(interaction: discord.Interaction, current: str):
        choices = language_choices(current, with_original=True)
        return [app_commands.Choice(name=name, value=value) for name, value in choices]

    async def source_language_autocomplete(interaction: discord.Interaction, current: str):
        choices = language_choices(current, with_auto=True)
        return [app_commands.Choice(name=name, value=value) for name, value in choices]

    link = app_commands.Group(
        name="link", description="Manage translation links", guild_only=True, default_permissions=ADMIN_ONLY
    )

    @link.command(name="add", description="Translate a source channel into a target channel")
    @app_commands.describe(
        source="Channel to read from",
        target="Channel to post the translation in",
        language="Language of the target channel",
        role="Role to ping instead of @everyone and @here",
    )
    @app_commands.autocomplete(language=language_autocomplete)
    async def link_add(
        interaction: discord.Interaction,
        source: discord.TextChannel,
        target: discord.TextChannel,
        language: str,
        role: discord.Role | None = None,
    ) -> None:
        if language != ORIGINAL and get_language(language) is None:
            return await reply(interaction, "Unknown language. Pick one from the list.")
        if source.id == target.id:
            return await reply(interaction, "Source and target must be different channels.")
        if role is not None and role.is_default():
            return await reply(interaction, "Pick a role other than @everyone.")
        me = interaction.guild.me
        source_perms = source.permissions_for(me)
        if not (source_perms.view_channel and source_perms.read_message_history):
            return await reply(
                interaction, f"I need View Channel and Read Message History in {source.mention}."
            )
        missing = missing_target_permissions(target.permissions_for(me))
        if missing:
            return await reply(
                interaction, f"I'm missing these permissions in {target.mention}: {', '.join(missing)}."
            )
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await bot.poster.ensure_webhook(target)
        except discord.HTTPException as error:  # e.g. the channel already has the maximum number of webhooks
            await interaction.followup.send(
                f"Could not create a webhook in {target.mention}: {error.text or error.status}", ephemeral=True
            )
            return
        await bot.store.add_link(Link(interaction.guild_id, source.id, target.id, language, role.id if role else None))
        if await bot.store.get_last_seen(source.id) is None:
            # Catch-up starts here, so a message posted while the bot is offline is not missed.
            await bot.store.set_last_seen(interaction.guild_id, source.id, interaction.id)
        ping = f", pinging {role.mention}" if role else ""
        await interaction.followup.send(
            f"Linked {source.mention} → {target.mention} in {language_name(language)}{ping}.", ephemeral=True
        )

    @link.command(name="remove", description="Remove a link and delete its translations")
    @app_commands.describe(source="Source channel of the link", target="Target channel of the link")
    async def link_remove(
        interaction: discord.Interaction, source: discord.TextChannel, target: discord.TextChannel
    ) -> None:
        links = await bot.store.links_for_source(source.id)
        if not any(existing.target_channel_id == target.id for existing in links):
            return await reply(interaction, f"There is no link from {source.mention} to {target.mention}.")
        task = asyncio.create_task(bot.relay.remove_link(source.id, target.id))
        _background.add(task)
        task.add_done_callback(_background.discard)
        await reply(interaction, "Link removed. Deleting its translations, which can take a while.")

    @link.command(name="list", description="Show all links of this server")
    async def link_list(interaction: discord.Interaction) -> None:
        links = await bot.store.links_for_guild(interaction.guild_id)
        languages = {
            source_id: await bot.store.get_source_language(source_id)
            for source_id in {existing.source_channel_id for existing in links}
        }
        await reply(interaction, truncate(format_links(links, languages), 2000))

    bot.tree.add_command(link)

    @bot.tree.command(name="source-language", description="Set the language a source channel is written in")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(channel="Source channel", language="Its language, or detect automatically")
    @app_commands.autocomplete(language=source_language_autocomplete)
    async def source_language(interaction: discord.Interaction, channel: discord.TextChannel, language: str) -> None:
        if language == AUTO[1]:
            await bot.store.set_source_language(interaction.guild_id, channel.id, None)
            return await reply(interaction, f"The language of {channel.mention} is detected automatically.")
        lang = get_language(language)
        if lang is None:
            return await reply(interaction, "Unknown language. Pick one from the list.")
        await bot.store.set_source_language(interaction.guild_id, channel.id, lang.code)
        await reply(interaction, f"Messages in {channel.mention} are treated as {lang.name}.")

    apikey = app_commands.Group(
        name="apikey", description="Manage this server's DeepL API key", guild_only=True, default_permissions=ADMIN_ONLY
    )

    @apikey.command(name="set", description="Store a DeepL API key for this server")
    async def apikey_set(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(KeyModal(bot))

    @apikey.command(name="remove", description="Remove this server's DeepL API key")
    async def apikey_remove(interaction: discord.Interaction) -> None:
        await bot.store.set_deepl_key(interaction.guild_id, None)
        await reply(interaction, "DeepL key removed. Using Google Translate.")

    @apikey.command(name="status", description="Show whether a DeepL key is set and how much is used")
    async def apikey_status(interaction: discord.Interaction) -> None:
        encrypted = await bot.store.get_deepl_key(interaction.guild_id)
        if encrypted is None:
            return await reply(interaction, "No DeepL key set. Using Google Translate.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            used, limit = await DeepLOfficial(decrypt(bot.config.fernet_key, encrypted)).usage()
        except Exception:
            await interaction.followup.send("DeepL key set, but DeepL does not accept it right now.", ephemeral=True)
            return
        await interaction.followup.send(
            f"DeepL key set. {used:,} of {limit:,} characters used this period.", ephemeral=True
        )

    bot.tree.add_command(apikey)
