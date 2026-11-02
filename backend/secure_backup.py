"""Create and restore passphrase-encrypted backups of the local database."""

import argparse
import getpass
import os
import secrets
import sqlite3
import struct
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import sqlcipher3

from .database import DB_PATH, PASSPHRASE_KEY_SUFFIX, _cipher_connection, _dpapi_transform
from .key_protection import unseal, seal

BACKUP_PURPOSE = b"EBK1"
ARCHIVE_HEADER = struct.Struct(">4sQQ")
ARCHIVE_MAGIC = b"EDB1"
DATABASE_KEY_PURPOSE = b"EKY1"
LEGACY_MAGIC = b"ENKRIPSIH-DB-BACKUP\x00\x01"
LEGACY_NONCE_SIZE = 12


def _archive(database: bytes, wrapped_key: bytes) -> bytes:
    return ARCHIVE_HEADER.pack(ARCHIVE_MAGIC, len(database), len(wrapped_key)) + database + wrapped_key


def _unpack_archive(data: bytes) -> tuple[bytes, bytes]:
    if len(data) < ARCHIVE_HEADER.size:
        raise ValueError("Isi backup tidak lengkap.")
    magic, database_size, key_size = ARCHIVE_HEADER.unpack(data[:ARCHIVE_HEADER.size])
    if magic != ARCHIVE_MAGIC:
        raise ValueError("Format isi backup tidak dikenal.")
    database_start = ARCHIVE_HEADER.size
    key_start = database_start + database_size
    if key_start + key_size != len(data):
        raise ValueError("Panjang data dalam backup tidak cocok.")
    return data[database_start:key_start], data[key_start:]


def _database_snapshot(source_path: Path, database_passphrase: str | None) -> bytes:
    if not source_path.is_file():
        raise FileNotFoundError(f"Database sumber tidak ditemukan: {source_path}")

    wal_path = Path(f"{source_path}-wal")
    if wal_path.exists() and wal_path.stat().st_size:
        raise RuntimeError("Database memiliki WAL aktif. Hentikan server sebelum membuat backup.")

    with source_path.open("rb") as database_file:
        header = database_file.read(16)

    key_path = Path(f"{source_path}{PASSPHRASE_KEY_SUFFIX}")
    legacy_key_path = Path(f"{source_path}.key.dpapi")
    if header == b"SQLite format 3\x00":
        source = sqlite3.connect(str(source_path), timeout=0)
        try:
            source.execute("BEGIN EXCLUSIVE")
            integrity = source.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"Verifikasi database sumber gagal: {integrity}")
            database_bytes = source_path.read_bytes()
            return _archive(database_bytes, b"")
        finally:
            source.rollback()
            source.close()

    if not database_passphrase or len(database_passphrase) < 16:
        raise ValueError("Passphrase database diperlukan untuk backup database terenkripsi.")
    if key_path.exists():
        wrapped_key = key_path.read_bytes()
        key = unseal(wrapped_key, database_passphrase, DATABASE_KEY_PURPOSE)
    elif legacy_key_path.exists():
        wrapped_key = b""
        key = _dpapi_transform(legacy_key_path.read_bytes(), protect=False)
    else:
        raise FileNotFoundError("File kunci database tidak ditemukan.")

    source = _cipher_connection(str(source_path), key)
    try:
        source.execute("BEGIN EXCLUSIVE")
        integrity = source.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Verifikasi database terenkripsi gagal: {integrity}")
        database_bytes = source_path.read_bytes()
        if not wrapped_key:
            wrapped_key = seal(key, database_passphrase, DATABASE_KEY_PURPOSE)
        return _archive(database_bytes, wrapped_key)
    finally:
        source.rollback()
        source.close()


def _verify_sqlite_bytes(data: bytes) -> None:
    if not data.startswith(b"SQLite format 3\x00"):
        raise ValueError("Data hasil dekripsi bukan database SQLite plaintext.")
    connection = sqlite3.connect(":memory:")
    try:
        if hasattr(connection, "deserialize"):
            connection.deserialize(data)
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"Verifikasi database hasil dekripsi gagal: {integrity}")
        else:
            # Older SQLite builds lack Connection.deserialize(); verify the
            # header fields that every SQLite database must satisfy.
            if len(data) < 100:
                raise ValueError("Ukuran database tidak valid.")
            page_size = int.from_bytes(data[16:18], "big")
            if page_size < 512 or page_size > 65536 or (page_size & (page_size - 1)) != 0:
                raise ValueError("Ukuran halaman SQLite tidak valid.")
            if data[28] not in (0x00, 0x02):
                raise ValueError("Tekstur halaman SQLite tidak valid.")
    finally:
        connection.close()


