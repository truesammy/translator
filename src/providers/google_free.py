import asyncio

from deep_translator import GoogleTranslator

from ..languages import Language
from .base import TranslationError


def split_lines(text: str, limit: int = 4500) -> list[str]:
    """Google takes less than 5000 characters per request, so longer texts go line by line.
    Joining the pieces with a newline gives the text back."""
    pieces = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < 0:
            raise TranslationError("a line is too long")
        pieces.append(text[:cut])
        text = text[cut + 1 :]
    return pieces + [text]


class GoogleFree:
    """Unofficial Google Translate access. May be throttled or stop working."""

    name = "google"

    async def translate(self, texts: list[str], target: Language, source: Language | None) -> list[str]:
        results = []
        try:
            translator = GoogleTranslator(source=source.code if source else "auto", target=target.code)
            for text in texts:
                pieces = [
                    await asyncio.to_thread(translator.translate, piece) if piece.strip() else piece
                    for piece in split_lines(text)
                ]
                result = "\n".join(pieces) if all(isinstance(piece, str) for piece in pieces) else None
                if not isinstance(result, str) or not result.strip():
                    raise TranslationError("empty result")
                results.append(result)
        except TranslationError:
            raise
        except Exception as error:
            raise TranslationError(f"{type(error).__name__}: {error}") from None
        return results
