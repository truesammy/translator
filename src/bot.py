import asyncio
import logging
from datetime import UTC, datetime

import discord
from cryptography.fernet import InvalidToken
from discord import app_commands

from .chain import TranslatorChain, build_chain
from .commands.embed import register_embed_commands
from .commands.setup import register_setup_commands
from .config import Config
from .crypto import decrypt
from .db import Store
from .discord_io import DiscordPoster, snapshot
from .models import SourceMessage
from .reconcile import prune, reconcile
from .relay import Relay

log = logging.getLogger(__name__)

RELAYED_TYPES = (
    discord.MessageType.default,
    discord.MessageType.reply,
    # what another bot posts as the answer to one of its slash or context-menu commands
    discord.MessageType.chat_input_command,
    discord.MessageType.context_menu_command,
)


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
        self._catch_up: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        self.store = await Store.open(self.config.db_path)
        self.poster = DiscordPoster(self, self.store)
        self.relay = Relay(self.store, self.poster, self.chain_for)
        register_setup_commands(self)
        register_embed_commands(self)
        await self.tree.sync()

    async def close(self) -> None:
        if self._catch_up:
            self._catch_up.cancel()
        await super().close()
        if getattr(self, "poster", None):
            await self.poster.close()
        if getattr(self, "store", None):
            await self.store.close()

    async def chain_for(self, guild_id: int) -> TranslatorChain:
        encrypted = await self.store.get_deepl_key(guild_id)
        key = None
        if encrypted:
            try:
                key = decrypt(self.config.fernet_key, encrypted)
            except InvalidToken:  # ENCRYPTION_KEY changed: translate without the key rather than not at all
                log.warning("The DeepL key of server %s cannot be decrypted, using Google Translate", guild_id)
        return build_chain(key)

    async def on_ready(self) -> None:
        log.info("Logged in as %s on %d server(s)", self.user, len(self.guilds))
        self.start_catch_up()

    def start_catch_up(self) -> None:
        """Runs after every (re)connect, because events are lost while disconnected."""
        if self._catch_up is None or self._catch_up.done():
            self._catch_up = asyncio.create_task(self._run_catch_up())

    async def _run_catch_up(self) -> None:
        try:
            await prune(self.store, self.relay, self._guild_exists, self._channel_exists)
            await reconcile(self.store, self.relay, self._fetch_history, datetime.now(UTC))
        except Exception:
            log.exception("Catch-up failed")

    async def _guild_exists(self, guild_id: int) -> bool:
        if self.get_guild(guild_id):
            return True
        try:
            await self.fetch_guild(guild_id)
        except (discord.NotFound, discord.Forbidden):
            return False  # proof that the bot is no longer a member
        except discord.HTTPException:
            pass  # an outage proves nothing
        return True

    async def _channel_exists(self, channel_id: int) -> bool:
        if self.get_channel(channel_id):
            return True
        try:
            await self.fetch_channel(channel_id)
        except discord.NotFound:
            return False
        except discord.HTTPException:
            pass
        return True

    async def _fetch_history(self, channel_id: int, after_id: int) -> list[SourceMessage] | None:
        channel = self.get_channel(channel_id)
        # Without this permission Discord answers with an empty list, which would look like
        # every message was deleted.
        if channel is None or not channel.permissions_for(channel.guild.me).read_message_history:
            return None
        own = await self.store.own_webhook_ids()
        try:
            return [
                snapshot(message, own_webhook_ids=own)
                async for message in channel.history(after=discord.Object(after_id), oldest_first=True, limit=None)
                if message.type in RELAYED_TYPES
            ]
        except (discord.Forbidden, discord.NotFound):
            return None

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
