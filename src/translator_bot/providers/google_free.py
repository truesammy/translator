import asyncio

from deep_translator import GoogleTranslator

from ..languages import Language
from .base import TranslationError


class GoogleFree:
    """Unofficial Google Translate access. May be throttled or stop working."""

    name = "google"

    async def translate(self, texts: list[str], target: Language, source: Language | None) -> list[str]:
        results = []
        try:
            translator = GoogleTranslator(source=source.code if source else "auto", target=target.code)
            for text in texts:
                result = await asyncio.to_thread(translator.translate, text)
                if not isinstance(result, str) or not result.strip():
                    raise TranslationError("empty result")
                results.append(result)
        except TranslationError:
            raise
        except Exception as error:
            raise TranslationError(f"{type(error).__name__}: {error}") from None
        return results
