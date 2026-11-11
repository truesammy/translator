import asyncio
from types import SimpleNamespace

import pytest

from fakes import FakePoster, FakeTranslator, make_msg
from translator_bot.chain import TranslatorChain
from translator_bot.db import Store
from translator_bot.models import Link
from translator_bot.relay import Relay


def translate(text, lang):
    """"long" turns into a three-part message, everything else gets the language prefix."""
    return ("wort " * 1000).strip() if "long" in text else f"[{lang.code}] {text}"


@pytest.fixture
async def env():
    store = await Store.open(":memory:")
    await store.add_link(Link(1, 100, 201, "de", None))
    await store.add_link(Link(1, 100, 202, "fr", 5))
    poster = FakePoster()
    providers = [FakeTranslator(transform=translate)]

    async def chain_for(guild_id):
        return TranslatorChain(providers)

    yield SimpleNamespace(store=store, poster=poster, providers=providers, relay=Relay(store, poster, chain_for))
    await store.close()


async def test_create_posts_to_every_target(env):
    await env.relay.handle_create(make_msg(id=1, channel_id=100, content="hi"))
    assert {(c, p.content) for c, _, p in env.poster.sent} == {(201, "[de] hi"), (202, "[fr] hi")}
    assert await env.store.get_parts(1, 201) and await env.store.get_last_seen(100) == 1


async def test_create_uses_author_identity(env):
    await env.relay.handle_create(make_msg(id=1, channel_id=100, author_name="Mika"))
    assert env.poster.sent[0][1] == "Mika"


async def test_create_uses_the_channels_source_language(env):
    await env.store.set_source_language(1, 100, "en")
    await env.relay.handle_create(make_msg(id=1, channel_id=100))
    assert {call[2] for call in env.providers[0].calls} == {"en"}


async def test_channel_without_links_is_ignored(env):
    await env.relay.handle_create(make_msg(id=1, channel_id=999))
    assert env.poster.sent == [] and await env.store.get_source_hash(1) is None


async def test_create_twice_posts_once(env):
    msg = make_msg(id=1, channel_id=100)
    await env.relay.handle_create(msg)
    await env.relay.handle_create(msg)
    assert len(env.poster.sent) == 2


async def test_edit_updates_in_place(env):
    await env.relay.handle_create(make_msg(id=1, channel_id=100, content="a"))
    await env.relay.handle_edit(make_msg(id=1, channel_id=100, content="b"))
    assert {p.content for _, _, p in env.poster.edited} == {"[de] b", "[fr] b"}
    assert len(env.poster.sent) == 2


async def test_edit_without_change_does_nothing(env):
    msg = make_msg(id=1, channel_id=100)
    await env.relay.handle_create(msg)
    await env.relay.handle_edit(msg)
    assert env.poster.edited == []


async def test_edit_of_untracked_message_does_nothing(env):
    await env.relay.handle_edit(make_msg(id=7, channel_id=100))
    assert env.poster.sent == [] and env.poster.edited == []


async def test_edit_growing_and_shrinking_part_count(env):
    await env.relay.handle_create(make_msg(id=1, channel_id=100, content="short"))
    await env.relay.handle_edit(make_msg(id=1, channel_id=100, content="long"))
    assert len(await env.store.get_parts(1, 201)) == 3
    assert all(not p.notify for _, _, p in env.poster.sent[2:])
    await env.relay.handle_edit(make_msg(id=1, channel_id=100, content="short"))
    assert len(await env.store.get_parts(1, 201)) == 1
    assert len(env.poster.deleted) == 4


async def test_delete_removes_all_parts_and_forgets(env):
    await env.relay.handle_create(make_msg(id=1, channel_id=100))
    await env.relay.handle_delete(1)
    assert len(env.poster.deleted) == 2 and await env.store.get_source_hash(1) is None


async def test_delete_of_untracked_message_does_nothing(env):
    await env.relay.handle_delete(42)
    assert env.poster.deleted == []


async def test_all_providers_failing_marks_and_logs(env, caplog):
    env.providers[:] = [FakeTranslator("a", fail="quota")]
    await env.relay.handle_create(make_msg(id=1, channel_id=100))
    assert env.poster.sent == [] and env.poster.failed == [1]
    assert "quota" in caplog.text and "German" in caplog.text


async def test_one_target_failing_does_not_block_others(env, caplog):
    env.poster.fail_channels = {201}
    await env.relay.handle_create(make_msg(id=1, channel_id=100, content="hi"))
    assert [c for c, _, _ in env.poster.sent] == [202]
    assert "201" in caplog.text and "no permission" in caplog.text


async def test_edit_retries_target_that_failed_on_create(env):
    env.poster.fail_channels = {201}
    await env.relay.handle_create(make_msg(id=1, channel_id=100, content="a"))
    env.poster.fail_channels = set()
    await env.relay.handle_edit(make_msg(id=1, channel_id=100, content="b"))
    assert await env.store.get_parts(1, 201)


async def test_edit_during_create_is_serialized(env):
    env.poster.gate = asyncio.Event()
    create = asyncio.create_task(env.relay.handle_create(make_msg(id=1, channel_id=100, content="a")))
    edit = asyncio.create_task(env.relay.handle_edit(make_msg(id=1, channel_id=100, content="b")))
    await asyncio.sleep(0.01)
    env.poster.gate.set()
    await asyncio.gather(create, edit)
    assert len(env.poster.sent) == 2
    assert {p.content for _, _, p in env.poster.edited} == {"[de] b", "[fr] b"}


async def test_delete_during_create_leaves_nothing_behind(env):
    env.poster.gate = asyncio.Event()
    create = asyncio.create_task(env.relay.handle_create(make_msg(id=1, channel_id=100)))
    delete = asyncio.create_task(env.relay.handle_delete(1))
    await asyncio.sleep(0.01)
    env.poster.gate.set()
    await asyncio.gather(create, delete)
    assert len(env.poster.deleted) == 2 and await env.store.all_parts(1) == {}


async def test_remove_link_deletes_its_messages_only(env):
    await env.relay.handle_create(make_msg(id=1, channel_id=100))
    await env.relay.handle_create(make_msg(id=2, channel_id=100))
    await env.relay.remove_link(100, 201)
    assert {c for c, _ in env.poster.deleted} == {201} and len(env.poster.deleted) == 2
    assert [l.target_channel_id for l in await env.store.links_for_source(100)] == [202]
    assert await env.store.get_parts(1, 201) == [] and await env.store.get_parts(1, 202)


async def test_remove_link_without_deleting_messages(env):
    await env.relay.handle_create(make_msg(id=1, channel_id=100))
    await env.relay.remove_link(100, 201, delete_messages=False)
    assert env.poster.deleted == [] and await env.store.get_parts(1, 201) == []
