from translator_bot.chain import TranslatorChain
from translator_bot.models import EmbedData, Link, SourceMessage
from translator_bot.providers.base import TranslationError


def make_msg(**overrides) -> SourceMessage:
    values = dict(id=1, guild_id=1, channel_id=100, author_name="Mika", author_avatar_url=None, content="hello")
    return SourceMessage(**{**values, **overrides})


def make_embed(**values) -> EmbedData:
    return EmbedData(**values)


def make_link(language="de", role_id=None, target=201) -> Link:
    return Link(1, 100, target, language, role_id)


def chain(*providers) -> TranslatorChain:
    return TranslatorChain(providers or [FakeTranslator()])


class FakeTranslator:
    """Prefixes every text with the target language code, e.g. "[de] hi"."""

    def __init__(self, name="fake", *, fail=None, transform=lambda text, lang: f"[{lang.code}] {text}"):
        self.name, self.fail, self.transform, self.calls = name, fail, transform, []

    async def translate(self, texts, target, source):
        self.calls.append((list(texts), target.code, source.code if source else None))
        if self.fail:
            raise TranslationError(self.fail)
        return [self.transform(text, target) for text in texts]
