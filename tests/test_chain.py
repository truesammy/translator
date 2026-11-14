import asyncio

import pytest

from fakes import FakeTranslator
from translator_bot.chain import AllProvidersFailed, TranslatorChain, build_chain
from translator_bot.languages import get_language

DE = get_language("de")


async def test_first_provider_wins():
    a, b = FakeTranslator("a"), FakeTranslator("b")
    assert await TranslatorChain([a, b]).translate(["hi"], DE, None) == ["[de] hi"]
    assert b.calls == []


async def test_source_language_is_passed_on():
    a = FakeTranslator("a")
    await TranslatorChain([a]).translate(["hi"], DE, get_language("en"))
    assert a.calls == [(["hi"], "de", "en")]


async def test_falls_through_on_error():
    a, b = FakeTranslator("a", fail="quota"), FakeTranslator("b")
    assert await TranslatorChain([a, b]).translate(["hi"], DE, None) == ["[de] hi"]


async def test_falls_through_on_unexpected_exception():
    class Broken(FakeTranslator):
        async def translate(self, texts, target, source):
            raise RuntimeError("boom")

    assert await TranslatorChain([Broken("a"), FakeTranslator("b")]).translate(["hi"], DE, None) == ["[de] hi"]


async def test_damaged_placeholders_count_as_failure():
    a = FakeTranslator("a", transform=lambda text, lang: text.replace('<m id="0"/>', ""))
    b = FakeTranslator("b")
    out = await TranslatorChain([a, b]).translate(['hello <m id="0"/>'], DE, None)
    assert out == ['[de] hello <m id="0"/>']


async def test_wrong_result_length_counts_as_failure():
    class Short(FakeTranslator):
        async def translate(self, texts, target, source):
            return []

    assert await TranslatorChain([Short("a"), FakeTranslator("b")]).translate(["hi"], DE, None) == ["[de] hi"]


async def test_all_fail_reports_every_provider():
    chain = TranslatorChain([FakeTranslator("a", fail="x"), FakeTranslator("b", fail="y")])
    with pytest.raises(AllProvidersFailed) as error:
        await chain.translate(["hi"], DE, None)
    assert error.value.errors == [("a", "x"), ("b", "y")]
    assert "a: x; b: y" in str(error.value)


async def test_untranslatable_texts_pass_through_in_position():
    a = FakeTranslator("a")
    out = await TranslatorChain([a]).translate(['<m id="0"/>', "hi", ""], DE, None)
    assert out == ['<m id="0"/>', "[de] hi", ""]
    assert a.calls[0][0] == ["hi"]


async def test_nothing_translatable_calls_no_provider():
    a = FakeTranslator("a")
    assert await TranslatorChain([a]).translate(["", "123"], DE, None) == ["", "123"]
    assert a.calls == []


def test_build_chain_order():
    assert [p.name for p in build_chain("k:fx")._providers] == ["deepl", "deeplx", "google"]
    assert [p.name for p in build_chain(None)._providers] == ["deeplx", "google"]


class Hanging(FakeTranslator):
    async def translate(self, texts, target, source):
        await asyncio.sleep(5)


async def test_hanging_provider_times_out_and_falls_through():
    chain = TranslatorChain([Hanging("a"), FakeTranslator("b")], timeout=0.01)
    assert await chain.translate(["hi"], DE, None) == ["[de] hi"]


async def test_timeout_is_reported():
    with pytest.raises(AllProvidersFailed) as error:
        await TranslatorChain([Hanging("a")], timeout=0.01).translate(["hi"], DE, None)
    assert error.value.errors == [("a", "timed out")]
