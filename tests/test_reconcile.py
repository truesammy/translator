from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from fakes import FakePoster, FakeTranslator, make_msg
from translator_bot.chain import TranslatorChain
from translator_bot.db import Store
from translator_bot.models import Link
from translator_bot.reconcile import prune, reconcile, snowflake_for
from translator_bot.relay import Relay

NOW = datetime(2026, 11, 10, tzinfo=UTC)


def recent(n):
    return snowflake_for(NOW - timedelta(days=1)) + n


def old(n):
    return snowflake_for(NOW - timedelta(days=40)) + n


@pytest.fixture
async def env():
    store = await Store.open(":memory:")
    await store.add_link(Link(1, 100, 201, "de", None))
    poster = FakePoster()

    async def chain_for(guild_id):
        return TranslatorChain([FakeTranslator()])

    relay = Relay(store, poster, chain_for)
    history: dict[int, list | None] = {}
    calls = []

    async def fetch(channel_id, after_id):
        calls.append((channel_id, after_id))
        messages = history.get(channel_id, [])
        return None if messages is None else [m for m in messages if m.id > after_id]

    yield SimpleNamespace(store=store, poster=poster, relay=relay, history=history, calls=calls, fetch=fetch)
    await store.close()


def test_snowflake_for_matches_discord_epoch():
    assert snowflake_for(datetime(2015, 1, 1, tzinfo=UTC)) == 0
    assert snowflake_for(datetime(2015, 1, 1, 0, 0, 1, tzinfo=UTC)) == 1000 << 22


async def test_missed_message_is_relayed(env):
    await env.relay.handle_create(make_msg(id=recent(1), channel_id=100, content="a"))
    env.history[100] = [
        make_msg(id=recent(1), channel_id=100, content="a"),
        make_msg(id=recent(2), channel_id=100, content="b"),
    ]
    await reconcile(env.store, env.relay, env.fetch, NOW)
    assert await env.store.get_parts(recent(2), 201)
    assert len(env.poster.sent) == 2 and env.poster.edited == []


async def test_missed_edit_is_applied(env):
    await env.relay.handle_create(make_msg(id=recent(1), channel_id=100, content="a"))
    env.history[100] = [make_msg(id=recent(1), channel_id=100, content="changed")]
    await reconcile(env.store, env.relay, env.fetch, NOW)
    assert [p.content for _, _, p in env.poster.edited] == ["[de] changed"]


async def test_missed_delete_is_applied(env):
    await env.relay.handle_create(make_msg(id=recent(1), channel_id=100))
    env.history[100] = []
    await reconcile(env.store, env.relay, env.fetch, NOW)
    assert len(env.poster.deleted) == 1 and await env.store.get_source_hash(recent(1)) is None


async def test_messages_older_than_window_are_left_alone(env):
    await env.relay.handle_create(make_msg(id=old(1), channel_id=100))
    await env.store.set_last_seen(1, 100, recent(1))
    env.history[100] = []
    await reconcile(env.store, env.relay, env.fetch, NOW)
    assert env.poster.deleted == []


async def test_never_used_channel_is_not_backfilled(env):
    env.history[100] = [make_msg(id=recent(1), channel_id=100)]
    await reconcile(env.store, env.relay, env.fetch, NOW)
    assert env.poster.sent == []


async def test_own_translations_are_not_relayed(env):
    await env.relay.handle_create(make_msg(id=recent(1), channel_id=100))
    env.history[100] = [
        make_msg(id=recent(1), channel_id=100),
        make_msg(id=recent(2), channel_id=100, from_own_webhook=True),
    ]
    await reconcile(env.store, env.relay, env.fetch, NOW)
    assert len(env.poster.sent) == 1


async def test_tracked_own_embed_is_still_checked_for_edits(env):
    await env.relay.handle_create(make_msg(id=recent(1), channel_id=100, content="a"))
    env.history[100] = [make_msg(id=recent(1), channel_id=100, content="b", from_own_webhook=True)]
    await reconcile(env.store, env.relay, env.fetch, NOW)
    assert len(env.poster.edited) == 1


async def test_unreachable_channel_is_skipped(env):
    await env.relay.handle_create(make_msg(id=recent(1), channel_id=100))
    env.history[100] = None
    await reconcile(env.store, env.relay, env.fetch, NOW)
    assert env.poster.deleted == []


async def test_failing_fetch_does_not_stop_other_channels(env):
    await env.store.add_link(Link(1, 50, 201, "de", None))
    await env.relay.handle_create(make_msg(id=recent(1), channel_id=100))
    env.history[100] = []

    async def fetch(channel_id, after_id):
        if channel_id == 50:
            raise RuntimeError("boom")
        return await env.fetch(channel_id, after_id)

    await reconcile(env.store, env.relay, fetch, NOW)
    assert len(env.poster.deleted) == 1


async def test_long_downtime_fetches_from_last_seen(env):
    await env.relay.handle_create(make_msg(id=old(1), channel_id=100))
    env.history[100] = []
    await reconcile(env.store, env.relay, env.fetch, NOW)
    assert env.calls == [(100, old(1))]


async def test_message_arriving_during_catch_up_is_not_deleted(env):
    await env.relay.handle_create(make_msg(id=recent(1), channel_id=100))

    async def fetch(channel_id, after_id):
        # A live message is relayed while the history request is still running.
        await env.relay.handle_create(make_msg(id=recent(5), channel_id=100))
        return [make_msg(id=recent(1), channel_id=100)]

    await reconcile(env.store, env.relay, fetch, NOW)
    assert env.poster.deleted == [] and await env.store.get_parts(recent(5), 201)


async def test_one_failing_message_does_not_stop_the_rest(env):
    await env.relay.handle_create(make_msg(id=recent(1), channel_id=100, content="a"))
    await env.relay.handle_create(make_msg(id=recent(2), channel_id=100, content="a"))
    env.history[100] = [
        make_msg(id=recent(1), channel_id=100, content="x"),
        make_msg(id=recent(2), channel_id=100, content="y"),
    ]
    real_edit = env.relay.handle_edit

    async def flaky_edit(msg):
        if msg.id == recent(1):
            raise RuntimeError("boom")
        await real_edit(msg)

    env.relay.handle_edit = flaky_edit
    await reconcile(env.store, env.relay, env.fetch, NOW)
    assert [p.content for _, _, p in env.poster.edited] == ["[de] y"]


def exists(*missing):
    async def check(some_id):
        return some_id not in missing

    return check


async def test_prune_forgets_servers_the_bot_left(env):
    await env.store.set_deepl_key(1, b"k")
    await prune(env.store, env.relay, exists(1), exists())
    assert await env.store.get_deepl_key(1) is None and await env.store.links_for_guild(1) == []


async def test_prune_removes_links_of_a_deleted_source_and_their_translations(env):
    await env.relay.handle_create(make_msg(id=recent(1), channel_id=100))
    await prune(env.store, env.relay, exists(), exists(100))
    assert await env.store.all_links() == [] and len(env.poster.deleted) == 1


async def test_prune_removes_links_to_a_deleted_target_without_deleting(env):
    await env.relay.handle_create(make_msg(id=recent(1), channel_id=100))
    await prune(env.store, env.relay, exists(), exists(201))
    assert await env.store.all_links() == [] and env.poster.deleted == []


async def test_prune_keeps_everything_that_still_exists(env):
    await env.store.set_deepl_key(1, b"k")
    await prune(env.store, env.relay, exists(), exists())
    assert len(await env.store.all_links()) == 1 and await env.store.get_deepl_key(1) == b"k"