def _write_new_file(destination: Path, content: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("xb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.rename(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def create_backup(
    source_path: Path,
    destination: Path,
    backup_passphrase: str,
    database_passphrase: str | None = None,
) -> None:
    if len(backup_passphrase) < 16:
        raise ValueError("Passphrase backup harus minimal 16 karakter.")
    archive = _database_snapshot(source_path, database_passphrase)
    _write_new_file(destination, seal(archive, backup_passphrase, BACKUP_PURPOSE))


def _restore_legacy_dpapi_backup(data: bytes) -> bytes:
    minimum_size = len(LEGACY_MAGIC) + 4 + LEGACY_NONCE_SIZE + 16
    if len(data) < minimum_size:
        raise ValueError("Backup DPAPI lama tidak lengkap.")

    offset = len(LEGACY_MAGIC)
    wrapped_key_size = struct.unpack(">I", data[offset:offset + 4])[0]
    offset += 4
    key_end = offset + wrapped_key_size
    nonce_end = key_end + LEGACY_NONCE_SIZE
    if wrapped_key_size == 0 or nonce_end >= len(data):
        raise ValueError("Header backup DPAPI lama rusak.")

    wrapped_key = data[offset:key_end]
    nonce = data[key_end:nonce_end]
    aad = data[:nonce_end]
    key = _dpapi_transform(wrapped_key, protect=False)
    return AESGCM(key).decrypt(nonce, data[nonce_end:], aad)


def restore_backup(
    backup_path: Path,
    destination: Path,
    backup_passphrase: str | None = None,
    database_passphrase: str | None = None,
) -> None:
    data = backup_path.read_bytes()
    if data.startswith(LEGACY_MAGIC):
        database = _restore_legacy_dpapi_backup(data)
        wrapped_key = b""
    else:
        if backup_passphrase is None or len(backup_passphrase) < 16:
            raise ValueError("Passphrase backup harus minimal 16 karakter.")
        database, wrapped_key = _unpack_archive(unseal(data, backup_passphrase, BACKUP_PURPOSE))

    database_key_path = Path(f"{destination}{PASSPHRASE_KEY_SUFFIX}")
    if database.startswith(b"SQLite format 3\x00"):
        if wrapped_key:
            raise ValueError("Backup plaintext memiliki metadata kunci yang tidak semestinya.")
        _verify_sqlite_bytes(database)
        _write_new_file(destination, database)
        return

    if not wrapped_key or not database_passphrase or len(database_passphrase) < 16:
        raise ValueError("Passphrase database diperlukan untuk memulihkan database terenkripsi.")
    key = unseal(wrapped_key, database_passphrase, DATABASE_KEY_PURPOSE)
    temporary_database = destination.with_name(f".{destination.name}.{secrets.token_hex(8)}.tmp")
    temporary_key = database_key_path.with_name(f".{database_key_path.name}.{secrets.token_hex(8)}.tmp")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temporary_database.open("xb") as output:
            output.write(database)
        with temporary_key.open("xb") as output:
            output.write(wrapped_key)
        connection = _cipher_connection(str(temporary_database), key)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"Verifikasi database hasil pemulihan gagal: {integrity}")
        finally:
            connection.close()
        os.rename(temporary_key, database_key_path)
        try:
            os.rename(temporary_database, destination)
        except Exception:
            database_key_path.unlink()
            raise
    finally:
        if temporary_database.exists():
            temporary_database.unlink()
        if temporary_key.exists():
            temporary_key.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backup database ENKRIPSIH terenkripsi dengan Argon2id."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    backup_parser = commands.add_parser("backup", help="Buat file backup terenkripsi.")
    backup_parser.add_argument("--source", type=Path, default=Path(DB_PATH))
    backup_parser.add_argument("--output", type=Path, required=True)

    restore_parser = commands.add_parser("restore", help="Pulihkan backup ke database SQLite baru.")
    restore_parser.add_argument("--source", type=Path, required=True)
    restore_parser.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "backup":
        database_passphrase = getpass.getpass(
            "Passphrase database (kosongkan jika database masih plaintext): "
        )
        backup_passphrase = getpass.getpass("Passphrase baru untuk backup: ")
        confirmation = getpass.getpass("Ulangi passphrase backup: ")
        if backup_passphrase != confirmation:
            raise SystemExit("Passphrase tidak cocok.")
        create_backup(
            args.source,
            args.output,
            backup_passphrase,
            database_passphrase or None,
        )
        print(f"Backup terenkripsi dibuat: {args.output}")
    else:
        if args.source.read_bytes().startswith(LEGACY_MAGIC):
            restore_backup(args.source, args.output)
            print("Backup lama DPAPI dipulihkan; diperlukan akun Windows pembuat backup.")
        else:
            backup_passphrase = getpass.getpass("Passphrase backup: ")
            database_passphrase = getpass.getpass(
                "Passphrase database (kosongkan untuk backup plaintext): "
            )
            restore_backup(
                args.source,
                args.output,
                backup_passphrase,
                database_passphrase or None,
            )
        print(f"Database dipulihkan dan lolos integrity_check: {args.output}")


if __name__ == "__main__":
    main()
