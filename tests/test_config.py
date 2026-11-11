from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from translator_bot.config import ConfigError, load_config

KEY = Fernet.generate_key().decode()


def test_load_config_reads_all_values():
    cfg = load_config({"DISCORD_TOKEN": "t", "ENCRYPTION_KEY": KEY, "DATABASE_PATH": "x/y.db"})
    assert (cfg.token, cfg.fernet_key, cfg.db_path) == ("t", KEY.encode(), Path("x/y.db"))


def test_db_path_defaults():
    assert load_config({"DISCORD_TOKEN": "t", "ENCRYPTION_KEY": KEY}).db_path == Path("data/bot.db")


def test_empty_db_path_uses_default():
    cfg = load_config({"DISCORD_TOKEN": "t", "ENCRYPTION_KEY": KEY, "DATABASE_PATH": ""})
    assert cfg.db_path == Path("data/bot.db")


@pytest.mark.parametrize("missing", ["DISCORD_TOKEN", "ENCRYPTION_KEY"])
def test_missing_variable_is_named(missing):
    env = {"DISCORD_TOKEN": "t", "ENCRYPTION_KEY": KEY}
    del env[missing]
    with pytest.raises(ConfigError, match=missing):
        load_config(env)


def test_invalid_fernet_key_rejected():
    with pytest.raises(ConfigError, match="ENCRYPTION_KEY"):
        load_config({"DISCORD_TOKEN": "t", "ENCRYPTION_KEY": "not-a-key"})
