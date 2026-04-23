"""Security helpers for password hashes, opaque tokens, and secret storage."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet

PASSWORD_PREFIX = "scrypt"
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return (
        f"{PASSWORD_PREFIX}${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}$"
        f"{base64.urlsafe_b64encode(salt).decode('ascii')}$"
        f"{base64.urlsafe_b64encode(derived).decode('ascii')}"
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        prefix, raw_n, raw_r, raw_p, raw_salt, raw_hash = stored_hash.split("$", maxsplit=5)
    except ValueError:
        return False
    if prefix != PASSWORD_PREFIX:
        return False
    salt = base64.urlsafe_b64decode(raw_salt.encode("ascii"))
    expected = base64.urlsafe_b64decode(raw_hash.encode("ascii"))
    candidate = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=int(raw_n),
        r=int(raw_r),
        p=int(raw_p),
        dklen=len(expected),
    )
    return hmac.compare_digest(candidate, expected)


def new_opaque_token(*, bytes_length: int = 32) -> str:
    return secrets.token_urlsafe(bytes_length)


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _fernet(secret_key: str) -> Fernet:
    derived_key = hashlib.sha256(secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(derived_key))


def encrypt_text(secret_key: str, plaintext: str) -> str:
    return _fernet(secret_key).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_text(secret_key: str, ciphertext: str) -> str:
    return _fernet(secret_key).decrypt(ciphertext.encode("ascii")).decode("utf-8")
