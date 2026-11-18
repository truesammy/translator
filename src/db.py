from pathlib import Path

import aiosqlite

from .models import Link

# Every table carries guild_id so delete_guild is one DELETE per table.
SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    guild_id INTEGER NOT NULL, source_id INTEGER NOT NULL, target_id INTEGER NOT NULL,
    language TEXT NOT NULL, role_id INTEGER,
    PRIMARY KEY (source_id, target_id));
CREATE TABLE IF NOT EXISTS source_channels (
    channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL,
    source_language TEXT, last_seen INTEGER);
CREATE TABLE IF NOT EXISTS guilds (
    guild_id INTEGER PRIMARY KEY, deepl_key BLOB);
CREATE TABLE IF NOT EXISTS sources (
    message_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL, content_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS parts (
    message_id INTEGER NOT NULL, guild_id INTEGER NOT NULL, source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL, part_index INTEGER NOT NULL, target_message_id INTEGER NOT NULL,
    PRIMARY KEY (message_id, target_id, part_index));
CREATE TABLE IF NOT EXISTS webhooks (
    channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL,
    webhook_id INTEGER NOT NULL, token TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS own_embeds (
    message_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL, author_id INTEGER);
CREATE TABLE IF NOT EXISTS flag_languages (
    guild_id INTEGER NOT NULL, language TEXT NOT NULL, PRIMARY KEY (guild_id, language));
CREATE TABLE IF NOT EXISTS translations (
    message_id INTEGER NOT NULL, guild_id INTEGER NOT NULL, language TEXT NOT NULL,
    content_hash TEXT NOT NULL, parts BLOB NOT NULL, PRIMARY KEY (message_id, language));
CREATE TABLE IF NOT EXISTS flag_replies (
    message_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL, reply_id INTEGER NOT NULL);
"""
TABLES = (
    "links", "source_channels", "guilds", "sources", "parts", "webhooks", "own_embeds",
    "flag_languages", "translations", "flag_replies",
)
LINK_COLUMNS = "guild_id, source_id, target_id, language, role_id"


class Store:
    def __init__(self, db: aiosqlite.Connection):
        self._db = db

    @classmethod
    async def open(cls, path: Path | str) -> "Store":
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        db = await aiosqlite.connect(path)
        await db.executescript(SCHEMA)
        # Some databases were created while this column did not exist.
        columns = await (await db.execute("PRAGMA table_info(own_embeds)")).fetchall()
        if not any(column[1] == "author_id" for column in columns):
            await db.execute("ALTER TABLE own_embeds ADD COLUMN author_id INTEGER")
        await db.commit()
        return cls(db)

    async def close(self) -> None:
        await self._db.close()

    async def _write(self, sql: str, args: tuple = ()) -> int:
        cursor = await self._db.execute(sql, args)
        await self._db.commit()
        return cursor.rowcount

    async def _rows(self, sql: str, args: tuple = ()) -> list[tuple]:
        cursor = await self._db.execute(sql, args)
        return await cursor.fetchall()

    async def _value(self, sql: str, args: tuple = ()):
        rows = await self._rows(sql, args)
        return rows[0][0] if rows else None

    # links

    async def add_link(self, link: Link) -> None:
        await self._write(
            f"INSERT INTO links ({LINK_COLUMNS}) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (source_id, target_id) DO UPDATE SET language = excluded.language, role_id = excluded.role_id",
            (link.guild_id, link.source_channel_id, link.target_channel_id, link.language, link.role_id),
        )

    async def delete_link(self, source_id: int, target_id: int) -> bool:
        return await self._write("DELETE FROM links WHERE source_id = ? AND target_id = ?", (source_id, target_id)) > 0

    async def _links(self, where: str, args: tuple) -> list[Link]:
        rows = await self._rows(f"SELECT {LINK_COLUMNS} FROM links WHERE {where} ORDER BY source_id, target_id", args)
        return [Link(*row) for row in rows]

    async def links_for_source(self, source_id: int) -> list[Link]:
        return await self._links("source_id = ?", (source_id,))

    async def links_for_guild(self, guild_id: int) -> list[Link]:
        return await self._links("guild_id = ?", (guild_id,))

    async def links_touching_channel(self, channel_id: int) -> list[Link]:
        return await self._links("source_id = ? OR target_id = ?", (channel_id, channel_id))

    async def all_links(self) -> list[Link]:
        return await self._links("1 = 1", ())

    async def guild_ids(self) -> list[int]:
        """Every server that has any data here."""
        union = " UNION ".join(f"SELECT guild_id FROM {table}" for table in TABLES)
        return [row[0] for row in await self._rows(f"{union} ORDER BY guild_id")]

    async def source_channel_ids(self) -> list[int]:
        return [row[0] for row in await self._rows("SELECT DISTINCT source_id FROM links ORDER BY source_id")]

    # per source channel

    async def get_source_language(self, source_id: int) -> str | None:
        return await self._value("SELECT source_language FROM source_channels WHERE channel_id = ?", (source_id,))

    async def set_source_language(self, guild_id: int, source_id: int, code: str | None) -> None:
        await self._write(
            "INSERT INTO source_channels (channel_id, guild_id, source_language) VALUES (?, ?, ?) "
            "ON CONFLICT (channel_id) DO UPDATE SET source_language = excluded.source_language",
            (source_id, guild_id, code),
        )

    async def get_last_seen(self, source_id: int) -> int | None:
        return await self._value("SELECT last_seen FROM source_channels WHERE channel_id = ?", (source_id,))

    async def set_last_seen(self, guild_id: int, source_id: int, message_id: int) -> None:
        await self._write(
            "INSERT INTO source_channels (channel_id, guild_id, last_seen) VALUES (?, ?, ?) "
            "ON CONFLICT (channel_id) DO UPDATE SET last_seen = MAX(COALESCE(last_seen, 0), excluded.last_seen)",
            (source_id, guild_id, message_id),
        )

    # per guild

    async def set_deepl_key(self, guild_id: int, encrypted: bytes | None) -> None:
        await self._write(
            "INSERT INTO guilds (guild_id, deepl_key) VALUES (?, ?) "
            "ON CONFLICT (guild_id) DO UPDATE SET deepl_key = excluded.deepl_key",
            (guild_id, encrypted),
        )

    async def get_deepl_key(self, guild_id: int) -> bytes | None:
        return await self._value("SELECT deepl_key FROM guilds WHERE guild_id = ?", (guild_id,))

    async def delete_guild(self, guild_id: int) -> None:
        for table in TABLES:
            await self._db.execute(f"DELETE FROM {table} WHERE guild_id = ?", (guild_id,))
        await self._db.commit()

    # relayed messages

    async def record_source(self, msg_id: int, guild_id: int, channel_id: int, content_hash: str) -> None:
        await self._write(
            "INSERT INTO sources (message_id, guild_id, channel_id, content_hash) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (message_id) DO UPDATE SET content_hash = excluded.content_hash",
            (msg_id, guild_id, channel_id, content_hash),
        )

    async def get_source_hash(self, msg_id: int) -> str | None:
        return await self._value("SELECT content_hash FROM sources WHERE message_id = ?", (msg_id,))

    async def tracked_source_ids(self, channel_id: int, min_id: int) -> list[int]:
        rows = await self._rows(
            "SELECT message_id FROM sources WHERE channel_id = ? AND message_id >= ? ORDER BY message_id",
            (channel_id, min_id),
        )
        return [row[0] for row in rows]

    async def set_parts(self, msg_id: int, target_id: int, target_message_ids: list[int]) -> None:
        await self._db.execute("DELETE FROM parts WHERE message_id = ? AND target_id = ?", (msg_id, target_id))
        await self._db.executemany(
            "INSERT INTO parts (message_id, guild_id, source_id, target_id, part_index, target_message_id) "
            "SELECT message_id, guild_id, channel_id, ?, ?, ? FROM sources WHERE message_id = ?",
            [(target_id, index, part_id, msg_id) for index, part_id in enumerate(target_message_ids)],
        )
        await self._db.commit()

    async def get_parts(self, msg_id: int, target_id: int) -> list[int]:
        rows = await self._rows(
            "SELECT target_message_id FROM parts WHERE message_id = ? AND target_id = ? ORDER BY part_index",
            (msg_id, target_id),
        )
        return [row[0] for row in rows]

    async def all_parts(self, msg_id: int) -> dict[int, list[int]]:
        rows = await self._rows(
            "SELECT target_id, target_message_id FROM parts WHERE message_id = ? ORDER BY target_id, part_index",
            (msg_id,),
        )
        result: dict[int, list[int]] = {}
        for target_id, part_id in rows:
            result.setdefault(target_id, []).append(part_id)
        return result

    async def parts_for_link(self, source_id: int, target_id: int) -> list[int]:
        rows = await self._rows(
            "SELECT target_message_id FROM parts WHERE source_id = ? AND target_id = ?", (source_id, target_id)
        )
        return [row[0] for row in rows]

    async def forget_source(self, msg_id: int) -> None:
        await self._db.execute("DELETE FROM parts WHERE message_id = ?", (msg_id,))
        await self._write("DELETE FROM sources WHERE message_id = ?", (msg_id,))

    async def forget_link_parts(self, source_id: int, target_id: int) -> None:
        await self._write("DELETE FROM parts WHERE source_id = ? AND target_id = ?", (source_id, target_id))

    # webhooks

    async def get_webhook(self, channel_id: int) -> tuple[int, str] | None:
        rows = await self._rows("SELECT webhook_id, token FROM webhooks WHERE channel_id = ?", (channel_id,))
        return rows[0] if rows else None

    async def set_webhook(self, guild_id: int, channel_id: int, webhook_id: int, token: str) -> None:
        await self._write(
            "INSERT OR REPLACE INTO webhooks (channel_id, guild_id, webhook_id, token) VALUES (?, ?, ?, ?)",
            (channel_id, guild_id, webhook_id, token),
        )

    async def delete_webhook(self, channel_id: int) -> None:
        await self._write("DELETE FROM webhooks WHERE channel_id = ?", (channel_id,))

    async def own_webhook_ids(self) -> set[int]:
        return {row[0] for row in await self._rows("SELECT webhook_id FROM webhooks")}

    # embeds created with /embed

    async def record_own_embed(self, msg_id: int, guild_id: int, channel_id: int, author_id: int) -> None:
        await self._write(
            "INSERT OR REPLACE INTO own_embeds (message_id, guild_id, channel_id, author_id) VALUES (?, ?, ?, ?)",
            (msg_id, guild_id, channel_id, author_id),
        )

    async def get_own_embed(self, msg_id: int) -> tuple[int, int | None] | None:
        """(channel, who created it) of an embed made with /embed create. The creator of old embeds is unknown."""
        rows = await self._rows("SELECT channel_id, author_id FROM own_embeds WHERE message_id = ?", (msg_id,))
        return rows[0] if rows else None

    # private translations behind flag buttons

    async def add_flag_language(self, guild_id: int, code: str) -> None:
        await self._write("INSERT OR IGNORE INTO flag_languages (guild_id, language) VALUES (?, ?)", (guild_id, code))

    async def remove_flag_language(self, guild_id: int, code: str) -> bool:
        sql = "DELETE FROM flag_languages WHERE guild_id = ? AND language = ?"
        return await self._write(sql, (guild_id, code)) > 0

    async def flag_languages(self, guild_id: int) -> list[str]:
        rows = await self._rows("SELECT language FROM flag_languages WHERE guild_id = ? ORDER BY language", (guild_id,))
        return [row[0] for row in rows]

    async def get_translation(self, msg_id: int, language: str, content_hash: str) -> bytes | None:
        return await self._value(
            "SELECT parts FROM translations WHERE message_id = ? AND language = ? AND content_hash = ?",
            (msg_id, language, content_hash),
        )

    async def set_translation(self, msg_id: int, guild_id: int, language: str, content_hash: str, parts: bytes) -> None:
        await self._write(
            "INSERT OR REPLACE INTO translations (message_id, guild_id, language, content_hash, parts) "
            "VALUES (?, ?, ?, ?, ?)",
            (msg_id, guild_id, language, content_hash, parts),
        )

    async def add_flag_reply(self, guild_id: int, msg_id: int, channel_id: int, reply_id: int) -> None:
        await self._write(
            "INSERT OR REPLACE INTO flag_replies (message_id, guild_id, channel_id, reply_id) VALUES (?, ?, ?, ?)",
            (msg_id, guild_id, channel_id, reply_id),
        )

    async def forget_private(self, msg_id: int) -> list[tuple[int, int]]:
        """Drop a message's stored translations and flag reply. Returns (channel, reply) of the reply."""
        replies = await self._rows("SELECT channel_id, reply_id FROM flag_replies WHERE message_id = ?", (msg_id,))
        await self._db.execute("DELETE FROM translations WHERE message_id = ?", (msg_id,))
        await self._write("DELETE FROM flag_replies WHERE message_id = ?", (msg_id,))
        return [tuple(row) for row in replies]
