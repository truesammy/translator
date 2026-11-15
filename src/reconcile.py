"""Catch up on what happened in the source channels while the bot was offline."""

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from .db import Store
from .models import SourceMessage
from .relay import Relay

log = logging.getLogger(__name__)

WINDOW = timedelta(days=30)
_DISCORD_EPOCH_MS = 1_420_070_400_000


def snowflake_for(moment: datetime) -> int:
    """Smallest Discord id created at `moment`."""
    return (int(moment.timestamp() * 1000) - _DISCORD_EPOCH_MS) << 22


async def reconcile(
    store: Store,
    relay: Relay,
    fetch_history: Callable[[int, int], Awaitable[list[SourceMessage] | None]],
    now: datetime,
) -> None:
    """`fetch_history(channel_id, after_id)` returns the messages newer than `after_id`,
    or None when the channel cannot be read."""
    cutoff = snowflake_for(now - WINDOW)
    for channel_id in await store.source_channel_ids():
        last_seen = await store.get_last_seen(channel_id)
        # Read before fetching: a message relayed live during the fetch must not look deleted.
        tracked = await store.tracked_source_ids(channel_id, cutoff)
        try:
            messages = await fetch_history(channel_id, cutoff if last_seen is None else min(cutoff, last_seen))
        except Exception as error:
            log.warning("Could not read channel %s to catch up: %s", channel_id, error)
            continue
        if messages is None:
            continue
        for msg in messages:
            try:
                if await store.get_source_hash(msg.id) is not None:
                    await relay.handle_edit(msg)
                elif last_seen is not None and msg.id > last_seen and not msg.from_own_webhook:
                    await relay.handle_create(msg)
            except Exception as error:  # one bad message must not end the catch-up
                log.warning("Could not catch up on message %s: %s", msg.id, error)
        present = {msg.id for msg in messages}
        for msg_id in tracked:
            if msg_id not in present:
                await relay.handle_delete(msg_id)


async def prune(
    store: Store,
    relay: Relay,
    guild_exists: Callable[[int], Awaitable[bool]],
    channel_exists: Callable[[int], Awaitable[bool]],
) -> None:
    """Drop what was deleted while the bot was offline: servers it left, links of deleted channels.
    The callbacks must answer False only on proof, never on a failed request."""
    for guild_id in await store.guild_ids():
        if not await guild_exists(guild_id):
            log.info("No longer in server %s, deleting its data", guild_id)
            await store.delete_guild(guild_id)
    known: dict[int, bool] = {}

    async def exists(channel_id: int) -> bool:
        if channel_id not in known:
            known[channel_id] = await channel_exists(channel_id)
        return known[channel_id]

    for link in await store.all_links():
        if not await exists(link.source_channel_id):
            await relay.remove_link(link.source_channel_id, link.target_channel_id)
        elif not await exists(link.target_channel_id):
            await relay.remove_link(link.source_channel_id, link.target_channel_id, delete_messages=False)
