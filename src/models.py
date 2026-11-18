from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class EmbedField:
    name: str
    value: str
    inline: bool


@dataclass(frozen=True)
class EmbedData:
    title: str | None = None
    description: str | None = None
    url: str | None = None
    color: int | None = None
    timestamp: datetime | None = None
    footer_text: str | None = None
    footer_icon_url: str | None = None
    author_name: str | None = None
    author_url: str | None = None
    author_icon_url: str | None = None
    image_url: str | None = None
    thumbnail_url: str | None = None
    fields: tuple[EmbedField, ...] = ()


@dataclass(frozen=True)
class Attachment:
    filename: str
    url: str
    size: int


@dataclass(frozen=True)
class SourceMessage:
    id: int
    guild_id: int
    channel_id: int
    author_name: str
    author_avatar_url: str | None
    content: str
    embeds: tuple[EmbedData, ...] = ()
    attachments: tuple[Attachment, ...] = ()
    from_own_webhook: bool = False
    # What actually notified in the original. Text alone proves nothing: "@everyone" from
    # someone without the permission is just text there, and must stay text in the targets.
    mention_everyone: bool = False
    role_mention_ids: tuple[int, ...] = ()
    user_mention_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class Link:
    guild_id: int
    source_channel_id: int
    target_channel_id: int
    language: str
    role_id: int | None


@dataclass(frozen=True)
class OutgoingPart:
    content: str
    embeds: tuple[EmbedData, ...]
    attachments: tuple[Attachment, ...]
    notify: bool
    ping_roles: tuple[int, ...] = ()  # roles this part may notify, only when `notify` is set
    ping_users: tuple[int, ...] = ()  # users this part may notify, only when `notify` is set
    buttons: tuple[str, ...] = ()  # custom ids of flag buttons
