"""Copy the local ENKRIPSIH database to an empty PostgreSQL database."""

import argparse
import getpass
import os
import sqlite3
from pathlib import Path

from . import database

TABLE_COLUMNS = {
    "users": (
        "id",
        "name",
        "rank",
        "role",
        "face_enrolled",
        "face_template",
        "created_at",
    ),
    "messages": (
        "id",
        "sender_id",
        "sender_name",
        "target_unit",
        "subject",
        "priority",
        "challenge_letters",
        "challenge_symbols",
        "paket",
        "status",
        "plaintext",
        "created_at",
        "decrypted_at",
    ),
    "audit_logs": ("id", "timestamp", "category", "status", "message"),
}


def _open_local_database(source_path: Path, passphrase: str | None):
    with source_path.open("rb") as source_file:
        is_plaintext = source_file.read(16) == b"SQLite format 3\x00"

    if is_plaintext:
        source = sqlite3.connect(f"{source_path.resolve().as_uri()}?mode=ro", uri=True)
        source.row_factory = sqlite3.Row
        return source

    if not passphrase or len(passphrase) < 16:
        raise ValueError("Passphrase database lokal harus minimal 16 karakter.")

    original_path = database.DB_PATH
    try:
        database.DB_PATH = str(source_path)
        key = database._ensure_encrypted_database(False, passphrase)
    finally:
        database.DB_PATH = original_path
    return database._cipher_connection(str(source_path), key)


def migrate(source_path: Path, database_url: str, source_passphrase: str | None) -> dict[str, int]:
    source = _open_local_database(source_path, source_passphrase)
    original_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    target = None
    try:
        database.init_db()
        target = database.get_connection()

        counts_before = {
            table: target.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]
            for table in ("messages", "audit_logs")
        }
        if counts_before["messages"] or counts_before["audit_logs"]:
            raise RuntimeError(
                "Database PostgreSQL tujuan tidak kosong. Migrasi dibatalkan agar tidak "
                "menggabungkan atau menggandakan data."
            )
        existing_users = target.execute("SELECT id FROM users").fetchall()
        if any(row["id"] != "CMD-01" for row in existing_users):
            raise RuntimeError(
                "Database tujuan sudah memiliki profil tambahan. Gunakan database PostgreSQL baru."
            )

        expected_counts: dict[str, int] = {}
        for table, columns in TABLE_COLUMNS.items():
            placeholders = ", ".join("?" for _ in columns)
            column_list = ", ".join(columns)
            rows = source.execute(f"SELECT {column_list} FROM {table}").fetchall()
            expected_counts[table] = len(rows)
            if not rows:
                continue

            insert = (
                f"INSERT INTO {table} ({column_list}) VALUES ({placeholders})"
            )
            if table == "users":
                insert += """
                    ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    rank = EXCLUDED.rank,
                    role = EXCLUDED.role,
                    face_enrolled = EXCLUDED.face_enrolled,
                    face_template = EXCLUDED.face_template,
                    created_at = EXCLUDED.created_at
                """
            target.executemany(
                insert,
                [tuple(row[column] for column in columns) for row in rows],
            )

        target.execute("""
            SELECT setval(
                pg_get_serial_sequence('audit_logs', 'id'),
                COALESCE(MAX(id), 1),
                MAX(id) IS NOT NULL
            )
            FROM audit_logs
        """)
        target.commit()

        actual_counts = {
            table: target.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]
            for table in TABLE_COLUMNS
        }
        if actual_counts != expected_counts:
            raise RuntimeError(
                f"Jumlah record tidak cocok; sumber={expected_counts}, tujuan={actual_counts}."
            )
        return actual_counts
    except Exception:
        if target is not None:
            target.rollback()
        raise
    finally:
        source.close()
        if target is not None:
            target.close()
        if original_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_url


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pindahkan data lokal ENKRIPSIH ke database PostgreSQL kosong."
    )
    parser.add_argument("--source", type=Path, default=Path(database.DB_PATH))
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("Atur DATABASE_URL ke connection string PostgreSQL tujuan.")

    with args.source.open("rb") as source_file:
        plaintext_source = source_file.read(16) == b"SQLite format 3\x00"
    source_passphrase = None
    if not plaintext_source:
        source_passphrase = getpass.getpass("Passphrase database lokal: ")

    confirmation = input(
        "Pastikan server berhenti, backup terverifikasi, dan PostgreSQL tujuan kosong. "
        "Ketik MIGRATE untuk lanjut: "
    )
    if confirmation != "MIGRATE":
        raise SystemExit("Migrasi dibatalkan.")

    counts = migrate(args.source, database_url, source_passphrase)
    print(f"Migrasi selesai dan jumlah record cocok: {counts}")
    print("Database lokal tidak dihapus dan tetap menjadi salinan sumber.")


if __name__ == "__main__":
    main()
