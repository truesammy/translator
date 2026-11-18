"""The only place that turns Discord objects into our models and back."""

import io
import re

import aiohttp
import discord

from .db import Store
from .flags import button_look
from .models import Attachment, EmbedData, EmbedField, OutgoingPart, SourceMessage
from .relay import MessageGone

WEBHOOK_NAME = "Translator"
_RESERVED = re.compile(r"discord|clyde|^everyone$|^here$", re.IGNORECASE)


def sanitize_username(name: str) -> str:
    """Discord rejects webhook names that are empty, too long, contain "discord" or "clyde",
    or are exactly "everyone" or "here"."""
    broken = _RESERVED.sub(lambda match: match.group(0)[0] + "​" + match.group(0)[1:], name.strip())
    return broken[:80].strip() or "Unknown"


def embed_to_data(embed: discord.Embed) -> EmbedData:
    return EmbedData(
        title=embed.title,
        description=embed.description,
        url=embed.url,
        color=embed.color.value if embed.color else None,
        timestamp=embed.timestamp,
        footer_text=embed.footer.text,
        footer_icon_url=embed.footer.icon_url,
        author_name=embed.author.name,
        author_url=embed.author.url,
        author_icon_url=embed.author.icon_url,
        image_url=embed.image.url,
        thumbnail_url=embed.thumbnail.url,
        fields=tuple(EmbedField(field.name, field.value, bool(field.inline)) for field in embed.fields),
    )


def data_to_embed(data: EmbedData) -> discord.Embed:
    embed = discord.Embed(
        title=data.title, description=data.description, url=data.url, color=data.color, timestamp=data.timestamp
    )
    if data.footer_text or data.footer_icon_url:
        embed.set_footer(text=data.footer_text, icon_url=data.footer_icon_url)
    if data.author_name:
        embed.set_author(name=data.author_name, url=data.author_url, icon_url=data.author_icon_url)
    if data.image_url:
        embed.set_image(url=data.image_url)
    if data.thumbnail_url:
        embed.set_thumbnail(url=data.thumbnail_url)
    for field in data.fields:
        embed.add_field(name=field.name, value=field.value, inline=field.inline)
    return embed


def button_view(custom_ids: tuple[str, ...]) -> discord.ui.View | None:
    if not custom_ids:
        return None
    view = discord.ui.View(timeout=None)
    for custom_id in custom_ids:
        emoji, label = button_look(custom_id)
        view.add_item(discord.ui.Button(custom_id=custom_id, emoji=emoji, label=label))
    # TranslateButton and FlagButton answer the presses. A running view would be kept in memory for every message it is sent with.
    view.stop()
    return view


def snapshot(message: discord.Message, *, own_webhook_ids: set[int]) -> SourceMessage:
    return SourceMessage(
        id=message.id,
        guild_id=message.guild.id,
        channel_id=message.channel.id,
        author_name=message.author.display_name,
        author_avatar_url=message.author.display_avatar.url,
        content=message.content,
        embeds=tuple(embed_to_data(embed) for embed in message.embeds if _is_real_embed(embed, message)),
        attachments=tuple(Attachment(a.filename, a.url, a.size) for a in message.attachments),
        from_own_webhook=message.webhook_id in own_webhook_ids,
        mention_everyone=message.mention_everyone,
        role_mention_ids=tuple(role.id for role in message.role_mentions),
        user_mention_ids=tuple(user.id for user in message.mentions),
    )


def _is_real_embed(embed: discord.Embed, message: discord.Message) -> bool:
    """Link previews are left out: Discord builds them again in the target channel.
    Only bots and webhooks can send embeds, so anything on a person's message is a preview,
    and so is a bot's embed whose url is a link in the text. Some previews have type "rich"."""
    if embed.type != "rich" or not message.author.bot:
        return False
    return not (embed.url and embed.url in message.content)


