import re
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from ..discord_io import data_to_embed, embed_to_data, sanitize_username, snapshot
from ..models import EmbedData

if TYPE_CHECKING:
    from ..bot import TranslatorBot

ADMIN_ONLY = discord.Permissions(manage_guild=True)


class EmbedInputError(ValueError):
    """Its message is shown to the admin as is."""


def parse_color(text: str) -> int | None:
    text = text.strip()
    if not text:
        return None
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", text)
    if not match:
        raise EmbedInputError("Color must be a hex code like #5865F2.")
    return int(match.group(1), 16)


def format_color(color: int | None) -> str:
    return "" if color is None else f"#{color:06X}"


def parse_image_url(text: str) -> str | None:
    text = text.strip()
    if not text:
        return None
    if not re.match(r"https?://\S+$", text):
        raise EmbedInputError("Image URL must start with http:// or https://.")
    return text


def parse_message_ref(text: str) -> int:
    match = re.search(r"(\d+)$", text.strip())
    if not match:
        raise EmbedInputError("Give a message ID or a message link.")
    return int(match.group(1))


def build_embed(title: str, description: str, color: str, image_url: str, footer: str) -> EmbedData:
    if not description.strip():
        raise EmbedInputError("The text must not be empty.")
    return EmbedData(
        title=title.strip() or None,
        description=description.strip(),
        color=parse_color(color),
        image_url=parse_image_url(image_url),
        footer_text=footer.strip() or None,
    )


class EmbedModal(discord.ui.Modal):
    def __init__(
        self,
        heading: str,
        on_valid: Callable[[discord.Interaction, EmbedData], Awaitable[None]],
        current: EmbedData = EmbedData(),
    ):
        super().__init__(title=heading)
        self._on_valid = on_valid
        self._current = current
        text = discord.ui.TextInput
        self.title_input = text(label="Title", required=False, max_length=256, default=current.title)
        self.text_input = text(
            label="Text", style=discord.TextStyle.paragraph, max_length=4000, default=current.description
        )
        self.color_input = text(
            label="Color", required=False, max_length=7, placeholder="#5865F2", default=format_color(current.color)
        )
        self.image_input = text(label="Image URL", required=False, max_length=500, default=current.image_url)
        self.footer_input = text(label="Footer", required=False, max_length=2048, default=current.footer_text)
        for item in (self.title_input, self.text_input, self.color_input, self.image_input, self.footer_input):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            new = build_embed(
                self.title_input.value,
                self.text_input.value,
                self.color_input.value,
                self.image_input.value,
                self.footer_input.value,
            )
        except EmbedInputError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        # Only the five form fields change; anything else on the embed stays.
        await self._on_valid(
            interaction,
            replace(
                self._current,
                title=new.title,
                description=new.description,
                color=new.color,
                image_url=new.image_url,
                footer_text=new.footer_text,
            ),
        )


def register_embed_commands(bot: "TranslatorBot") -> None:
    embed = app_commands.Group(
        name="embed", description="Post and edit translated embeds", guild_only=True, default_permissions=ADMIN_ONLY
    )

    @embed.command(name="create", description="Post an embed in a source channel and translate it")
    @app_commands.describe(channel="Source channel to post in")
    async def embed_create(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if not await bot.store.links_for_source(channel.id):
            await interaction.response.send_message(
                "That channel has no links. Add one with /link add first.", ephemeral=True
            )
            return

        async def post(submitted: discord.Interaction, data: EmbedData) -> None:
            name, avatar = submitted.user.display_name, submitted.user.display_avatar.url
            webhook = await bot.poster.ensure_webhook(channel)
            sent = await webhook.send(
                embed=data_to_embed(data), username=sanitize_username(name), avatar_url=avatar, wait=True
            )
            await bot.store.record_own_embed(sent.id, submitted.guild_id, channel.id, submitted.user.id)
            # Read it back so the stored hash matches what later edit events and catch-up will see.
            message = await channel.fetch_message(sent.id)
            source = replace(snapshot(message, own_webhook_ids=set()), author_name=name, author_avatar_url=avatar)
            await bot.relay.handle_create(source)
            await submitted.followup.send(f"Embed posted in {channel.mention}.", ephemeral=True)

        await interaction.response.send_modal(EmbedModal("New embed", post))

    @embed.command(name="edit", description="Edit an embed that was created with /embed create")
    @app_commands.describe(message="Message ID or message link of the embed")
    async def embed_edit(interaction: discord.Interaction, message: str) -> None:
        async def refuse(text: str) -> None:
            await interaction.response.send_message(text, ephemeral=True)

        try:
            message_id = parse_message_ref(message)
        except EmbedInputError as error:
            return await refuse(str(error))
        own = await bot.store.get_own_embed(message_id)
        channel = interaction.guild.get_channel(own[0]) if own else None
        if channel is None:
            return await refuse("That message was not created with /embed.")
        try:
            original = await channel.fetch_message(message_id)
        except discord.HTTPException:
            return await refuse("That message no longer exists.")
        if not original.embeds:
            return await refuse("That message has no embed any more.")

        async def save(submitted: discord.Interaction, data: EmbedData) -> None:
            webhook = await bot.poster.ensure_webhook(channel)
            await webhook.edit_message(message_id, embed=data_to_embed(data))
            edited = await channel.fetch_message(message_id)
            await bot.relay.handle_edit(snapshot(edited, own_webhook_ids=set()))
            await submitted.followup.send("Embed updated.", ephemeral=True)

        await interaction.response.send_modal(EmbedModal("Edit embed", save, embed_to_data(original.embeds[0])))

    bot.tree.add_command(embed)
