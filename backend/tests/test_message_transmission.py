import asyncio
import base64
import hashlib
import json
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
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend import database
from backend import migrate_to_postgres
from backend import secure_backup

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

    def register_test_recipient(self, name="Tim Uji"):
        response = main.register_recipient(main.RegisterRecipientRequest(
            name=name,
            salt="11" * 16,
            verifier="22" * 32,
        ))
        return response["recipient_id"]

    @staticmethod
    def fake_envelope():
        return json.dumps({
            "v": 1,
            "salt": "AAAAAAAAAAAAAAAAAAAAAA",
            "iv": "AAAAAAAAAAAAAAAA",
            "ciphertext": "AAAAAAAAAAAAAAAAAAAAAA",
        })

    def test_message_storage_contains_ciphertext_only_and_no_removed_metadata(self):
        recipient_id = self.register_test_recipient()
        paket = self.fake_envelope()
        result = asyncio.run(main.send_message_endpoint(main.SendMessageRequest(
            recipient_id=recipient_id,
            paket=paket,
        )))
        stored = database.get_message_by_id(result["message_id"])
        api_detail = main.get_message_detail(result["message_id"])
        api_list = main.get_all_messages()["messages"]

        self.assertTrue(result["success"])
        self.assertEqual(stored["status"], "LOCKED")
        self.assertEqual(stored["paket"], paket)
        self.assertNotIn("plaintext", stored)
        self.assertNotIn("subject", stored)
        self.assertNotIn("priority", stored)
        self.assertTrue(api_detail["encrypted"])
        self.assertNotIn("paket", api_detail)
        self.assertNotIn("subject", api_detail)
        self.assertNotIn("priority", api_detail)
        self.assertNotIn("paket", api_list[0])

        with database._managed_connection() as connection:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(messages)").fetchall()
            }
        self.assertNotIn("plaintext", columns)
        self.assertNotIn("subject", columns)
        self.assertNotIn("priority", columns)

    def test_passkey_challenge_is_saved_with_ciphertext_summary_only(self):
        recipient_id = self.register_test_recipient("Passkey Receiver")
        envelope = json.loads(self.fake_envelope())
        envelope["v"] = 5
        envelope["challenge"] = "TCXS"
        paket = json.dumps(envelope)
        result = asyncio.run(main.send_message_endpoint(main.SendMessageRequest(
            recipient_id=recipient_id,
            paket=paket,
        )))

        stored = database.get_message_by_id(result["message_id"])
        summary = main.get_all_messages()["messages"][0]
        ciphertext = main.get_message_ciphertext(result["message_id"])
        self.assertEqual(stored["paket"], paket)
        self.assertEqual(summary["passkey_challenge"], "TCXS")
        self.assertEqual(summary["encryption_version"], 5)
        self.assertNotIn("passkey", summary)
        self.assertNotIn("plaintext", stored)
        self.assertEqual(ciphertext["paket"], paket)

        invalid = json.loads(paket)
        invalid["challenge"] = "TCX"
        with self.assertRaises(HTTPException) as error:
            asyncio.run(main.send_message_endpoint(main.SendMessageRequest(
                recipient_id=recipient_id,
                paket=json.dumps(invalid),
            )))
        self.assertEqual(error.exception.status_code, 400)

    def test_recipient_keys_are_unique_and_verifiers_are_not_listed(self):
        first = main.register_recipient(main.RegisterRecipientRequest(
            name="Anggota Terdaftar",
            salt="11" * 16,
            verifier="22" * 32,
        ))
        with self.assertRaises(HTTPException) as error:
            main.register_recipient(main.RegisterRecipientRequest(
                name="Anggota Terdaftar",
                salt="33" * 16,
                verifier="44" * 32,
            ))

        self.assertEqual(error.exception.status_code, 409)
        listed = main.list_recipients()["recipients"]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], first["recipient_id"])
        self.assertNotIn("verifier", listed[0])

    def test_message_database_indexes_and_legacy_row_normalization(self):
        with database._managed_connection() as connection:
            indexes = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                ).fetchall()
            }
        self.assertIn("idx_messages_created_at", indexes)
        self.assertIn("idx_messages_recipient_id", indexes)

        legacy = migrate_to_postgres._normalize_record("messages", {
            "id": "old-locked",
            "status": "LOCKED",
            "paket": "old-ciphertext",
        })
        missing_recipient_key = migrate_to_postgres._normalize_record(
            "messages",
            {
                "id": "old-recipient",
                "recipient_id": "missing-member",
                "status": "LOCKED",
                "paket": "old-ciphertext",
            },
            set(),
        )
        burned = migrate_to_postgres._normalize_record("messages", {
            "id": "old-burned",
            "recipient_id": "",
            "status": "BURNED",
            "paket": "DESTROYED",
        })
        unlocked = migrate_to_postgres._normalize_record("messages", {
            "id": "new-unlocked",
            "recipient_id": "member-1",
            "status": "UNLOCKED",
            "paket": "ciphertext",
        })
        self.assertEqual(legacy["status"], "LEGACY")
        self.assertEqual(legacy["recipient_id"], "")
        self.assertEqual(missing_recipient_key["status"], "LEGACY")
        self.assertEqual(burned["paket"], "")
        self.assertEqual(unlocked["status"], "LOCKED")

    def test_postgres_migration_rolls_back_before_committing_count_mismatch(self):
        source = sqlite3.connect(":memory:")
        source.row_factory = sqlite3.Row
        source.executescript("""
            CREATE TABLE users (
                id TEXT PRIMARY KEY, name TEXT, rank TEXT, role TEXT,
                face_enrolled INTEGER, face_template TEXT, created_at TEXT
            );
            INSERT INTO users VALUES (
                'CMD-01', 'Komandan', 'Rank', 'COMMANDER', 0, NULL, '2026-10-24'
            );
            CREATE TABLE messages (
                id TEXT, sender_id TEXT, sender_name TEXT, target_unit TEXT,
                recipient_id TEXT, paket TEXT, status TEXT, created_at TEXT
            );
            INSERT INTO messages VALUES (
                'MSG-1', 'CMD-01', 'Komandan', 'Anggota', 'member-1',
                '{"v":1}', 'LOCKED', '2026-10-24'
            );
            CREATE TABLE recipient_keys (
                id TEXT, name TEXT, salt TEXT, verifier TEXT, created_at TEXT
            );
            CREATE TABLE audit_logs (
                id INTEGER, timestamp TEXT, category TEXT, status TEXT, message TEXT
            );
        """)

        class Result:
            def __init__(self, rows):
                self.rows = rows

            def fetchone(self):
                return self.rows[0] if self.rows else None

            def fetchall(self):
                return self.rows

        class Target:
            def __init__(self):
                self.committed = False
                self.rolled_back = False

            def execute(self, query, params=None):
                if query.startswith("SELECT COUNT(*) AS count FROM "):
                    return Result([{"count": 0}])
                if query == "SELECT id FROM users":
                    return Result([{"id": "CMD-01"}])
                return Result([])

            def executemany(self, query, params):
                return None

            def commit(self):
                self.committed = True

            def rollback(self):
                self.rolled_back = True

            def close(self):
                pass

        target = Target()
        try:
            with (
                patch.object(migrate_to_postgres, "_open_local_database", return_value=source),
                patch.object(database, "init_db"),
                patch.object(database, "get_connection", return_value=target),
                patch.dict(os.environ, {}, clear=False),
            ):
                with self.assertRaisesRegex(RuntimeError, "Jumlah record tidak cocok"):
                    migrate_to_postgres.migrate(
                        Path("unused-source.db"),
                        "postgresql://test.invalid/database",
                        None,
                    )
        finally:
            source.close()

        self.assertFalse(target.committed)
        self.assertTrue(target.rolled_back)

    def test_registered_key_verifier_and_aes_gcm_package_round_trip(self):
        secret = "B" * 32
        recipient_salt = os.urandom(16)
        verifier = hashlib.pbkdf2_hmac(
            "sha256",
            secret.encode(),
            b"enkripsih:recipient:v1:" + recipient_salt,
            600_000,
            32,
        ).hex()
        registration = main.register_recipient(main.RegisterRecipientRequest(
            name="Anggota Aman",
            salt=recipient_salt.hex(),
            verifier=verifier,
        ))
        recipient_id = registration["recipient_id"]
        self.assertTrue(main.verify_recipient_key(
            recipient_id,
            main.VerifyRecipientKeyRequest(verifier=verifier),
        )["valid"])
        self.assertFalse(main.verify_recipient_key(
            recipient_id,
            main.VerifyRecipientKeyRequest(verifier="00" * 32),
        )["valid"])

        plaintext = "Isi contoh untuk uji round-trip"
        salt = os.urandom(16)
        iv = os.urandom(12)
        key = hashlib.pbkdf2_hmac(
            "sha256",
            secret.encode(),
            b"enkripsih:message:v1:" + salt,
            600_000,
            32,
        )
        ciphertext = AESGCM(key).encrypt(
            iv,
            plaintext.encode(),
            f"enkripsih:v1:{recipient_id}".encode(),
        )
        encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip("=")
        paket = json.dumps({
            "v": 1,
            "salt": encode(salt),
            "iv": encode(iv),
            "ciphertext": encode(ciphertext),
        })
        sent = asyncio.run(main.send_message_endpoint(main.SendMessageRequest(
            recipient_id=recipient_id,
            paket=paket,
        )))
        stored_packet = main.get_message_ciphertext(sent["message_id"])
        self.assertEqual(stored_packet["paket"], paket)
        self.assertEqual(
            AESGCM(key).decrypt(
                iv,
                ciphertext,
                f"enkripsih:v1:{recipient_id}".encode(),
            ).decode(),
            plaintext,
        )
        wrong_key = hashlib.pbkdf2_hmac(
            "sha256",
            ("C" * 32).encode(),
            b"enkripsih:message:v1:" + salt,
            600_000,
            32,
        )
        with self.assertRaises(InvalidTag):
            AESGCM(wrong_key).decrypt(
                iv,
                ciphertext,
                f"enkripsih:v1:{recipient_id}".encode(),
            )

    def test_startup_removes_legacy_decrypted_text_and_burn_markers(self):
        recipient_id = self.register_test_recipient()
        sent_ids = []
        for _ in range(2):
            sent = asyncio.run(main.send_message_endpoint(main.SendMessageRequest(
                recipient_id=recipient_id,
                paket=self.fake_envelope(),
            )))
            sent_ids.append(sent["message_id"])

        with database._managed_connection() as connection:
            connection.execute("ALTER TABLE messages ADD COLUMN plaintext TEXT")
            connection.execute("ALTER TABLE messages ADD COLUMN subject TEXT")
            connection.execute("ALTER TABLE messages ADD COLUMN priority TEXT")
            connection.execute("ALTER TABLE messages ADD COLUMN challenge_letters TEXT")
            connection.execute("ALTER TABLE messages ADD COLUMN challenge_symbols TEXT")
            connection.execute("ALTER TABLE messages ADD COLUMN decrypted_at TEXT")
            connection.execute("""
                UPDATE messages
                SET status = 'UNLOCKED', plaintext = ?, subject = ?,
                    priority = ?, challenge_letters = ?, challenge_symbols = ?,
                    decrypted_at = ?
                WHERE id = ?
            """, (
                "plaintext lama", "subject rahasia", "TOP SECRET",
                "TCXS", "△ ○ ✕ □", "2026-10-23T12:00:00", sent_ids[0],
            ))
            connection.execute("""
                UPDATE messages
                SET status = 'BURNED', plaintext = ?
                WHERE id = ?
            """, ("marker lama", sent_ids[1]))

        database.init_db()
        unlocked = database.get_message_by_id(sent_ids[0])
        burned = database.get_message_by_id(sent_ids[1])

        self.assertEqual(unlocked["status"], "LOCKED")
        self.assertNotIn("plaintext", unlocked)
        self.assertNotIn("decrypted_at", unlocked)
        self.assertEqual(burned["status"], "BURNED")
        self.assertNotIn("plaintext", burned)
        with database._managed_connection() as connection:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(messages)").fetchall()
            }
        for removed in (
            "plaintext", "subject", "priority", "challenge_letters",
            "challenge_symbols", "decrypted_at",
        ):
            self.assertNotIn(removed, columns)

    def test_blank_message_is_not_transmitted(self):
        recipient_id = self.register_test_recipient()
        request = main.SendMessageRequest(
            recipient_id=recipient_id,
            paket=" ",
        )

        with self.assertRaises(HTTPException) as error:
            asyncio.run(main.send_message_endpoint(request))

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(database.get_messages(), [])

    def test_invalid_ciphertext_is_rejected_without_logging_payload(self):
        recipient_id = self.register_test_recipient()
        with self.assertRaises(HTTPException) as error:
            asyncio.run(main.send_message_endpoint(main.SendMessageRequest(
                recipient_id=recipient_id,
                paket="not-json",
            )))
        self.assertEqual(error.exception.status_code, 400)
        self.assertNotIn("not-json", str(database.get_logs()))

    def test_burning_message_clears_ciphertext(self):
        recipient_id = self.register_test_recipient()
        sent = asyncio.run(main.send_message_endpoint(main.SendMessageRequest(
            recipient_id=recipient_id,
            paket=self.fake_envelope(),
        )))

        asyncio.run(main.burn_message_endpoint(sent["message_id"]))

        stored = database.get_message_by_id(sent["message_id"])
        self.assertEqual(stored["status"], "BURNED")
        self.assertEqual(stored["paket"], "")
        with self.assertRaises(HTTPException) as error:
            main.get_message_ciphertext(sent["message_id"])
        self.assertEqual(error.exception.status_code, 410)

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
                    'ciphertext', 'UNLOCKED', 'teks plaintext lama',
                    '2026-10-23T00:00:00', '2026-10-23T01:00:00'
                )
            """)
            connection.commit()
        finally:
            connection.close()

        database.init_db(confirm_plaintext_migration=True)
        migrated = database.get_message_by_id("MSG-OLD")

        self.assertEqual(migrated["paket"], "ciphertext")
        self.assertNotIn("expected_response", migrated)
        self.assertEqual(migrated["status"], "LEGACY")
        self.assertNotIn("plaintext", migrated)
        self.assertNotIn("decrypted_at", migrated)
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
                registered = client.post("/api/recipients/register", json={
                    "name": "Anggota API",
                    "salt": "11" * 16,
                    "verifier": "22" * 32,
                })
                self.assertEqual(registered.status_code, 200)
                recipient_id = registered.json()["recipient_id"]
                send = client.post("/api/messages/send", json={
                    "recipient_id": recipient_id,
                    "paket": self.fake_envelope(),
                })
                self.assertEqual(send.status_code, 200)
                detail = client.get(f"/api/messages/{send.json()['message_id']}")
                self.assertEqual(detail.status_code, 200)
                self.assertTrue(detail.json()["encrypted"])
                self.assertNotIn("paket", detail.json())
                self.assertNotIn("expected_response", detail.json())
                self.assertNotIn("subject", detail.json())
                self.assertNotIn("priority", detail.json())
                packet = client.get(
                    f"/api/messages/{send.json()['message_id']}/ciphertext"
                )
                self.assertEqual(packet.status_code, 200)
                self.assertEqual(packet.json()["paket"], self.fake_envelope())
                detail_after = client.get(f"/api/messages/{send.json()['message_id']}")
                self.assertEqual(detail_after.json()["status"], "LOCKED")
                rejected_origin = client.post(
                    "/api/messages/send",
                    headers={"Origin": "http://attacker.invalid"},
                    json={
                        "recipient_id": recipient_id,
                        "paket": self.fake_envelope(),
                    },
                )
                self.assertEqual(rejected_origin.status_code, 403)
                self.assertEqual(client.get("/api/logs").status_code, 404)
                self.assertEqual(
                    client.post(
                        f"/api/messages/{send.json()['message_id']}/burn"
                    ).status_code,
                    200,
                )
                self.assertEqual(
                    client.get(
                        f"/api/messages/{send.json()['message_id']}/ciphertext"
                    ).status_code,
                    410,
                )
                self.assertEqual(client.post("/api/auth/logout").status_code, 200)
                self.assertEqual(client.get("/api/messages").status_code, 401)

    def test_receiver_accounts_change_password_and_scope_inbox_to_member(self):
        password = "enkripsih-test-password-2026"
        with patch.dict(os.environ, {"ENKRIPSIH_PASSWORD": password}):
            with TestClient(main.app) as client:
                commander_login = client.post(
                    "/api/auth/login", json={"password": password}
                )
                self.assertEqual(commander_login.status_code, 200)

                recipients = []
                for name, salt, verifier in (
                    ("Receiver Satu", "11" * 16, "22" * 32),
                    ("Receiver Dua", "33" * 16, "44" * 32),
                ):
                    response = client.post("/api/recipients/register", json={
                        "name": name,
                        "salt": salt,
                        "verifier": verifier,
                    })
                    self.assertEqual(response.status_code, 200)
                    account = response.json()
                    self.assertEqual(account["username"], name.casefold())
                    self.assertGreaterEqual(len(account["temporary_password"]), 20)
                    recipients.append(account)
                    sent = client.post("/api/messages/send", json={
                        "recipient_id": account["recipient_id"],
                        "paket": self.fake_envelope(),
                    })
                    self.assertEqual(sent.status_code, 200)
                    account["message_id"] = sent.json()["message_id"]

                client.post("/api/auth/logout")
                receiver = recipients[0]
                receiver_login = client.post("/api/auth/receiver-login", json={
                    "username": receiver["username"],
                    "password": receiver["temporary_password"],
                })
                self.assertEqual(receiver_login.status_code, 200)
                self.assertTrue(receiver_login.json()["must_change_password"])
                self.assertEqual(client.get("/api/messages").status_code, 403)

                short_password = client.post("/api/auth/change-password", json={
                    "new_password": "short",
                })
                self.assertEqual(short_password.status_code, 400)
                changed = client.post("/api/auth/change-password", json={
                    "new_password": "a-new-receiver-password-2026",
                })
                self.assertEqual(changed.status_code, 200)
                self.assertFalse(client.get("/api/auth/session").json()["must_change_password"])

                inbox = client.get("/api/messages")
                self.assertEqual(inbox.status_code, 200)
                self.assertEqual(
                    [item["recipient_id"] for item in inbox.json()["messages"]],
                    [receiver["recipient_id"]],
                )
                own_keys = client.get("/api/recipients")
                self.assertEqual(
                    [item["id"] for item in own_keys.json()["recipients"]],
                    [receiver["recipient_id"]],
                )
                foreign_ciphertext = client.get(
                    f"/api/messages/{recipients[1]['message_id']}/ciphertext"
                )
                self.assertEqual(foreign_ciphertext.status_code, 404)
                self.assertEqual(
                    client.post("/api/messages/send", json={
                        "recipient_id": receiver["recipient_id"],
                        "paket": self.fake_envelope(),
                    }).status_code,
                    403,
                )
                client.post("/api/auth/logout")
                self.assertEqual(
                    client.post("/api/auth/login", json={"password": password}).status_code,
                    200,
                )
                reset = client.post(
                    f"/api/recipients/{receiver['recipient_id']}/account"
                )
                self.assertEqual(reset.status_code, 200)
                self.assertNotEqual(
                    reset.json()["temporary_password"],
                    receiver["temporary_password"],
                )
                client.post("/api/auth/logout")
                old_password_login = client.post("/api/auth/receiver-login", json={
                    "username": receiver["username"],
                    "password": receiver["temporary_password"],
                })
                self.assertEqual(old_password_login.status_code, 401)
                new_password_login = client.post("/api/auth/receiver-login", json={
                    "username": reset.json()["username"],
                    "password": reset.json()["temporary_password"],
                })
                self.assertEqual(new_password_login.status_code, 200)
                self.assertTrue(new_password_login.json()["must_change_password"])

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
