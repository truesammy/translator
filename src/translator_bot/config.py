from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    token: str
    fernet_key: bytes
    db_path: Path


def load_config(env: Mapping[str, str]) -> Config:
    for name in ("DISCORD_TOKEN", "ENCRYPTION_KEY"):
        if not env.get(name):
            raise ConfigError(f"{name} is not set")
    fernet_key = env["ENCRYPTION_KEY"].encode()
    try:
        Fernet(fernet_key)
    except ValueError:
        raise ConfigError("ENCRYPTION_KEY is not a valid Fernet key") from None
    return Config(env["DISCORD_TOKEN"], fernet_key, Path(env.get("DATABASE_PATH") or "data/bot.db"))
