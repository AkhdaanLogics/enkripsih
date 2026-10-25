"""
SQLCipher-backed local storage for Enkripsih.

The database key is generated on first use and protected with Windows DPAPI.
"""

import json
import ipaddress
import os
import secrets
import sqlite3 as plaintext_sqlite
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import sqlcipher3
import psycopg
from psycopg.rows import dict_row

from .key_protection import seal, unseal

DB_PATH = os.path.join(os.path.dirname(__file__), "enkripsih.db")
DB_KEY_PURPOSE = b"EKY1"
LEGACY_DPAPI_KEY_SUFFIX = ".key.dpapi"
PASSPHRASE_KEY_SUFFIX = ".key.argon2"
_KEY_CACHE: dict[tuple[str, str, int, int], bytes] = {}


class _PostgresCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, query: str, params=None):
        self._cursor.execute(query.replace("?", "%s"), params)
        return self

    def executemany(self, query: str, params_seq):
        self._cursor.executemany(query.replace("?", "%s"), params_seq)
        return self

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _PostgresConnection:
    def __init__(self, connection):
        self._connection = connection

    def execute(self, query: str, params=None):
        return self._connection.execute(query.replace("?", "%s"), params)

    def executemany(self, query: str, params_seq):
        return self._connection.cursor().executemany(
            query.replace("?", "%s"),
            params_seq,
        )

    def cursor(self):
        return _PostgresCursor(self._connection.cursor())

    def __getattr__(self, name):
        return getattr(self._connection, name)


def _postgres_connection_options(database_url: str) -> dict:
    options = psycopg.conninfo.conninfo_to_dict(database_url)
    host = options.get("host", "")
    local_host = host.lower() in {"", "localhost"}
    if host:
        try:
            local_host = local_host or ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass

    sslmode = options.get("sslmode", "")
    if local_host:
        if not sslmode:
            options["sslmode"] = "prefer"
    elif sslmode not in {"require", "verify-ca", "verify-full"}:
        options["sslmode"] = "require"

    return options


def database_needs_migration() -> bool:
    db_path = Path(DB_PATH)
    if not db_path.exists():
        return False
    with db_path.open("rb") as database_file:
        return database_file.read(16) == b"SQLite format 3\x00"


def database_needs_passphrase_setup() -> bool:
    return not Path(f"{DB_PATH}{PASSPHRASE_KEY_SUFFIX}").exists()


def _dpapi_transform(data: bytes, *, protect: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Enkripsi database otomatis saat ini hanya didukung di Windows.")

    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    source_buffer = ctypes.create_string_buffer(data, len(data))
    source = DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = DataBlob()
    flags = 0x1
    transform = (
        crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    )
    transform.restype = wintypes.BOOL

    if protect:
        transform.argtypes = [
            ctypes.POINTER(DataBlob), wintypes.LPCWSTR, ctypes.POINTER(DataBlob),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob),
        ]
        success = transform(ctypes.byref(source), "Enkripsih SQLCipher key", None, None, None, flags, ctypes.byref(result))
    else:
        transform.argtypes = [
            ctypes.POINTER(DataBlob), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(DataBlob),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob),
        ]
        description = wintypes.LPWSTR()
        success = transform(ctypes.byref(source), ctypes.byref(description), None, None, None, flags, ctypes.byref(result))
        if description:
            kernel32.LocalFree(ctypes.cast(description, ctypes.c_void_p))

    if not success:
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))


def _cipher_connection(path: str, key: bytes):
    conn = sqlcipher3.connect(path)
    try:
        conn.execute(f"PRAGMA key = \"x'{key.hex()}'\"")
        conn.execute("PRAGMA cipher_memory_security = ON")
        if not conn.execute("PRAGMA cipher_version").fetchone():
            raise RuntimeError("Driver database tidak mengaktifkan SQLCipher.")
        conn.row_factory = sqlcipher3.Row
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return conn
    except Exception:
        conn.close()
        raise


def _migrate_plaintext_database(db_path: Path, key: bytes):
    encrypted_tmp = db_path.with_name(f"{db_path.name}.{secrets.token_hex(6)}.encrypted")
    source = plaintext_sqlite.connect(str(db_path))
    try:
        target = _cipher_connection(str(encrypted_tmp), key)
        try:
            for statement in source.iterdump():
                target.execute(statement)
            target.commit()
            integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"Verifikasi database terenkripsi gagal: {integrity}")
        finally:
            target.close()
    finally:
        source.close()

    try:
        verified = _cipher_connection(str(encrypted_tmp), key)
        verified.close()
        os.replace(encrypted_tmp, db_path)
    finally:
        if encrypted_tmp.exists():
            encrypted_tmp.unlink()


