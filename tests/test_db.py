import aiosqlite
import pytest

from translator_bot.db import Store
from translator_bot.models import Link


@pytest.fixture
async def store():
    s = await Store.open(":memory:")
    yield s
    await s.close()


async def test_link_round_trip(store):
    await store.add_link(Link(1, 100, 201, "de", None))
    await store.add_link(Link(1, 100, 202, "fr", 5))
    assert await store.links_for_source(100) == [Link(1, 100, 201, "de", None), Link(1, 100, 202, "fr", 5)]
    assert await store.links_for_guild(1) == await store.links_for_source(100)
    assert await store.source_channel_ids() == [100]
    assert await store.delete_link(100, 201) is True
    assert await store.delete_link(100, 201) is False


async def test_add_link_twice_updates_language_and_role(store):
    await store.add_link(Link(1, 100, 201, "de", None))
    await store.add_link(Link(1, 100, 201, "fr", 7))
    assert await store.links_for_source(100) == [Link(1, 100, 201, "fr", 7)]


async def test_links_touching_channel(store):
    await store.add_link(Link(1, 100, 201, "de", None))
    await store.add_link(Link(1, 201, 300, "fr", None))
    await store.add_link(Link(1, 400, 500, "ja", None))
    assert {(l.source_channel_id, l.target_channel_id) for l in await store.links_touching_channel(201)} == {
        (100, 201),
        (201, 300),
    }


async def test_last_seen_never_decreases(store):
    assert await store.get_last_seen(100) is None
    await store.set_last_seen(1, 100, 10)
    await store.set_last_seen(1, 100, 5)
    assert await store.get_last_seen(100) == 10


async def test_source_language_defaults_to_auto(store):
    assert await store.get_source_language(100) is None
    await store.set_source_language(1, 100, "en")
    assert await store.get_source_language(100) == "en"
    await store.set_source_language(1, 100, None)
    assert await store.get_source_language(100) is None


async def test_source_language_and_last_seen_do_not_clobber_each_other(store):
    await store.set_source_language(1, 100, "en")
    await store.set_last_seen(1, 100, 10)
    assert await store.get_source_language(100) == "en"
    await store.set_source_language(1, 100, "de")
    assert await store.get_last_seen(100) == 10


async def test_deepl_key(store):
    assert await store.get_deepl_key(1) is None
    await store.set_deepl_key(1, b"secret")
    assert await store.get_deepl_key(1) == b"secret"
    await store.set_deepl_key(1, None)
    assert await store.get_deepl_key(1) is None


async def test_source_hash_upsert(store):
    assert await store.get_source_hash(1) is None
    await store.record_source(1, 1, 100, "a")
    await store.record_source(1, 1, 100, "b")
    assert await store.get_source_hash(1) == "b"


async def test_parts_replace_and_order(store):
    await store.record_source(1, 1, 100, "h")
    await store.set_parts(1, 9, [31, 30])
    assert await store.get_parts(1, 9) == [31, 30]
    await store.set_parts(1, 9, [30])
    assert await store.get_parts(1, 9) == [30]
    assert await store.all_parts(1) == {9: [30]}


async def test_parts_for_link_spans_messages(store):
    for msg_id in (1, 2):
        await store.record_source(msg_id, 1, 5, "h")
        await store.set_parts(msg_id, 9, [msg_id * 10])
        await store.set_parts(msg_id, 8, [msg_id * 10 + 1])
    assert sorted(await store.parts_for_link(5, 9)) == [10, 20]
    await store.forget_link_parts(5, 9)
    assert await store.parts_for_link(5, 9) == []
    assert sorted(await store.parts_for_link(5, 8)) == [11, 21]


async def test_forget_source_removes_parts(store):
    await store.record_source(1, 1, 100, "h")
    await store.set_parts(1, 9, [30])
    await store.forget_source(1)
    assert await store.get_source_hash(1) is None
    assert await store.all_parts(1) == {}


async def test_tracked_source_ids_respects_min_id(store):
    for msg_id in (5, 10, 15):
        await store.record_source(msg_id, 1, 100, "h")
    await store.record_source(12, 1, 999, "h")
    assert await store.tracked_source_ids(100, 10) == [10, 15]


async def test_webhooks(store):
    assert await store.get_webhook(201) is None
    await store.set_webhook(1, 201, 77, "tok")
    await store.set_webhook(1, 202, 78, "tok2")
    assert await store.get_webhook(201) == (77, "tok")
    assert await store.own_webhook_ids() == {77, 78}
    await store.delete_webhook(201)
    assert await store.own_webhook_ids() == {78}


async def test_own_embeds(store):
    assert await store.get_own_embed(1) is None
    await store.record_own_embed(1, 1, 100)
    assert await store.get_own_embed(1) == 100


async def test_delete_guild_removes_everything(store):
    for g in (1, 2):
        base = g * 1000
        await store.add_link(Link(g, base, base + 1, "de", None))
        await store.set_source_language(g, base, "en")
        await store.set_deepl_key(g, b"k")
        await store.record_source(base + 5, g, base, "h")
        await store.set_parts(base + 5, base + 1, [base + 6])
        await store.set_webhook(g, base + 1, base + 7, "t")
        await store.record_own_embed(base + 8, g, base)
    await store.delete_guild(1)
    assert await store.links_for_guild(1) == []
    assert await store.get_source_language(1000) is None
    assert await store.get_deepl_key(1) is None
    assert await store.get_source_hash(1005) is None
    assert await store.all_parts(1005) == {}
    assert await store.get_webhook(1001) is None
    assert await store.get_own_embed(1008) is None
    assert len(await store.links_for_guild(2)) == 1
    assert await store.get_source_language(2000) == "en"
    assert await store.get_deepl_key(2) == b"k"
    assert await store.all_parts(2005) == {2001: [2006]}
    assert await store.get_webhook(2001) == (2007, "t")
    assert await store.get_own_embed(2008) == 2000


async def test_schema_survives_reopen(tmp_path):
    path = tmp_path / "sub" / "bot.db"
    s = await Store.open(path)
    await s.add_link(Link(1, 100, 201, "de", None))
    await s.close()
    s = await Store.open(path)
    assert len(await s.links_for_source(100)) == 1
    await s.close()


async def test_guild_ids_and_all_links(store):
    await store.add_link(Link(1, 100, 201, "de", None))
    await store.add_link(Link(2, 300, 301, "fr", None))
    await store.set_deepl_key(3, b"k")
    assert await store.guild_ids() == [1, 2, 3]
    assert len(await store.all_links()) == 2


async def test_old_database_loses_the_unused_author_column(tmp_path):
    path = tmp_path / "old.db"
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "CREATE TABLE own_embeds (message_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL, "
            "channel_id INTEGER NOT NULL, author_id INTEGER NOT NULL)"
        )
        await db.execute("INSERT INTO own_embeds VALUES (1, 1, 100, 42)")
        await db.commit()
    store = await Store.open(path)
    await store.record_own_embed(2, 1, 100)
    assert await store.get_own_embed(1) == 100 and await store.get_own_embed(2) == 100
    await store.close()
