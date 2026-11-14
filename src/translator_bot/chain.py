import asyncio
from collections.abc import Sequence

from .languages import Language
from .protect import has_translatable_text, intact
from .providers.base import TranslationError, Translator
from .providers.deepl_official import DeepLOfficial
from .providers.deeplx import DeepLX
from .providers.google_free import GoogleFree


class AllProvidersFailed(Exception):
    def __init__(self, errors: list[tuple[str, str]]):
        self.errors = errors
        super().__init__("; ".join(f"{name}: {reason}" for name, reason in errors))


class TranslatorChain:
    def __init__(self, providers: Sequence[Translator], timeout: float = 30):
        self._providers = list(providers)
        self._timeout = timeout  # a hanging provider must not block the message forever

    async def translate(self, texts: list[str], target: Language, source: Language | None) -> list[str]:
        """Translate masked texts with the first provider that returns every placeholder intact."""
        wanted = [i for i, text in enumerate(texts) if has_translatable_text(text)]
        if not wanted:
            return list(texts)
        batch = [texts[i] for i in wanted]
        errors: list[tuple[str, str]] = []
        for provider in self._providers:
            try:
                translated = await asyncio.wait_for(provider.translate(batch, target, source), self._timeout)
            except TimeoutError:
                errors.append((provider.name, "timed out"))
                continue
            except TranslationError as error:
                errors.append((provider.name, str(error)))
                continue
            except Exception as error:
                errors.append((provider.name, f"{type(error).__name__}: {error}"))
                continue
            if len(translated) != len(batch):
                errors.append((provider.name, "wrong number of results"))
            elif not all(intact(before, after) for before, after in zip(batch, translated)):
                errors.append((provider.name, "placeholders damaged"))
            else:
                result = list(texts)
                for i, text in zip(wanted, translated):
                    result[i] = text
                return result
        raise AllProvidersFailed(errors)


def build_chain(deepl_key: str | None) -> TranslatorChain:
    fallbacks: list[Translator] = [DeepLX(), GoogleFree()]
    return TranslatorChain([DeepLOfficial(deepl_key), *fallbacks] if deepl_key else fallbacks)
