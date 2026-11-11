from translator_bot.providers.deepl_official import DeepLOfficial, xml_escape


def test_xml_escape_leaves_placeholders_alone():
    assert xml_escape('a < b & c <m id="0"/> > d') == 'a &lt; b &amp; c <m id="0"/> &gt; d'


def test_deepl_error_never_contains_the_key():
    provider = DeepLOfficial("secret-key:fx")
    error = provider._error(RuntimeError("request with secret-key:fx failed"))
    assert "secret-key" not in str(error)
