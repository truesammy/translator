import hashlib
from dataclasses import replace

from .chain import TranslatorChain
from .languages import get_language
from .models import EmbedData, EmbedField, Link, OutgoingPart, SourceMessage
from .protect import mask, unmask
from .splitting import split_text, truncate

TITLE, DESCRIPTION, FIELD_NAME, FIELD_VALUE, FOOTER, AUTHOR, EMBED_TOTAL = 256, 4096, 256, 1024, 2048, 256, 6000


def content_hash(msg: SourceMessage) -> str:
    # Attachment urls carry signatures that change on every fetch, so they stay out of the hash.
    identity = (msg.content, msg.embeds, tuple((a.filename, a.size) for a in msg.attachments))
    return hashlib.sha256(repr(identity).encode()).hexdigest()


def _embed_texts(embed: EmbedData) -> list[str | None]:
    texts = [embed.title, embed.description, embed.footer_text, embed.author_name]
    for field in embed.fields:
        texts += [field.name, field.value]
    return texts


def _embed_length(embed: EmbedData) -> int:
    return sum(len(text or "") for text in _embed_texts(embed))


def _rebuild_embed(embed: EmbedData, texts) -> EmbedData:
    """Same embed with its texts replaced by the next values from `texts`, cut to Discord's limits."""

    def take(original: str | None, limit: int) -> str | None:
        value = next(texts)
        return None if original is None else truncate(value, limit)

    result = replace(
        embed,
        title=take(embed.title, TITLE),
        description=take(embed.description, DESCRIPTION),
        footer_text=take(embed.footer_text, FOOTER),
        author_name=take(embed.author_name, AUTHOR),
        fields=tuple(
            EmbedField(take(f.name, FIELD_NAME), take(f.value, FIELD_VALUE), f.inline) for f in embed.fields
        ),
    )
    excess = _embed_length(result) - EMBED_TOTAL
    if excess > 0 and result.description:
        result = replace(result, description=truncate(result.description, max(1, len(result.description) - excess)))
    while _embed_length(result) > EMBED_TOTAL and result.fields:
        result = replace(result, fields=result.fields[:-1])
    return result


async def render(
    msg: SourceMessage, link: Link, source_language: str | None, chain: TranslatorChain
) -> list[OutgoingPart]:
    """Translate one message for one link. Raises AllProvidersFailed."""
    if not (msg.content or msg.embeds or msg.attachments):
        return []
    raw = [msg.content] + [text or "" for embed in msg.embeds for text in _embed_texts(embed)]
    masked = [mask(text) for text in raw]
    texts = [text for text, _ in masked]
    if source_language != link.language:
        target = get_language(link.language)
        if target is None:
            raise ValueError(f"unknown language code {link.language!r}")
        source = get_language(source_language) if source_language else None
        texts = await chain.translate(texts, target, source)

    role = f"<@&{link.role_id}>"
    swap = {"@everyone": role, "@here": role} if link.role_id else {}
    # In the message text the role replaces @everyone only if the original really pinged.
    # Embed text never pings, so there the replacement is always safe.
    pinged = msg.mention_everyone and bool(link.role_id)
    restored = iter(
        [
            unmask(text, spans, swap if i > 0 or pinged else {}, original=before)
            for i, (text, (before, spans)) in enumerate(zip(texts, masked))
        ]
    )
    content = next(restored)
    embeds = tuple(_rebuild_embed(embed, restored) for embed in msg.embeds)

    chunks = split_text(content) or [""]
    last = len(chunks) - 1
    return [
        OutgoingPart(
            content=chunk,
            embeds=embeds if i == last else (),
            attachments=msg.attachments if i == last else (),
            notify=i == 0,
            ping_roles=msg.role_mention_ids + ((link.role_id,) if pinged else ()) if i == 0 else (),
        )
        for i, chunk in enumerate(chunks)
    ]
