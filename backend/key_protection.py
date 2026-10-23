"""Passphrase-based key wrapping using Argon2id and authenticated encryption."""

import secrets
import struct

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HEADER = struct.Struct(">4sBIII16s12s")
FORMAT_VERSION = 1
SALT_SIZE = 16
NONCE_SIZE = 12
KEY_SIZE = 32
TIME_COST = 3
MEMORY_COST_KIB = 65536
PARALLELISM = 4
MIN_MEMORY_COST_KIB = 8192
MAX_MEMORY_COST_KIB = 262144
MAX_TIME_COST = 6
MAX_PARALLELISM = 8


def _derive_key(passphrase: str, salt: bytes, time_cost: int, memory_cost_kib: int, parallelism: int) -> bytes:
    if len(passphrase) < 16:
        raise ValueError("Passphrase harus minimal 16 karakter.")
    return hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=time_cost,
        memory_cost=memory_cost_kib,
        parallelism=parallelism,
        hash_len=KEY_SIZE,
        type=Type.ID,
    )


def seal(data: bytes, passphrase: str, purpose: bytes) -> bytes:
    if len(purpose) != 4:
        raise ValueError("Penanda tujuan enkripsi harus tepat 4 byte.")
    if len(passphrase) < 16:
        raise ValueError("Passphrase harus minimal 16 karakter.")
    salt = secrets.token_bytes(SALT_SIZE)
    nonce = secrets.token_bytes(NONCE_SIZE)
    header = HEADER.pack(
        purpose,
        FORMAT_VERSION,
        TIME_COST,
        MEMORY_COST_KIB,
        PARALLELISM,
        salt,
        nonce,
    )
    key = _derive_key(passphrase, salt, TIME_COST, MEMORY_COST_KIB, PARALLELISM)
    return header + AESGCM(key).encrypt(nonce, data, header)


def unseal(envelope: bytes, passphrase: str, expected_purpose: bytes) -> bytes:
    if len(expected_purpose) != 4 or len(envelope) < HEADER.size + 16:
        raise ValueError("Envelope enkripsi tidak valid atau tidak lengkap.")

    purpose, version, time_cost, memory_cost_kib, parallelism, salt, nonce = HEADER.unpack(
        envelope[:HEADER.size]
    )
    if purpose != expected_purpose or version != FORMAT_VERSION:
        raise ValueError("Format atau tujuan file terenkripsi tidak cocok.")
    if (
        time_cost < 1
        or time_cost > MAX_TIME_COST
        or memory_cost_kib < MIN_MEMORY_COST_KIB
        or memory_cost_kib > MAX_MEMORY_COST_KIB
        or parallelism < 1
        or parallelism > MAX_PARALLELISM
        or memory_cost_kib < 8 * parallelism
    ):
        raise ValueError("Parameter Argon2id pada file tidak valid.")

    header = envelope[:HEADER.size]
    key = _derive_key(passphrase, salt, time_cost, memory_cost_kib, parallelism)
    return AESGCM(key).decrypt(nonce, envelope[HEADER.size:], header)
