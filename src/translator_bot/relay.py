import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Protocol

from .chain import AllProvidersFailed, TranslatorChain
from .db import Store
from .languages import get_language
from .models import Link, OutgoingPart, SourceMessage
from .render import content_hash, render

log = logging.getLogger(__name__)


class MessageGone(Exception):
    """Poster.edit raises this when the message cannot be edited any more: it was deleted
    by hand, or it belongs to a webhook that no longer exists."""


class Poster(Protocol):
    async def send(self, channel_id: int, author_name: str, avatar_url: str | None, part: OutgoingPart) -> int: ...

    async def edit(self, channel_id: int, message_id: int, part: OutgoingPart) -> None: ...

    async def delete(self, channel_id: int, message_id: int) -> None: ...

    async def mark_failed(self, msg: SourceMessage) -> None: ...


class Relay:
    """Keeps the translations of every source message in step with the original."""

    def __init__(self, store: Store, poster: Poster, chain_for: Callable[[int], Awaitable[TranslatorChain]]):
        self._store = store
        self._poster = poster
        self._chain_for = chain_for
        self._locks: dict[int, tuple[asyncio.Lock, int]] = {}

    @asynccontextmanager
    async def _locked(self, msg_id: int):
        # One lock per source message, so create, edit and delete never interleave.
        lock, users = self._locks.get(msg_id, (asyncio.Lock(), 0))
        self._locks[msg_id] = (lock, users + 1)
        try:
            async with lock:
                yield
        finally:
            lock, users = self._locks[msg_id]
            if users == 1:
                del self._locks[msg_id]
            else:
                self._locks[msg_id] = (lock, users - 1)

    async def handle_create(self, msg: SourceMessage) -> None:
        async with self._locked(msg.id):
            links = await self._store.links_for_source(msg.channel_id)
            if not links or await self._store.get_source_hash(msg.id) is not None:
                return
            await self._store.record_source(msg.id, msg.guild_id, msg.channel_id, content_hash(msg))
            await self._store.set_last_seen(msg.guild_id, msg.channel_id, msg.id)
            await self._sync(msg, links, notify=True)

    async def handle_edit(self, msg: SourceMessage) -> None:
        async with self._locked(msg.id):
            known = await self._store.get_source_hash(msg.id)
            new = content_hash(msg)
            if known is None or known == new:
                return
            await self._store.record_source(msg.id, msg.guild_id, msg.channel_id, new)
            await self._sync(msg, await self._store.links_for_source(msg.channel_id), notify=False)

    async def handle_delete(self, source_message_id: int) -> None:
        async with self._locked(source_message_id):
            if await self._store.get_source_hash(source_message_id) is None:
                return
            stuck = False
            for target_id, part_ids in (await self._store.all_parts(source_message_id)).items():
                left = [part_id for part_id in part_ids if not await self._delete(target_id, part_id)]
                await self._store.set_parts(source_message_id, target_id, left)
                stuck = stuck or bool(left)
            # What could not be deleted stays tracked, so the next catch-up tries again.
            if not stuck:
                await self._store.forget_source(source_message_id)

    async def remove_link(self, source_channel_id: int, target_channel_id: int, *, delete_messages: bool = True) -> None:
        # The link goes first, so nothing new is relayed while the old messages are being deleted.
        await self._store.delete_link(source_channel_id, target_channel_id)
        if delete_messages:
            for part_id in await self._store.parts_for_link(source_channel_id, target_channel_id):
                await self._delete(target_channel_id, part_id)
        await self._store.forget_link_parts(source_channel_id, target_channel_id)

    async def _delete(self, channel_id: int, message_id: int) -> bool:
        try:
            await self._poster.delete(channel_id, message_id)
            return True
        except Exception as error:
            log.warning("Could not delete message %s in channel %s: %s", message_id, channel_id, error)
            return False

    async def _sync(self, msg: SourceMessage, links: list[Link], *, notify: bool) -> None:
        chain = await self._chain_for(msg.guild_id)
        source_language = await self._store.get_source_language(msg.channel_id)
        translated = await asyncio.gather(
            *(self._sync_link(msg, link, source_language, chain, notify) for link in links)
        )
        if not all(translated):
            await self._poster.mark_failed(msg)

    async def _sync_link(
        self, msg: SourceMessage, link: Link, source_language: str | None, chain: TranslatorChain, notify: bool
    ) -> bool:
        """Bring one target channel up to date. False when no provider could translate."""
        target = link.target_channel_id
        try:
            parts = await render(msg, link, source_language, chain)
        except AllProvidersFailed as error:
            language = get_language(link.language)
            name = language.name if language else link.language
            log.warning("Translation to %s in channel %s failed: %s", name, target, error)
            return False
        except Exception as error:
            log.warning("Could not post to channel %s: %s", target, error)
            return True

        existing = await self._store.get_parts(msg.id, target)
        posted: list[int] = []
        try:
            for i, part in enumerate(parts):
                if i < len(existing):
                    try:
                        await self._poster.edit(target, existing[i], part)
                        posted.append(existing[i])
                        continue
                    except MessageGone:
                        # Replace it, or this target would never get an update again.
                        await self._delete(target, existing[i])
                part = replace(part, notify=part.notify and notify)
                posted.append(await self._poster.send(target, msg.author_name, msg.author_avatar_url, part))
            for surplus in existing[len(parts) :]:
                await self._poster.delete(target, surplus)
        except Exception as error:
            log.warning("Could not post to channel %s: %s", target, error)
            posted += existing[len(posted) :]  # keep tracking what is still there
        await self._store.set_parts(msg.id, target, posted)
        return True
