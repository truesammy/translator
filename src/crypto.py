from cryptography.fernet import Fernet


def encrypt(fernet_key: bytes, plaintext: str) -> bytes:
    return Fernet(fernet_key).encrypt(plaintext.encode())


def decrypt(fernet_key: bytes, token: bytes) -> str:
    return Fernet(fernet_key).decrypt(token).decode()
