import pytest

from fakes import FakeTranslator, chain, make_embed, make_link, make_msg
from translator_bot.chain import AllProvidersFailed, TranslatorChain
from translator_bot.models import Attachment, EmbedField
from translator_bot.render import content_hash, render


async def test_plain_text():
    parts = await render(make_msg(content="**Hello** <@1>"), make_link(), None, chain())
    assert [p.content for p in parts] == ["[de] **Hello** <@1>"]
    assert parts[0].notify


async def test_everyone_becomes_language_role():
    msg = make_msg(content="@everyone news @here", mention_everyone=True)
    parts = await render(msg, make_link(role_id=5), None, chain())
    assert parts[0].content == "[de] <@&5> news <@&5>"
    assert parts[0].ping_roles == (5,)


async def test_everyone_that_did_not_ping_in_the_original_does_not_ping_the_role():
    # Written by someone without the Mention Everyone permission: plain text in the original.
    parts = await render(make_msg(content="@everyone news"), make_link(role_id=5), None, chain())
    assert parts[0].content == "[de] @everyone news" and parts[0].ping_roles == ()


async def test_only_roles_that_pinged_in_the_original_ping_again():
    msg = make_msg(content="<@&7> and <@&8>", role_mention_ids=(7,))
    parts = await render(msg, make_link(role_id=5), None, chain())
    assert parts[0].ping_roles == (7,)


async def test_everyone_stays_text_without_role():
    parts = await render(make_msg(content="@here news"), make_link(), None, chain())
    assert parts[0].content == "[de] @here news"


async def test_embed_text_is_translated_and_rest_copied():
    embed = make_embed(
        title="T",
        description="D",
        fields=(EmbedField("N", "V", True),),
        footer_text="F",
        author_name="A",
        color=0xFF0000,
        image_url="https://i/x.png",
        url="https://u",
    )
    out = (await render(make_msg(content="", embeds=(embed,)), make_link(), None, chain()))[0].embeds[0]
    assert (out.title, out.description, out.footer_text, out.author_name) == ("[de] T", "[de] D", "[de] F", "[de] A")
    assert out.fields == (EmbedField("[de] N", "[de] V", True),)
    assert (out.color, out.image_url, out.url) == (0xFF0000, "https://i/x.png", "https://u")


async def test_missing_embed_parts_stay_missing():
    out = (await render(make_msg(content="", embeds=(make_embed(description="D"),)), make_link(), None, chain()))[0]
    assert out.embeds[0].title is None and out.embeds[0].footer_text is None


async def test_embed_everyone_becomes_language_role():
    msg = make_msg(content="", embeds=(make_embed(description="@everyone hi"),))
    out = (await render(msg, make_link(role_id=5), None, chain()))[0]
    assert out.embeds[0].description == "[de] <@&5> hi"


async def test_single_chain_call_per_message():
    translator = FakeTranslator("a")
    msg = make_msg(content="x", embeds=(make_embed(title="T"),))
    await render(msg, make_link(), None, TranslatorChain([translator]))
    assert len(translator.calls) == 1


async def test_fixed_source_language_is_passed_to_the_translator():
    translator = FakeTranslator("a")
    await render(make_msg(content="hi"), make_link("de"), "en", TranslatorChain([translator]))
    assert translator.calls[0][1:] == ("de", "en")


async def test_same_language_skips_translation():
    translator = FakeTranslator("a")
    parts = await render(make_msg(content="Hallo"), make_link("de"), "de", TranslatorChain([translator]))
    assert parts[0].content == "Hallo" and translator.calls == []


async def test_no_translatable_text_skips_translation():
    translator = FakeTranslator("a")
    msg = make_msg(content="https://example.com <@1>", attachments=(Attachment("a.png", "https://c/a.png", 10),))
    parts = await render(msg, make_link(), None, TranslatorChain([translator]))
    assert parts[0].content == "https://example.com <@1>"
    assert parts[0].attachments == msg.attachments and translator.calls == []


