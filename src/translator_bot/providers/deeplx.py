import asyncio

from PyDeepLX import PyDeepLX

from ..languages import Language, deepl_code
from .base import TranslationError


class DeepLX:
    """Unofficial DeepL access without a key. Throttled quickly and may stop working."""

    name = "deeplx"

    async def translate(self, texts: list[str], target: Language, source: Language | None) -> list[str]:
        source_code = source.code.split("-")[0].upper() if source else "auto"
        target_code = deepl_code(target).split("-")[0]
        results = []
        for text in texts:
            try:
                result = await asyncio.to_thread(PyDeepLX.translate, text, source_code, target_code)
            except Exception as error:
                raise TranslationError(f"{type(error).__name__}: {error}") from None
            if not isinstance(result, str) or not result.strip():
                raise TranslationError("empty result")
            # DeepL answers outdated clients with this notice instead of a translation.
            # shortcut: matches the English wording only, widen if DeepL changes or localizes it
            if "older version of DeepL" in result and "older version of DeepL" not in text:
                raise TranslationError("DeepL rejected the client as outdated")
            results.append(result)
        return results