def _passphrase_key_path() -> Path:
    return Path(f"{DB_PATH}{PASSPHRASE_KEY_SUFFIX}")


def _legacy_key_path() -> Path:
    return Path(f"{DB_PATH}{LEGACY_DPAPI_KEY_SUFFIX}")


def _validate_database_key(db_path: Path, key: bytes) -> None:
    if not db_path.exists():
        return
    with db_path.open("rb") as database_file:
        header = database_file.read(16)
    if header == b"SQLite format 3\x00":
        raise RuntimeError("Database masih plaintext dan perlu dimigrasikan.")
    connection = _cipher_connection(str(db_path), key)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Verifikasi database terenkripsi gagal: {integrity}")
    finally:
        connection.close()


def _store_passphrase_wrapped_key(key_path: Path, key: bytes, passphrase: str) -> None:
    temporary = key_path.with_name(f"{key_path.name}.{secrets.token_hex(6)}.tmp")
    try:
        temporary.write_bytes(seal(key, passphrase, DB_KEY_PURPOSE))
        os.replace(temporary, key_path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _ensure_encrypted_database(
    confirm_plaintext_migration: bool,
    passphrase: str,
) -> bytes:
    db_path = Path(DB_PATH)
    key_path = _passphrase_key_path()
    legacy_key_path = _legacy_key_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if key_path.exists():
        stat = key_path.stat()
        cache_key = (str(db_path.resolve()), passphrase, stat.st_mtime_ns, stat.st_size)
        cached_key = _KEY_CACHE.get(cache_key)
        if cached_key is not None:
            if db_path.exists() and database_needs_migration():
                if not confirm_plaintext_migration:
                    raise RuntimeError(
                        "Migrasi database belum selesai. Jalankan run.py dan konfirmasi MIGRATE."
                    )
                _migrate_plaintext_database(db_path, cached_key)
            return cached_key

        key = unseal(key_path.read_bytes(), passphrase, DB_KEY_PURPOSE)
        if len(key) != 32:
            raise RuntimeError("Kunci database tidak valid; database tidak dibuka.")
        if db_path.exists():
            if database_needs_migration():
                if not confirm_plaintext_migration:
                    raise RuntimeError(
                        "Migrasi database belum selesai. Jalankan run.py dan konfirmasi MIGRATE."
                    )
                _migrate_plaintext_database(db_path, key)
            else:
                _validate_database_key(db_path, key)
        if legacy_key_path.exists():
            legacy_key_path.unlink()
        stat = key_path.stat()
        _KEY_CACHE[(str(db_path.resolve()), passphrase, stat.st_mtime_ns, stat.st_size)] = key
        return key

    if legacy_key_path.exists():
        key = _dpapi_transform(legacy_key_path.read_bytes(), protect=False)
        if len(key) != 32:
            raise RuntimeError("Kunci database DPAPI lama tidak valid.")
        if db_path.exists() and database_needs_migration():
            if not confirm_plaintext_migration:
                raise RuntimeError(
                    "Migrasi database belum selesai. Jalankan run.py dan konfirmasi MIGRATE."
                )
            _migrate_plaintext_database(db_path, key)
        _validate_database_key(db_path, key)
        _store_passphrase_wrapped_key(key_path, key, passphrase)
        _validate_database_key(db_path, unseal(key_path.read_bytes(), passphrase, DB_KEY_PURPOSE))
        legacy_key_path.unlink()
        stat = key_path.stat()
        _KEY_CACHE[(str(db_path.resolve()), passphrase, stat.st_mtime_ns, stat.st_size)] = key
        return key

    if db_path.exists() and not database_needs_migration():
        raise RuntimeError(
            "Database terenkripsi tetapi file kunci tidak ditemukan. "
            "Pulihkan backup database beserta file kunci yang cocok."
        )
    if db_path.exists() and not confirm_plaintext_migration:
        raise RuntimeError(
            "Database lama belum terenkripsi. Buat backup terpisah, lalu konfirmasi migrasi."
        )

    key = secrets.token_bytes(32)
    _store_passphrase_wrapped_key(key_path, key, passphrase)
    stat = key_path.stat()
    _KEY_CACHE[(str(db_path.resolve()), passphrase, stat.st_mtime_ns, stat.st_size)] = key
    try:
        if db_path.exists():
            _migrate_plaintext_database(db_path, key)
        else:
            connection = _cipher_connection(str(db_path), key)
            connection.close()
    except Exception:
        key_path.unlink(missing_ok=True)
        _KEY_CACHE.pop((str(db_path.resolve()), passphrase, stat.st_mtime_ns, stat.st_size), None)
        raise
    return key


def get_connection(passphrase: str | None = None):
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        connection_options = _postgres_connection_options(database_url)
        connection = psycopg.connect(
            **connection_options,
            connect_timeout=8,
            row_factory=dict_row,
        )
        return _PostgresConnection(connection)

    database_passphrase = passphrase or os.environ.get("ENKRIPSIH_DB_PASSPHRASE", "")
    if len(database_passphrase) < 16:
        raise RuntimeError(
            "ENKRIPSIH_DB_PASSPHRASE belum diatur atau kurang dari 16 karakter."
        )
    key = _ensure_encrypted_database(
        confirm_plaintext_migration=os.environ.get("ENKRIPSIH_CONFIRM_DB_MIGRATION") == "yes",
        passphrase=database_passphrase,
    )
    conn = _cipher_connection(DB_PATH, key)
    conn.row_factory = sqlcipher3.Row
    return conn


@contextmanager
def _managed_connection():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(
    *,
    confirm_plaintext_migration: bool = False,
    passphrase: str | None = None,
):
    if os.environ.get("DATABASE_URL"):
        conn = get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    rank TEXT NOT NULL,
                    role TEXT NOT NULL,
                    face_enrolled INTEGER DEFAULT 0,
                    face_template TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    sender_id TEXT NOT NULL,
                    sender_name TEXT NOT NULL,
                    target_unit TEXT NOT NULL,
                    recipient_id TEXT NOT NULL,
                    paket TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                ALTER TABLE messages
                ADD COLUMN IF NOT EXISTS recipient_id TEXT NOT NULL DEFAULT ''
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_created_at
                ON messages (created_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_recipient_id
                ON messages (recipient_id)
            """)
            conn.execute("""
                UPDATE messages
                SET status = 'LEGACY'
                WHERE recipient_id = '' AND status != 'BURNED'
            """)
            conn.execute("""
                UPDATE messages SET status = 'LOCKED'
                WHERE status = 'UNLOCKED' AND recipient_id != ''
            """)
            conn.execute("UPDATE messages SET paket = '' WHERE status = 'BURNED'")
            for column in (
                "expected_response", "plaintext", "subject", "priority",
                "challenge_letters", "challenge_symbols", "decrypted_at",
            ):
                conn.execute(f"ALTER TABLE messages DROP COLUMN IF EXISTS {column}")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recipient_keys (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    salt TEXT NOT NULL,
                    verifier TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS receiver_accounts (
                    recipient_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    must_change_password INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    category TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token TEXT PRIMARY KEY,
                    expires_at DOUBLE PRECISION NOT NULL,
                    principal_id TEXT NOT NULL DEFAULT 'CMD-01',
                    role TEXT NOT NULL DEFAULT 'COMMANDER',
                    must_change_password INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                ALTER TABLE auth_sessions
                ADD COLUMN IF NOT EXISTS principal_id TEXT NOT NULL DEFAULT 'CMD-01'
            """)
            conn.execute("""
                ALTER TABLE auth_sessions
                ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'COMMANDER'
            """)
            conn.execute("""
                ALTER TABLE auth_sessions
                ADD COLUMN IF NOT EXISTS must_change_password INTEGER NOT NULL DEFAULT 0
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_auth_sessions_principal
                ON auth_sessions (principal_id)
            """)
            conn.execute("""
                INSERT INTO users (
                    id, name, rank, role, face_enrolled, face_template, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO NOTHING
            """, (
                "CMD-01",
                "Kolonel M. Haris",
                "Panglima Operasi Siber Intelijen",
                "COMMANDER",
                0,
                None,
                datetime.now().isoformat(),
            ))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return

    database_passphrase = passphrase or os.environ.get("ENKRIPSIH_DB_PASSPHRASE", "")
    if len(database_passphrase) < 16:
        raise RuntimeError(
            "Passphrase database belum diatur atau kurang dari 16 karakter."
        )
    key = _ensure_encrypted_database(confirm_plaintext_migration, database_passphrase)
    conn = _cipher_connection(DB_PATH, key)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        rank TEXT NOT NULL,
        role TEXT NOT NULL,
        face_enrolled INTEGER DEFAULT 0,
        face_template TEXT,
        created_at TEXT NOT NULL
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        sender_id TEXT NOT NULL,
        sender_name TEXT NOT NULL,
        target_unit TEXT NOT NULL,
        recipient_id TEXT NOT NULL,
        paket TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)
    message_columns = {
        row["name"] for row in cursor.execute("PRAGMA table_info(messages)").fetchall()
    }
    if "recipient_id" not in message_columns:
        cursor.execute("""
        ALTER TABLE messages ADD COLUMN recipient_id TEXT NOT NULL DEFAULT ''
        """)
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_messages_created_at
    ON messages (created_at)
    """)
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_messages_recipient_id
    ON messages (recipient_id)
    """)
    cursor.execute("""
    UPDATE messages SET status = 'LEGACY'
    WHERE recipient_id = '' AND status != 'BURNED'
    """)
    cursor.execute("""
    UPDATE messages SET status = 'LOCKED'
    WHERE status = 'UNLOCKED' AND recipient_id != ''
    """)
    cursor.execute("UPDATE messages SET paket = '' WHERE status = 'BURNED'")
    message_columns = {
        row["name"] for row in cursor.execute("PRAGMA table_info(messages)").fetchall()
    }
    for column in (
        "expected_response", "plaintext", "subject", "priority",
        "challenge_letters", "challenge_symbols", "decrypted_at",
    ):
        if column in message_columns:
            cursor.execute(f"ALTER TABLE messages DROP COLUMN {column}")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS recipient_keys (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        salt TEXT NOT NULL,
        verifier TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        category TEXT NOT NULL,
        status TEXT NOT NULL,
        message TEXT NOT NULL
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS auth_sessions (
        token TEXT PRIMARY KEY,
        expires_at REAL NOT NULL,
        principal_id TEXT NOT NULL DEFAULT 'CMD-01',
        role TEXT NOT NULL DEFAULT 'COMMANDER',
        must_change_password INTEGER NOT NULL DEFAULT 0
    )
    """)
    auth_session_columns = {
        row["name"] for row in cursor.execute("PRAGMA table_info(auth_sessions)").fetchall()
    }
    for column, declaration in (
        ("principal_id", "TEXT NOT NULL DEFAULT 'CMD-01'"),
        ("role", "TEXT NOT NULL DEFAULT 'COMMANDER'"),
        ("must_change_password", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if column not in auth_session_columns:
            cursor.execute(f"ALTER TABLE auth_sessions ADD COLUMN {column} {declaration}")
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_auth_sessions_principal
    ON auth_sessions (principal_id)
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS receiver_accounts (
        recipient_id TEXT PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        password_salt TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        must_change_password INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """)
    cursor.execute("SELECT COUNT(*) AS count FROM users WHERE id = 'CMD-01'")
    if cursor.fetchone()["count"] == 0:
        cursor.execute("""
        INSERT INTO users (id, name, rank, role, face_enrolled, face_template, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "CMD-01",
            "Kolonel M. Haris",
            "Panglima Operasi Siber Intelijen",
            "COMMANDER",
            0,
            None,
            datetime.now().isoformat(),
        ))

    conn.commit()
    conn.close()


def save_auth_session(
    token: str,
    expires_at: float,
    principal_id: str = "CMD-01",
    role: str = "COMMANDER",
    must_change_password: bool = False,
) -> None:
    with _managed_connection() as conn:
        conn.execute(
            """
            INSERT INTO auth_sessions (
                token, expires_at, principal_id, role, must_change_password
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (token, expires_at, principal_id, role, int(must_change_password)),
        )


def get_auth_session(token: str) -> dict | None:
    with _managed_connection() as conn:
        row = conn.execute(
            """
            SELECT token, expires_at, principal_id, role, must_change_password
            FROM auth_sessions WHERE token = ?
            """,
            (token,),
        ).fetchone()
        return dict(row) if row else None


def get_auth_session_expiry(token: str) -> float | None:
    session = get_auth_session(token)
    return float(session["expires_at"]) if session else None


def delete_auth_session(token: str) -> None:
    with _managed_connection() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))


