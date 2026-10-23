import asyncio
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from unittest.mock import patch

from fastapi import HTTPException
from cryptography.exceptions import InvalidTag

from backend import database
from backend import secure_backup
from backend.crypto_engine import (
    SYMBOL_MAP,
    calculate_response_symbols,
    decrypt_intel_package,
    response_to_string,
)

_IMPORT_DB = tempfile.TemporaryDirectory()
database.DB_PATH = str(Path(_IMPORT_DB.name) / "import.db")
from backend import main


class MessageTransmissionTests(unittest.TestCase):
    def test_main_app_does_not_load_optional_opencv_on_import(self):
        self.assertNotIn("backend.face_auth", sys.modules)
        self.assertNotIn("cv2", sys.modules)

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "messages.db"
        self.db_path_patch = patch.object(database, "DB_PATH", str(self.db_path))
        self.db_path_patch.start()
        self.database_passphrase = "a-distinct-test-database-passphrase"
        self.passphrase_patch = patch.dict(
            os.environ,
            {"ENKRIPSIH_DB_PASSPHRASE": self.database_passphrase},
        )
        self.passphrase_patch.start()
        database.init_db()

    def tearDown(self):
        self.passphrase_patch.stop()
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def test_send_persists_encrypted_message_and_correct_token_opens_it(self):
        plaintext = "Pesan uji transmisi rahasia"
        request = main.SendMessageRequest(
            target_unit="Tim Uji",
            subject="Uji penyimpanan",
            priority="CONFIDENTIAL",
            plaintext=plaintext,
        )

        result = asyncio.run(main.send_message_endpoint(request))
        stored = database.get_message_by_id(result["message_id"])
        api_detail = main.get_message_detail(result["message_id"])
        api_list = main.get_all_messages()["messages"]

        self.assertTrue(result["success"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored["status"], "LOCKED")
        self.assertIsNone(stored["plaintext"])
        self.assertTrue(stored["paket"])
        self.assertNotIn("expected_response", stored)
        self.assertNotIn(plaintext, stored["paket"])
        self.assertTrue(api_detail["encrypted"])
        self.assertNotIn("paket", api_detail)
        self.assertNotIn("expected_response", api_detail)
        self.assertNotIn("plaintext", api_detail)
        self.assertNotIn("paket", api_list[0])
        self.assertNotIn("expected_response", api_list[0])

        challenge_indices = [SYMBOL_MAP[letter] for letter in result["challenge_letters"]]
        token = response_to_string(calculate_response_symbols(challenge_indices))["letters"]
        decrypted = decrypt_intel_package(stored["paket"], token)
        self.assertTrue(decrypted["success"])
        self.assertEqual(decrypted["plaintext"], plaintext)

        wrong_token = ("T" if token[0] != "T" else "C") + token[1:]
        rejected = decrypt_intel_package(stored["paket"], wrong_token)
        self.assertFalse(rejected["success"])

    def test_blank_message_is_not_transmitted(self):
        request = main.SendMessageRequest(
            target_unit="Tim Uji",
            subject="Pesan kosong",
            priority="CONFIDENTIAL",
            plaintext="   ",
        )

        with self.assertRaises(HTTPException) as error:
            asyncio.run(main.send_message_endpoint(request))

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(database.get_messages(), [])

    def test_failed_decryption_does_not_log_submitted_token(self):
        request = main.SendMessageRequest(
            target_unit="Tim Uji",
            subject="Uji token",
            priority="CONFIDENTIAL",
            plaintext="Pesan uji",
        )
        sent = asyncio.run(main.send_message_endpoint(request))
        stored = database.get_message_by_id(sent["message_id"])
        challenge_indices = [SYMBOL_MAP[letter] for letter in sent["challenge_letters"]]
        valid_token = response_to_string(
            calculate_response_symbols(challenge_indices)
        )["letters"]
        submitted_token = ("T" if valid_token[0] != "T" else "C") + valid_token[1:]

        result = asyncio.run(
            main.decrypt_message_endpoint(
                sent["message_id"],
                main.DecryptRequest(token=submitted_token),
            )
        )

        self.assertFalse(result["success"])
        logs = database.get_logs()
        self.assertTrue(logs)
        self.assertNotIn(submitted_token, logs[0]["message"])
        self.assertNotIn("/api/logs", {route.path for route in main.app.routes})

    def test_legacy_database_migration_removes_saved_response_tokens(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.db"
        wrapped_key = Path(f"{legacy_path}.key.argon2")
        database.DB_PATH = str(legacy_path)
        connection = sqlite3.connect(legacy_path)
        try:
            connection.execute("""
                CREATE TABLE messages (
                    id TEXT PRIMARY KEY,
                    sender_id TEXT NOT NULL,
                    sender_name TEXT NOT NULL,
                    target_unit TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    challenge_letters TEXT NOT NULL,
                    challenge_symbols TEXT NOT NULL,
                    expected_response TEXT NOT NULL,
                    paket TEXT NOT NULL,
                    status TEXT NOT NULL,
                    plaintext TEXT,
                    created_at TEXT NOT NULL,
                    decrypted_at TEXT
                )
            """)
            connection.execute("""
                CREATE TABLE users (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, rank TEXT NOT NULL,
                    role TEXT NOT NULL, face_enrolled INTEGER DEFAULT 0,
                    face_template TEXT, created_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
                    category TEXT NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL
                )
            """)
            connection.execute("""
                INSERT INTO messages VALUES (
                    'MSG-OLD', 'CMD-01', 'Pengirim', 'Penerima', 'Subjek',
                    'CONFIDENTIAL', 'TCXS', '△ ○ ✕ □', 'SECRETRESPONSE',
                    'ciphertext', 'LOCKED', NULL, '2026-10-23T00:00:00', NULL
                )
            """)
            connection.commit()
        finally:
            connection.close()

        database.init_db(confirm_plaintext_migration=True)
        migrated = database.get_message_by_id("MSG-OLD")

        self.assertEqual(migrated["paket"], "ciphertext")
        self.assertNotIn("expected_response", migrated)
        self.assertTrue(wrapped_key.exists())
        with legacy_path.open("rb") as encrypted_file:
            self.assertNotEqual(encrypted_file.read(16), b"SQLite format 3\x00")
        database.DB_PATH = str(self.db_path)

    def test_api_requires_password_session_and_logout_revokes_it(self):
        password = "enkripsih-test-password-2026"
        with patch.dict(os.environ, {"ENKRIPSIH_PASSWORD": password}):
            with TestClient(main.app) as client:
                self.assertEqual(client.get("/api/messages").status_code, 401)
                self.assertEqual(
                    client.post("/api/auth/login", json={"password": "incorrect"}).status_code,
                    401,
                )
                login = client.post("/api/auth/login", json={"password": password})
                self.assertEqual(login.status_code, 200)
                self.assertTrue(client.cookies.get(main.SESSION_COOKIE))
                send = client.post("/api/messages/send", json={
                    "target_unit": "Tim Uji",
                    "subject": "Uji autentikasi",
                    "priority": "CONFIDENTIAL",
                    "plaintext": "Isi rahasia uji",
                })
                self.assertEqual(send.status_code, 200)
                detail = client.get(f"/api/messages/{send.json()['message_id']}")
                self.assertEqual(detail.status_code, 200)
                self.assertTrue(detail.json()["encrypted"])
                self.assertNotIn("paket", detail.json())
                self.assertNotIn("expected_response", detail.json())
                rejected_origin = client.post(
                    "/api/messages/send",
                    headers={"Origin": "http://attacker.invalid"},
                    json={
                        "target_unit": "Tim Uji",
                        "subject": "Origin lintas situs",
                        "priority": "CONFIDENTIAL",
                        "plaintext": "Tidak boleh masuk",
                    },
                )
                self.assertEqual(rejected_origin.status_code, 403)
                self.assertEqual(client.get("/api/logs").status_code, 404)
                self.assertEqual(client.post("/api/auth/logout").status_code, 200)
                self.assertEqual(client.get("/api/messages").status_code, 401)

    def test_database_requires_passphrase_and_rejects_wrong_passphrase(self):
        key_path = Path(f"{self.db_path}.key.argon2")
        self.assertTrue(key_path.exists())
        with self.assertRaises(InvalidTag):
            database._ensure_encrypted_database(False, "wrong-database-passphrase")

        key = database._ensure_encrypted_database(False, self.database_passphrase)
        connection = database._cipher_connection(str(self.db_path), key)
        try:
            self.assertEqual(
                connection.execute("PRAGMA integrity_check").fetchone()[0],
                "ok",
            )
        finally:
            connection.close()

    def test_postgres_adapter_translates_qmark_placeholders(self):
        class FakeCursor:
            def execute(self, query, params):
                self.query = query
                self.params = params

            def executemany(self, query, params_seq):
                self.query = query
                self.params_seq = list(params_seq)

        class FakeConnection:
            def execute(self, query, params):
                self.query = query
                self.params = params
                return self

            def cursor(self):
                self.last_cursor = FakeCursor()
                return self.last_cursor

        from backend.database import _PostgresConnection

        raw_connection = FakeConnection()
        connection = _PostgresConnection(raw_connection)
        connection.execute("SELECT * FROM messages WHERE id = ?", ("MSG-1",))
        self.assertEqual(
            raw_connection.query,
            "SELECT * FROM messages WHERE id = %s",
        )
        self.assertEqual(raw_connection.params, ("MSG-1",))
        connection.cursor().execute(
            "SELECT * FROM users WHERE id = ?",
            ("CMD-01",),
        )
        self.assertEqual(
            raw_connection.last_cursor.query,
            "SELECT * FROM users WHERE id = %s",
        )
        connection.executemany(
            "INSERT INTO messages (id) VALUES (?)",
            [("MSG-1",), ("MSG-2",)],
        )
        self.assertEqual(
            raw_connection.last_cursor.query,
            "INSERT INTO messages (id) VALUES (%s)",
        )
        self.assertEqual(
            raw_connection.last_cursor.params_seq,
            [("MSG-1",), ("MSG-2",)],
        )

    def test_postgres_connection_options_allow_local_ssl_settings_but_require_remote_tls(self):
        self.assertEqual(
            database._postgres_connection_options(
                "postgresql://demo:secret@localhost:5432/enkripsih?sslmode=disable"
            )["sslmode"],
            "disable",
        )
        self.assertEqual(
            database._postgres_connection_options(
                "postgresql://demo:secret@127.0.0.1:5432/enkripsih"
            )["sslmode"],
            "prefer",
        )
        self.assertEqual(
            database._postgres_connection_options(
                "postgresql://demo:secret@db.example.com:5432/enkripsih?sslmode=disable"
            )["sslmode"],
            "require",
        )

    def test_auth_sessions_persist_and_expire_in_database(self):
        token = "test-session-token"
        expires_at = 2_000_000_000.0
        database.save_auth_session(token, expires_at)
        self.assertEqual(database.get_auth_session_expiry(token), expires_at)
        database.delete_auth_session(token)
        self.assertIsNone(database.get_auth_session_expiry(token))

    def test_encrypted_backup_restores_database_and_wrapped_key(self):
        backup_path = Path(self.temp_dir.name) / "database.backup.enc"
        restored_path = Path(self.temp_dir.name) / "restored.db"
        backup_passphrase = "a-separate-test-backup-passphrase"
        secure_backup.create_backup(
            self.db_path,
            backup_path,
            backup_passphrase,
            self.database_passphrase,
        )
        secure_backup.restore_backup(
            backup_path,
            restored_path,
            backup_passphrase,
            self.database_passphrase,
        )

        self.assertTrue(Path(f"{restored_path}.key.argon2").exists())
        with restored_path.open("rb") as database_file:
            self.assertNotEqual(database_file.read(16), b"SQLite format 3\x00")
        from backend.key_protection import unseal

        restored_key = unseal(
            Path(f"{restored_path}.key.argon2").read_bytes(),
            self.database_passphrase,
            database.DB_KEY_PURPOSE,
        )
        connection = database._cipher_connection(str(restored_path), restored_key)
        try:
            self.assertEqual(
                connection.execute("PRAGMA integrity_check").fetchone()[0],
                "ok",
            )
        finally:
            connection.close()

        with self.assertRaises(InvalidTag):
            secure_backup.restore_backup(
                backup_path,
                Path(self.temp_dir.name) / "wrong-restore.db",
                "wrong-backup-passphrase",
                self.database_passphrase,
            )

    def test_plaintext_database_backup_is_encrypted_and_restorable(self):
        source = Path(self.temp_dir.name) / "legacy-plaintext.db"
        backup = Path(self.temp_dir.name) / "legacy.backup.enc"
        restored = Path(self.temp_dir.name) / "legacy-restored.db"
        connection = sqlite3.connect(source)
        try:
            connection.execute("CREATE TABLE demo (value TEXT NOT NULL)")
            connection.execute("INSERT INTO demo VALUES ('synthetic demo content')")
            connection.commit()
        finally:
            connection.close()

        backup_passphrase = "a-passphrase-for-legacy-backup"
        secure_backup.create_backup(source, backup, backup_passphrase)
        self.assertNotIn(b"synthetic demo content", backup.read_bytes())
        secure_backup.restore_backup(backup, restored, backup_passphrase)

        connection = sqlite3.connect(restored)
        try:
            self.assertEqual(
                connection.execute("SELECT value FROM demo").fetchone()[0],
                "synthetic demo content",
            )
        finally:
            connection.close()

    @unittest.skipUnless(os.name == "nt", "Legacy DPAPI migration is Windows-only.")
    def test_dpapi_key_is_rewrapped_with_argon2id_and_old_file_removed(self):
        legacy_path = Path(self.temp_dir.name) / "dpapi-legacy.db"
        legacy_key_path = Path(f"{legacy_path}.key.dpapi")
        passphrase_key_path = Path(f"{legacy_path}.key.argon2")
        database_key = os.urandom(32)
        connection = database._cipher_connection(str(legacy_path), database_key)
        try:
            connection.execute("CREATE TABLE retained (value TEXT NOT NULL)")
            connection.execute("INSERT INTO retained VALUES ('kept')")
            connection.commit()
        finally:
            connection.close()
        legacy_key_path.write_bytes(
            database._dpapi_transform(database_key, protect=True)
        )

        database.DB_PATH = str(legacy_path)
        database.init_db(passphrase=self.database_passphrase)
        self.assertTrue(passphrase_key_path.exists())
        self.assertFalse(legacy_key_path.exists())
        connection = database.get_connection(self.database_passphrase)
        try:
            self.assertEqual(
                connection.execute("SELECT value FROM retained").fetchone()["value"],
                "kept",
            )
        finally:
            connection.close()
        database.DB_PATH = str(self.db_path)


if __name__ == "__main__":
    unittest.main()
