import pytest
from PyDeepLX import PyDeepLX

from translator_bot.languages import get_language
from translator_bot.providers.base import TranslationError
from translator_bot.providers.deeplx import DeepLX

NOTICE = "You're using an older version of DeepL. To continue using the app, please update to the latest version."


async def test_deepl_update_notice_is_a_failure_not_a_translation(monkeypatch):
    monkeypatch.setattr(PyDeepLX, "translate", lambda *args: NOTICE)
    with pytest.raises(TranslationError):
        await DeepLX().translate(["Hallo zusammen"], get_language("en"), None)


async def test_normal_result_is_returned(monkeypatch):
    monkeypatch.setattr(PyDeepLX, "translate", lambda *args: "Hello everyone")
    assert await DeepLX().translate(["Hallo zusammen"], get_language("en"), None) == ["Hello everyone"]
