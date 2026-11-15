import asyncio
import html
import re

import deepl

from ..languages import Language, deepl_code
from .base import TranslationError

_PLACEHOLDER = re.compile(r'(<m id="\d+"/>)')


def xml_escape(text: str) -> str:
    """Escape everything except our placeholders, because DeepL parses the text as XML."""
    pieces = _PLACEHOLDER.split(text)
    return "".join(piece if i % 2 else html.escape(piece, quote=False) for i, piece in enumerate(pieces))


class DeepLOfficial:
    name = "deepl"

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client = deepl.DeepLClient(api_key)

    def _error(self, error: Exception) -> TranslationError:
        # The key must never reach a log line or a reply.
        return TranslationError(f"{type(error).__name__}: {error}".replace(self._api_key, "***"))

    async def translate(self, texts: list[str], target: Language, source: Language | None) -> list[str]:
        try:
            results = await asyncio.to_thread(
                self._client.translate_text,
                [xml_escape(text) for text in texts],
                target_lang=deepl_code(target),
                # source codes have no regional variant: EN, not EN-US
                source_lang=deepl_code(source).split("-")[0] if source else None,
                tag_handling="xml",
                preserve_formatting=True,
            )
        except Exception as error:
            raise self._error(error) from None
        return [html.unescape(result.text) for result in results]

    async def usage(self) -> tuple[int, int]:
        """(characters used, character limit) of the current billing period."""
        try:
            usage = await asyncio.to_thread(self._client.get_usage)
        except Exception as error:
            raise self._error(error) from None
        return usage.character.count or 0, usage.character.limit or 0
