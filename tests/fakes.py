from translator_bot.chain import TranslatorChain
from translator_bot.models import EmbedData, Link, SourceMessage
from translator_bot.providers.base import TranslationError
from translator_bot.relay import MessageGone


def make_msg(**overrides) -> SourceMessage:
    values = dict(id=1, guild_id=1, channel_id=100, author_name="Mika", author_avatar_url=None, content="hello")
    return SourceMessage(**{**values, **overrides})


def make_embed(**values) -> EmbedData:
    return EmbedData(**values)


def make_link(language="de", role_id=None, target=201) -> Link:
    return Link(1, 100, target, language, role_id)


def chain(*providers) -> TranslatorChain:
    return TranslatorChain(providers or [FakeTranslator()])


class FakePoster:
    """Records what the relay would post to Discord."""

    def __init__(self):
        self.sent, self.edited, self.deleted, self.failed = [], [], [], []
        self.fail_channels: set[int] = set()
        self.fail_delete: set[int] = set()  # channels where delete() fails
        self.gone: set[int] = set()  # message ids that can no longer be edited
        self.gate = None  # an asyncio.Event that send() waits for
        self._next_id = 1000

    async def send(self, channel_id, author_name, avatar_url, part):
        if self.gate:
            await self.gate.wait()
        if channel_id in self.fail_channels:
            raise RuntimeError("no permission")
        self._next_id += 1
        self.sent.append((channel_id, author_name, part))
        return self._next_id

    async def edit(self, channel_id, message_id, part):
        if message_id in self.gone:
            raise MessageGone()
        self.edited.append((channel_id, message_id, part))

    async def delete(self, channel_id, message_id):
        if channel_id in self.fail_delete:
            raise RuntimeError("no permission")
        self.deleted.append((channel_id, message_id))

    async def mark_failed(self, msg):
        self.failed.append(msg.id)


class FakeTranslator:
    """Prefixes every text with the target language code, e.g. "[de] hi"."""

    def __init__(self, name="fake", *, fail=None, transform=lambda text, lang: f"[{lang.code}] {text}"):
        self.name, self.fail, self.transform, self.calls = name, fail, transform, []

    async def translate(self, texts, target, source):
        self.calls.append((list(texts), target.code, source.code if source else None))
        if self.fail:
            raise TranslationError(self.fail)
        return [self.transform(text, target) for text in texts]