def delete_auth_sessions_for_principal(principal_id: str) -> None:
    with _managed_connection() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE principal_id = ?", (principal_id,))


def update_auth_session_password_change(token: str, required: bool) -> None:
    with _managed_connection() as conn:
        conn.execute(
            "UPDATE auth_sessions SET must_change_password = ? WHERE token = ?",
            (int(required), token),
        )


def update_auth_session_expiry(token: str, expires_at: float) -> None:
    with _managed_connection() as conn:
        conn.execute(
            "UPDATE auth_sessions SET expires_at = ? WHERE token = ?",
            (expires_at, token),
        )


def provision_receiver_account(
    recipient_id: str,
    username: str,
    password_salt: str,
    password_hash: str,
) -> bool:
    with _managed_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO receiver_accounts (
                recipient_id, username, password_salt, password_hash,
                must_change_password, created_at
            ) VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT (recipient_id) DO UPDATE SET
                username = excluded.username,
                password_salt = excluded.password_salt,
                password_hash = excluded.password_hash,
                must_change_password = 1,
                created_at = excluded.created_at
        """, (
            recipient_id, username, password_salt, password_hash,
            datetime.now().isoformat(),
        ))
        return cursor.rowcount == 1


def get_receiver_account(username: str) -> dict | None:
    with _managed_connection() as conn:
        row = conn.execute("""
            SELECT recipient_id, username, password_salt, password_hash,
                   must_change_password
            FROM receiver_accounts WHERE LOWER(username) = ?
        """, (username.lower(),)).fetchone()
        return dict(row) if row else None


def change_receiver_password(
    recipient_id: str,
    password_salt: str,
    password_hash: str,
) -> None:
    with _managed_connection() as conn:
        conn.execute("""
            UPDATE receiver_accounts
            SET password_salt = ?, password_hash = ?, must_change_password = 0
            WHERE recipient_id = ?
        """, (password_salt, password_hash, recipient_id))


def log_event(category: str, status: str, message: str):
    with _managed_connection() as conn:
        conn.execute("""
        INSERT INTO audit_logs (timestamp, category, status, message)
        VALUES (?, ?, ?, ?)
        """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), category, status, message))


def get_logs(limit: int = 50):
    with _managed_connection() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()]


def save_message(msg_data: dict):
    with _managed_connection() as conn:
        conn.execute("""
        INSERT INTO messages (
            id, sender_id, sender_name, target_unit, recipient_id, paket,
            status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            msg_data["id"], msg_data["sender_id"], msg_data["sender_name"],
            msg_data["target_unit"], msg_data["recipient_id"],
            msg_data["paket"], msg_data.get("status", "LOCKED"),
            msg_data.get("created_at", datetime.now().isoformat()),
        ))


