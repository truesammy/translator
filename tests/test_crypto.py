from cryptography.fernet import Fernet

from translator_bot.crypto import decrypt, encrypt


def test_round_trip():
    k = Fernet.generate_key()
    assert decrypt(k, encrypt(k, "abc:fx")) == "abc:fx"


def test_ciphertext_does_not_contain_plaintext():
    assert b"abc:fx" not in encrypt(Fernet.generate_key(), "abc:fx")