class DiscordPoster:
    """Posts through one webhook per channel, so translations can carry the author's name and avatar."""

    def __init__(self, client: discord.Client, store: Store):
        self._client = client
        self._store = store
        self._session: aiohttp.ClientSession | None = None

    async def close(self) -> None:
        if self._session:
            await self._session.close()

    async def is_own_webhook(self, webhook_id: int | None) -> bool:
        return webhook_id is not None and webhook_id in await self._store.own_webhook_ids()

    def _channel(self, channel_id: int) -> discord.TextChannel:
        channel = self._client.get_channel(channel_id)
        if channel is None:
            raise RuntimeError(f"channel {channel_id} not found")
        return channel

    async def ensure_webhook(self, channel: discord.TextChannel) -> discord.Webhook:
        stored = await self._store.get_webhook(channel.id)
        if stored:
            return discord.Webhook.partial(stored[0], stored[1], client=self._client)
        webhook = await channel.create_webhook(name=WEBHOOK_NAME)
        await self._store.set_webhook(channel.guild.id, channel.id, webhook.id, webhook.token)
        return webhook

    async def _download(self, url: str) -> bytes | None:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        try:
            async with self._session.get(url) as response:
                return await response.read() if response.status == 200 else None
        except aiohttp.ClientError:
            return None

    async def _content_and_files(
        self, part: OutgoingPart, channel: discord.TextChannel, *, upload: bool
    ) -> tuple[str, list[discord.File]]:
        """Attachments are uploaded again; ones that are too large, or fail to download, become links."""
        # shortcut: links can push the content past 2000 characters, split again if that ever happens
        lines, files = [part.content], []
        for attachment in part.attachments:
            if attachment.size > channel.guild.filesize_limit:
                lines.append(attachment.url)
            elif upload:
                data = await self._download(attachment.url)
                if data is None:
                    lines.append(attachment.url)
                else:
                    files.append(discord.File(io.BytesIO(data), filename=attachment.filename))
        return "\n".join(lines).strip(), files

    async def send(self, channel_id: int, author_name: str, avatar_url: str | None, part: OutgoingPart) -> int:
        channel = self._channel(channel_id)
        for attempt in (1, 2):
            webhook = await self.ensure_webhook(channel)
            content, files = await self._content_and_files(part, channel, upload=True)
            options = {"avatar_url": avatar_url} if avatar_url else {}
            if part.buttons:
                options["view"] = button_view(part.buttons)
            try:
                message = await webhook.send(
                    content,
                    username=sanitize_username(author_name),
                    embeds=[data_to_embed(embed) for embed in part.embeds],
                    files=files,
                    allowed_mentions=discord.AllowedMentions(
                        everyone=False,
                        users=[discord.Object(user_id) for user_id in part.ping_users] if part.notify else False,
                        roles=[discord.Object(role_id) for role_id in part.ping_roles] if part.notify else False,
                    ),
                    wait=True,
                    **options,
                )
                return message.id
            except discord.NotFound:
                # Someone deleted our webhook: forget it and make a new one, once.
                await self._store.delete_webhook(channel_id)
                if attempt == 2:
                    raise

    async def edit(self, channel_id: int, message_id: int, part: OutgoingPart) -> None:
        channel = self._channel(channel_id)
        webhook = await self.ensure_webhook(channel)
        content, _ = await self._content_and_files(part, channel, upload=False)
        try:
            await webhook.edit_message(
                message_id,
                content=content,
                embeds=[data_to_embed(embed) for embed in part.embeds],
                allowed_mentions=discord.AllowedMentions.none(),
                view=button_view(part.buttons),
            )
        except discord.NotFound:
            # Deleted by hand, or posted by an earlier webhook that was removed.
            raise MessageGone() from None

    async def delete(self, channel_id: int, message_id: int) -> None:
        channel = self._client.get_channel(channel_id)
        if channel is None:
            return
        # As the bot, not through the webhook: a webhook can only delete its own messages,
        # so translations of a replaced webhook would stay behind for good.
        try:
            await channel.get_partial_message(message_id).delete()
        except discord.NotFound:
            pass

    async def mark_failed(self, msg: SourceMessage) -> None:
        channel = self._client.get_channel(msg.channel_id)
        if channel is None:
            return
        try:
            await channel.get_partial_message(msg.id).add_reaction("⚠️")
        except discord.HTTPException:
            pass