def register_recipient_key(
    recipient_id: str,
    name: str,
    salt: str,
    verifier: str,
    username: str | None = None,
    password_salt: str | None = None,
    password_hash: str | None = None,
) -> bool:
    with _managed_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO recipient_keys (id, name, salt, verifier, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (name) DO NOTHING
        """, (recipient_id, name, salt, verifier, datetime.now().isoformat()))
        if cursor.rowcount != 1:
            return False
        if username and password_salt and password_hash:
            conn.execute("""
                INSERT INTO receiver_accounts (
                    recipient_id, username, password_salt, password_hash,
                    must_change_password, created_at
                ) VALUES (?, ?, ?, ?, 1, ?)
            """, (
                recipient_id, username, password_salt, password_hash,
                datetime.now().isoformat(),
            ))
        return True


def get_recipient_keys():
    with _managed_connection() as conn:
        return [dict(row) for row in conn.execute("""
            SELECT id, name, salt FROM recipient_keys ORDER BY name
        """).fetchall()]


def get_recipient_key(recipient_id: str):
    with _managed_connection() as conn:
        row = conn.execute("""
            SELECT id, name, salt, verifier FROM recipient_keys WHERE id = ?
        """, (recipient_id,)).fetchone()
        return dict(row) if row else None


def get_messages():
    with _managed_connection() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM messages ORDER BY created_at DESC"
        ).fetchall()]


def get_message_by_id(msg_id: str):
    with _managed_connection() as conn:
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()
        return dict(row) if row else None


def burn_message(msg_id: str):
    with _managed_connection() as conn:
        conn.execute("""
        UPDATE messages
        SET status = 'BURNED',
            paket = ''
        WHERE id = ?
        """, (msg_id,))


def get_commander_profile(user_id: str = "CMD-01"):
    with _managed_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def update_face_template(user_id: str, template_data: list):
    with _managed_connection() as conn:
        conn.execute("""
        UPDATE users SET face_enrolled = 1, face_template = ? WHERE id = ?
        """, (json.dumps(template_data), user_id))