async def test_attachment_only_message_is_one_empty_part():
    msg = make_msg(content="", attachments=(Attachment("a.png", "u", 1),))
    parts = await render(msg, make_link(), None, chain())
    assert len(parts) == 1 and parts[0].content == "" and len(parts[0].attachments) == 1


async def test_message_with_nothing_to_relay_yields_no_parts():
    assert await render(make_msg(content=""), make_link(), None, chain()) == []


async def test_long_translation_is_split_and_only_first_part_notifies():
    long = FakeTranslator("a", transform=lambda text, lang: ("wort " * 900).strip())
    msg = make_msg(content="x", embeds=(make_embed(title="T"),))
    parts = await render(msg, make_link(), None, TranslatorChain([long]))
    assert len(parts) > 1
    assert [p.notify for p in parts] == [True] + [False] * (len(parts) - 1)
    assert parts[-1].embeds and not parts[0].embeds
    assert all(len(p.content) <= 2000 for p in parts)


async def test_embed_limits_enforced():
    big = FakeTranslator("a", transform=lambda text, lang: "x" * 7000)
    msg = make_msg(content="", embeds=(make_embed(title="T", description="D", footer_text="F"),))
    embed = (await render(msg, make_link(), None, TranslatorChain([big])))[0].embeds[0]
    assert len(embed.title) == 256 and len(embed.footer_text) == 2048
    assert len(embed.title) + len(embed.description) + len(embed.footer_text) <= 6000


async def test_embed_with_many_long_fields_fits_the_total_limit():
    big = FakeTranslator("a", transform=lambda text, lang: "x" * 2000)
    fields = tuple(EmbedField(f"n{i}", f"v{i}", False) for i in range(25))
    msg = make_msg(content="", embeds=(make_embed(description="D", fields=fields),))
    embed = (await render(msg, make_link(), None, TranslatorChain([big])))[0].embeds[0]
    total = len(embed.description or "") + sum(len(f.name) + len(f.value) for f in embed.fields)
    assert total <= 6000 and len(embed.fields) >= 1


async def test_all_providers_failed_propagates():
    with pytest.raises(AllProvidersFailed):
        await render(make_msg(content="hi"), make_link(), None, TranslatorChain([FakeTranslator("a", fail="x")]))


def test_content_hash_changes_with_content_and_embeds():
    assert content_hash(make_msg(content="a")) != content_hash(make_msg(content="b"))
    assert content_hash(make_msg(content="a")) == content_hash(make_msg(content="a"))
    assert content_hash(make_msg(embeds=(make_embed(title="x"),))) != content_hash(
        make_msg(embeds=(make_embed(title="y"),))
    )


def test_content_hash_ignores_attachment_url_signatures():
    a = make_msg(attachments=(Attachment("a.png", "https://cdn/a.png?ex=1", 10),))
    b = make_msg(attachments=(Attachment("a.png", "https://cdn/a.png?ex=2", 10),))
    assert content_hash(a) == content_hash(b)


async def test_embeds_of_one_message_share_the_6000_limit():
    embeds = (make_embed(description="a" * 2998), make_embed(description="b" * 2998))
    (part,) = await render(make_msg(content="", embeds=embeds), make_link(), None, chain())
    assert sum(len(embed.description) for embed in part.embeds) <= 6000


def test_hash_ignores_the_signature_of_discord_image_links():
    def msg(signature):
        url = f"https://cdn.discordapp.com/attachments/1/2/a.png?ex={signature}&hm=1"
        return make_msg(embeds=(make_embed(image_url=url),))

    assert content_hash(msg("aa")) == content_hash(msg("bb"))
    assert content_hash(make_msg(content="a?b")) != content_hash(make_msg(content="a?c"))


async def test_only_users_that_pinged_in_the_original_ping_again():
    parts = await render(make_msg(content="<@9> and <@8>", user_mention_ids=(9,)), make_link(), None, chain())
    assert parts[0].ping_users == (9,)


async def test_original_link_copies_without_translating():
    translator = FakeTranslator("a")
    parts = await render(make_msg(content="hi @everyone"), make_link("original"), None, TranslatorChain([translator]))
    assert translator.calls == [] and parts[0].content == "hi @everyone"
