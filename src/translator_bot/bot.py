import logging

import discord
from discord import app_commands

from .chain import TranslatorChain, build_chain
from .config import Config
from .crypto import decrypt
from .db import Store
from .discord_io import DiscordPoster, snapshot
from .relay import Relay

log = logging.getLogger(__name__)

RELAYED_TYPES = (discord.MessageType.default, discord.MessageType.reply)


class TranslatorBot(discord.Client):
    store: Store
    poster: DiscordPoster
    relay: Relay

    def __init__(self, config: Config):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.config = config
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        self.store = await Store.open(self.config.db_path)
        self.poster = DiscordPoster(self, self.store)
        self.relay = Relay(self.store, self.poster, self.chain_for)
        await self.tree.sync()

    async def close(self) -> None:
        await super().close()
        if hasattr(self, "store"):
            await self.poster.close()
            await self.store.close()

    async def chain_for(self, guild_id: int) -> TranslatorChain:
        encrypted = await self.store.get_deepl_key(guild_id)
        return build_chain(decrypt(self.config.fernet_key, encrypted) if encrypted else None)

    async def on_ready(self) -> None:
        log.info("Logged in as %s on %d server(s)", self.user, len(self.guilds))

    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.type not in RELAYED_TYPES:
            return
        if await self.poster.is_own_webhook(message.webhook_id):
            return
        await self.relay.handle_create(snapshot(message, own_webhook_ids=set()))

    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        # Only tracked messages matter, which also skips our own translations without a fetch.
        if await self.store.get_source_hash(payload.message_id) is None:
            return
        channel = self.get_channel(payload.channel_id)
        if channel is None:
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.HTTPException:
            return
        await self.relay.handle_edit(snapshot(message, own_webhook_ids=set()))

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        await self.relay.handle_delete(payload.message_id)

    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent) -> None:
        for message_id in payload.message_ids:
            await self.relay.handle_delete(message_id)

    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        for link in await self.store.links_touching_channel(channel.id):
            # Translations in a deleted target are gone already; those of a deleted source are orphans.
            await self.relay.remove_link(
                link.source_channel_id,
                link.target_channel_id,
                delete_messages=link.target_channel_id != channel.id,
            )
        await self.store.delete_webhook(channel.id)

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        await self.store.delete_guild(guild.id)
