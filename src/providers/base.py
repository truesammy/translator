from typing import Protocol

from ..languages import Language


class TranslationError(Exception):
    pass


class Translator(Protocol):
    name: str

    async def translate(self, texts: list[str], target: Language, source: Language | None) -> list[str]: ...
