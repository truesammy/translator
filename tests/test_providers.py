from types import SimpleNamespace

from translator_bot.languages import get_language
from translator_bot.providers.deepl_official import DeepLOfficial, xml_escape


def test_xml_escape_leaves_placeholders_alone():
    assert xml_escape('a < b & c <m id="0"/> > d') == 'a &lt; b &amp; c <m id="0"/> &gt; d'


def test_deepl_error_never_contains_the_key():
    provider = DeepLOfficial("secret-key:fx")
    error = provider._error(RuntimeError("request with secret-key:fx failed"))
    assert "secret-key" not in str(error)


async def test_deepl_request_and_response():
    provider = DeepLOfficial("k:fx")
    seen = {}

    def fake(texts, **options):
        seen.update(options, texts=texts)
        return [SimpleNamespace(text='Tom &amp; Jerry <m id="0"/>')]

    provider._client = SimpleNamespace(translate_text=fake)
    result = await provider.translate(['Tom & Jerry <m id="0"/>'], get_language("no"), get_language("en"))
    assert result == ['Tom & Jerry <m id="0"/>']
    assert seen["texts"] == ['Tom &amp; Jerry <m id="0"/>']
    assert (seen["target_lang"], seen["source_lang"], seen["tag_handling"]) == ("NB", "EN", "xml")
