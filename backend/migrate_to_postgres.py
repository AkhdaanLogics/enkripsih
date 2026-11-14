"""Copy the local ENKRIPSIH database to an empty PostgreSQL database."""

import argparse
import getpass
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

from . import database, secure_backup

TABLE_COLUMNS = {
    "users": (
        "id",
        "name",
        "rank",
        "role",
        "created_at",
    ),
    "messages": (
        "id",
        "sender_id",
        "sender_name",
        "target_unit",
        "recipient_id",
        "paket",
        "status",
        "created_at",
    ),
    "recipient_keys": ("id", "name", "salt", "verifier", "created_at"),
    "receiver_accounts": (
        "recipient_id",
        "username",
        "password_salt",
        "password_hash",
        "must_change_password",
        "created_at",
    ),
    "audit_logs": ("id", "timestamp", "category", "status", "message"),
}


def _normalize_record(table: str, row, known_recipient_ids: set[str] | None = None) -> dict:
    record = dict(row)
    if table == "messages":
        record["recipient_id"] = record.get("recipient_id") or ""
        if record["status"] == "BURNED":
            record["paket"] = ""
        elif (
            not record["recipient_id"]
            or (
                known_recipient_ids is not None
                and record["recipient_id"] not in known_recipient_ids
            )
        ):
            record["status"] = "LEGACY"
        elif record["status"] == "UNLOCKED":
            record["status"] = "LOCKED"
    return record


def _open_local_database(source_path: Path, passphrase: str | None):
    source_bytes = source_path.read_bytes()
    if source_bytes.startswith(secure_backup.LEGACY_MAGIC):
        plaintext_snapshot = secure_backup._restore_legacy_dpapi_backup(source_bytes)
        secure_backup._verify_sqlite_bytes(plaintext_snapshot)
        source = sqlite3.connect(":memory:")
        source.deserialize(plaintext_snapshot)
        source.row_factory = sqlite3.Row
        return source

    is_plaintext = source_bytes.startswith(b"SQLite format 3\x00")

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
            table: target.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]  # nosec B608 — table from hardcoded list
            for table in (
                "messages", "recipient_keys", "receiver_accounts", "audit_logs"
            )
        }
        if any(counts_before.values()):
            raise RuntimeError(
                "Database PostgreSQL tujuan tidak kosong. Migrasi dibatalkan agar tidak "
                "menggabungkan atau menggandakan data."
            )
        existing_users = target.execute("SELECT id FROM users").fetchall()
        if any(row["id"] != "CMD-01" for row in existing_users):
            raise RuntimeError(
                "Database tujuan sudah memiliki profil tambahan. Gunakan database PostgreSQL baru."
            )

        recipient_columns = {
            row["name"] for row in source.execute("PRAGMA table_info(recipient_keys)")
        }
        known_recipient_ids = (
            {
                row["id"]
                for row in source.execute("SELECT id FROM recipient_keys").fetchall()
            }
            if "id" in recipient_columns
            else set()
        )

        expected_counts: dict[str, int] = {}
        for table, columns in TABLE_COLUMNS.items():
            placeholders = ", ".join("?" for _ in columns)
            column_list = ", ".join(columns)
            try:
                source_columns = {
                    row["name"] for row in source.execute("PRAGMA table_info(?)", (table,))
                }
                if not source_columns:
                    source_columns = {
                        row["column_name"]
                        for row in source.execute("""
                            SELECT column_name FROM information_schema.columns
                            WHERE table_name = ?
                        """, (table,))
                    }
            except sqlite3.Error:
                source_columns = set()
            available_columns = [column for column in columns if column in source_columns]
            if not available_columns:
                expected_counts[table] = 0
                if table == "users":
                    target.execute("DELETE FROM users WHERE id = ?", ("CMD-01",))
                continue
            rows = source.execute(
                f"SELECT {', '.join(available_columns)} FROM {table}"  # nosec B608 — table/columns from hardcoded TABLE_COLUMNS allowlist
            ).fetchall()
            expected_counts[table] = len(rows)
            if table == "users" and not any(row["id"] == "CMD-01" for row in rows):
                target.execute("DELETE FROM users WHERE id = ?", ("CMD-01",))
            if not rows:
                continue

            insert = f"INSERT INTO {table} ({column_list}) VALUES ({placeholders})"  # nosec B608 — table/columns from hardcoded TABLE_COLUMNS allowlist
            if table == "users":
                insert += """
                    ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    rank = EXCLUDED.rank,
                    role = EXCLUDED.role,
                    created_at = EXCLUDED.created_at
                """
            values = []
            for row in rows:
                record = _normalize_record(
                    table,
                    row,
                    known_recipient_ids if table == "messages" else None,
                )
                values.append(tuple(record[column] for column in columns))
            target.executemany(insert, values)

        target.execute("""
            SELECT setval(
                pg_get_serial_sequence('audit_logs', 'id'),
                COALESCE(MAX(id), 1),
                MAX(id) IS NOT NULL
            )
            FROM audit_logs
        """)
        actual_counts = {
            table: target.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]  # nosec B608 — table from hardcoded TABLE_COLUMNS allowlist
            for table in TABLE_COLUMNS
        }

        if actual_counts != expected_counts:
            raise RuntimeError(
                f"Jumlah record tidak cocok; sumber={expected_counts}, tujuan={actual_counts}."
            )
        target.commit()
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
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Pindahkan data lokal ENKRIPSIH ke database PostgreSQL kosong."
    )
    parser.add_argument("--source", type=Path, default=Path(database.DB_PATH))
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("Atur DATABASE_URL ke connection string PostgreSQL tujuan.")

    source_bytes = args.source.read_bytes()
    encrypted_legacy_backup = source_bytes.startswith(secure_backup.LEGACY_MAGIC)
    plaintext_source = source_bytes.startswith(b"SQLite format 3\x00")
    source_passphrase = None
    if not plaintext_source and not encrypted_legacy_backup:
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
