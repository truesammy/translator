import asyncio
from types import SimpleNamespace

import pytest

from fakes import FakePoster, FakeTranslator, make_msg
from translator_bot.chain import TranslatorChain
from translator_bot.db import Store
from translator_bot.flags import translate_id
from translator_bot.languages import ORIGINAL
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


async def test_delete_keeps_tracking_parts_it_could_not_delete(env):
    await env.relay.handle_create(make_msg(id=1, channel_id=100))
    stuck = await env.store.get_parts(1, 201)
    env.poster.fail_delete = {201}
    await env.relay.handle_delete(1)
    assert await env.store.all_parts(1) == {201: stuck}
    assert await env.store.get_source_hash(1) is not None
    env.poster.fail_delete = set()
    await env.relay.handle_delete(1)
    assert await env.store.get_source_hash(1) is None and await env.store.all_parts(1) == {}


async def test_edit_replaces_a_part_that_is_gone(env):
    await env.relay.handle_create(make_msg(id=1, channel_id=100, content="a"))
    (lost,) = await env.store.get_parts(1, 201)
    env.poster.gone = {lost}
    await env.relay.handle_edit(make_msg(id=1, channel_id=100, content="b"))
    (replacement,) = await env.store.get_parts(1, 201)
    assert replacement != lost
    channel, _, part = env.poster.sent[-1]
    assert (channel, part.content, part.notify) == (201, "[de] b", False)
    assert [c for c, _, _ in env.poster.edited] == [202]


async def test_real_pings_are_passed_on_and_edits_never_ping(env):
    msg = make_msg(id=1, channel_id=100, content="@everyone <@&7> hi", mention_everyone=True, role_mention_ids=(7,))
    await env.relay.handle_create(msg)
    pings = {channel: part.ping_roles for channel, _, part in env.poster.sent}
    assert pings == {201: (7,), 202: (7, 5)}


async def test_failed_translation_is_retried_by_the_next_catch_up(env):
    env.providers[0].fail = "down"
    msg = make_msg(id=1, channel_id=100, content="hi")
    await env.relay.handle_create(msg)
    assert env.poster.sent == [] and env.poster.failed == [1]
    env.providers[0].fail = None
    await env.relay.handle_edit(msg)  # what catch-up calls for every tracked message
    assert len(env.poster.sent) == 2
    assert all(part.notify for _, _, part in env.poster.sent)  # posted for the first time, so it pings


async def test_failed_post_is_marked_and_retried(env):
    env.poster.fail_channels = {201}
    msg = make_msg(id=1, channel_id=100, content="hi")
    await env.relay.handle_create(msg)
    assert env.poster.failed == [1]
    env.poster.fail_channels = set()
    await env.relay.handle_edit(msg)
    assert {channel for channel, _, _ in env.poster.sent} == {201, 202}


async def test_at_most_three_targets_are_synced_at_once(env):
    for target in range(203, 210):
        await env.store.add_link(Link(1, 100, target, "de", None))
    running = peak = 0

    async def slow(texts, target, source):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return texts

    env.providers[0].translate = slow
    await env.relay.handle_create(make_msg(id=1, channel_id=100, content="hi"))
    assert peak == 3 and len(env.poster.sent) == 9


async def test_hash_stays_empty_until_every_target_is_done(env):
    # A crash while posting must leave the message for the next catch-up.
    env.poster.gate = asyncio.Event()
    create = asyncio.create_task(env.relay.handle_create(make_msg(id=1, channel_id=100)))
    await asyncio.sleep(0.01)
    assert await env.store.get_source_hash(1) == ""
    env.poster.gate.set()
    await create
    assert await env.store.get_source_hash(1)


async def test_original_link_carries_the_translate_button_on_its_last_part(env):
    await env.store.add_link(Link(1, 100, 203, ORIGINAL, None))
    await env.relay.handle_create(make_msg(id=1, channel_id=100, content="word " * 500))
    buttons = (translate_id(100, 1),)
    assert [p.buttons for c, _, p in env.poster.sent if c == 203] == [(), buttons]
    assert all(p.buttons == () for c, _, p in env.poster.sent if c != 203)
    await env.relay.handle_edit(make_msg(id=1, channel_id=100, content="short"))
    assert [p.buttons for c, _, p in env.poster.edited if c == 203] == [buttons]


async def test_private_translation_happens_once_per_content(env):
    await env.store.set_source_language(1, 100, "en")
    msg = make_msg(id=1, channel_id=100, content="hi")
    calls = env.providers[0].calls
    first, second = await asyncio.gather(
        env.relay.private_translation(msg, "de"), env.relay.private_translation(msg, "de")
    )
    assert first == second and first[0].content == "[de] hi" and len(calls) == 1 and calls[0][2] == "en"
    await env.relay.private_translation(msg, "de")
    assert len(calls) == 1
    edited = await env.relay.private_translation(make_msg(id=1, channel_id=100, content="ho"), "de")
    assert edited[0].content == "[de] ho" and len(calls) == 2


async def test_delete_removes_flag_reply_and_stored_translations(env):
    await env.store.add_flag_reply(1, 7, 300, 8)
    await env.store.set_translation(7, 1, "de", "h", b"x")
    await env.relay.handle_delete(7)
    assert env.poster.deleted == [(300, 8)] and await env.store.get_translation(7, "de", "h") is None
