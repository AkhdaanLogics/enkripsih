import asyncio
import base64
import hashlib
import hmac
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

from backend import database as _database
from backend import migrate_to_postgres
from backend import secure_backup

_IMPORT_DB = tempfile.TemporaryDirectory()
_database.DB_PATH = str(Path(_IMPORT_DB.name) / "import.db")
from backend import main
from backend import database


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
        self.keybca_secret = "test-keybca-secret-2026"
        self.test_suffix = self._testMethodName
        # Force isolated SQLite/SQLCipher mode so tests do not touch Postgres.
        self.environ_patch = patch.dict(
            os.environ,
            {
                "ENKRIPSIH_DB_PASSPHRASE": self.database_passphrase,
                "ENKRIPSIH_KEYBCA_SECRET": self.keybca_secret,
                "ENKRIPSIH_ENABLE_DOCS": "",
            },
            clear=False,
        )
        self.environ_patch.start()
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("ENKRIPSIH_CONFIRM_DB_MIGRATION", None)
        database.init_db()
        self._clean_test_data()

    def _clean_test_data(self):
        """Wipe non-system rows so tests are isolated."""
        with database._managed_connection() as conn:
            for table in ("auth_sessions", "messages", "receiver_accounts",
                          "recipient_keys", "login_lockouts", "audit_logs"):
                conn.execute(f"DELETE FROM {table}")

    def tearDown(self):
        self._clean_test_data()
        self.environ_patch.stop()
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def register_test_recipient(self, name=None):
        if name is None:
            name = f"Tim Uji {self.test_suffix}"
        response = main.register_recipient(main.RegisterRecipientRequest(
            name=name,
            salt="11" * 16,
            verifier="22" * 32,
        ))
        return response["recipient_id"]

    def register_unique_recipient(self, base_name="Test"):
        import uuid
        name = f"{base_name} {uuid.uuid4().hex[:8]}"
        response = main.register_recipient(main.RegisterRecipientRequest(
            name=name,
            salt="11" * 16,
            verifier="22" * 32,
        ))
        return response["recipient_id"], name

    def register_unique_receiver_accounts(self, count=2):
        import uuid
        accounts = []
        for i in range(count):
            name = f"Rcv {uuid.uuid4().hex[:10]} {i}"
            salt = "11" * 16
            verifier = "22" * 32
            response = main.register_recipient(main.RegisterRecipientRequest(
                name=name, salt=salt, verifier=verifier,
            ))
            accounts.append(response)
        return accounts

    @staticmethod
    def _mock_commander_request():
        """Create a mock FastAPI request with COMMANDER principal for direct endpoint calls."""
        from unittest.mock import MagicMock
        request = MagicMock()
        request.state.principal = {
            "principal_id": "CMD-01",
            "role": "COMMANDER",
            "must_change_password": False,
        }
        return request

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
        result = asyncio.run(main.send_message_endpoint(
            main.SendMessageRequest(recipient_id=recipient_id, paket=paket),
            self._mock_commander_request(),
        ))
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
        envelope["expected_response"] = "TCXTCSTCXTCS"
        paket = json.dumps(envelope)
        result = asyncio.run(main.send_message_endpoint(
            main.SendMessageRequest(recipient_id=recipient_id, paket=paket),
            self._mock_commander_request(),
        ))

        stored = database.get_message_by_id(result["message_id"])
        ciphertext = main.get_message_ciphertext(result["message_id"])
        self.assertEqual(stored["paket"], paket)
        self.assertNotIn("plaintext", stored)
        self.assertEqual(ciphertext["paket"], paket)

        invalid = json.loads(paket)
        invalid["challenge"] = "TCX"
        with self.assertRaises(HTTPException) as error:
            asyncio.run(main.send_message_endpoint(
                main.SendMessageRequest(recipient_id=recipient_id, paket=json.dumps(invalid)),
                self._mock_commander_request(),
            ))
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
        sent = asyncio.run(main.send_message_endpoint(
            main.SendMessageRequest(recipient_id=recipient_id, paket=paket),
            self._mock_commander_request(),
        ))
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
            sent = asyncio.run(main.send_message_endpoint(
                main.SendMessageRequest(recipient_id=recipient_id, paket=self.fake_envelope()),
                self._mock_commander_request(),
            ))
            sent_ids.append(sent["message_id"])

        with database._managed_connection() as connection:
            connection.execute("ALTER TABLE messages ADD COLUMN plaintext TEXT")
            connection.execute("ALTER TABLE messages ADD COLUMN subject TEXT")
            connection.execute("ALTER TABLE messages ADD COLUMN priority TEXT")
            connection.execute("ALTER TABLE messages ADD COLUMN challenge_letters TEXT")
            connection.execute("ALTER TABLE messages ADD COLUMN challenge_symbols TEXT")
            connection.execute("ALTER TABLE messages ADD COLUMN legacy_marker TEXT")
            connection.execute("""
                UPDATE messages
                SET status = 'UNLOCKED', plaintext = ?, subject = ?,
                    priority = ?, challenge_letters = ?, challenge_symbols = ?,
                    legacy_marker = ?, decrypted_at = ?
                WHERE id = ?
            """, (
                "plaintext lama", "subject rahasia", "TOP SECRET",
                "TCXS", "△ ○ ✕ □", "legacy-marker-value",
                "2026-10-23T12:00:00", sent_ids[0],
            ))
            connection.execute("""
                UPDATE messages
                SET status = 'BURNED', plaintext = ?
                WHERE id = ?
            """, ("marker lama", sent_ids[1]))

        database.init_db()
        unlocked = database.get_message_by_id(sent_ids[0])
        burned = database.get_message_by_id(sent_ids[1])

        self.assertEqual(unlocked["status"], "UNLOCKED")
        self.assertNotIn("plaintext", unlocked)
        self.assertEqual(burned["status"], "BURNED")
        self.assertNotIn("plaintext", burned)
        with database._managed_connection() as connection:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(messages)").fetchall()
            }
        for removed in (
            "plaintext", "subject", "priority", "challenge_letters",
            "challenge_symbols",
        ):
            self.assertNotIn(removed, columns)
        self.assertIn("decrypted_at", columns)

    def test_blank_message_is_not_transmitted(self):
        recipient_id = self.register_test_recipient()
        send_request = main.SendMessageRequest(
            recipient_id=recipient_id,
            paket=" ",
        )

        with self.assertRaises(HTTPException) as error:
            asyncio.run(main.send_message_endpoint(send_request, self._mock_commander_request()))

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(database.get_messages(), [])

    def test_invalid_ciphertext_is_rejected_without_logging_payload(self):
        recipient_id = self.register_test_recipient()
        with self.assertRaises(HTTPException) as error:
            asyncio.run(main.send_message_endpoint(
                main.SendMessageRequest(recipient_id=recipient_id, paket="not-json"),
                self._mock_commander_request(),
            ))
        self.assertEqual(error.exception.status_code, 400)
        self.assertNotIn("not-json", str(database.get_logs()))

    def test_burning_message_clears_ciphertext(self):
        recipient_id = self.register_test_recipient()
        sent = asyncio.run(main.send_message_endpoint(
            main.SendMessageRequest(recipient_id=recipient_id, paket=self.fake_envelope()),
            self._mock_commander_request(),
        ))

        asyncio.run(main.burn_message_endpoint(sent["message_id"], self._mock_commander_request()))

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
        self.assertIn("decrypted_at", migrated)
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
                self.assertIsNone(client.cookies.get(main.SESSION_COOKIE))
                self.assertFalse(client.get("/api/auth/session").json()["authenticated"])
                self.assertEqual(client.get("/api/messages").status_code, 401)
                login = client.post("/api/auth/login", json={"password": password})
                self.assertEqual(login.status_code, 200)
                self.assertEqual(
                    login.json()["idle_timeout_seconds"],
                    main.SESSION_IDLE_TIMEOUT_SECONDS,
                )
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

    def test_authenticated_activity_slides_idle_expiry_and_idle_session_is_rejected(self):
        password = "enkripsih-test-password-2026"
        clock = [1_000.0]
        with (
            patch.dict(os.environ, {"ENKRIPSIH_PASSWORD": password}),
            patch.object(main, "SESSION_IDLE_TIMEOUT_SECONDS", 10),
            patch.object(main.time, "monotonic", side_effect=lambda: clock[0]),
        ):
            with TestClient(main.app) as client:
                login = client.post("/api/auth/login", json={"password": password})
                self.assertEqual(login.status_code, 200)

                clock[0] += 9
                refreshed = client.get("/api/auth/session")
                self.assertEqual(refreshed.status_code, 200)
                self.assertTrue(refreshed.json()["authenticated"])
                clock[0] += 9
                self.assertEqual(client.get("/api/messages").status_code, 200)

                clock[0] += 11
                self.assertEqual(client.get("/api/messages").status_code, 401)
                self.assertFalse(client.get("/api/auth/session").json()["authenticated"])

    def test_login_lockout_persists_across_restart_and_resets_after_cooldown(self):
        password = "enkripsih-test-password-2026"
        for attempt in range(main.LOGIN_MAX_ATTEMPTS):
            with patch.dict(os.environ, {"ENKRIPSIH_PASSWORD": password}), \
                    patch.object(main.time, "time") as time_mock:
                time_now = [1_000.0 + attempt]
                time_mock.side_effect = lambda: time_now[0]
                with TestClient(main.app) as client:
                    request = client.post("/api/auth/login", json={"password": "salah"})
                    if attempt < main.LOGIN_MAX_ATTEMPTS - 1:
                        self.assertEqual(request.status_code, 401)
                        remaining = main.LOGIN_MAX_ATTEMPTS - (attempt + 1)
                        self.assertIn(f"Sisa {remaining} percobaan", request.json()["detail"])
                    else:
                        self.assertEqual(request.status_code, 429)
                        self.assertIn("Retry-After", request.headers)

        with patch.dict(os.environ, {"ENKRIPSIH_PASSWORD": password}), \
                patch.object(main.time, "time") as time_mock:
            time_now = [1_000.0 + main.LOGIN_MAX_ATTEMPTS]
            time_mock.side_effect = lambda: time_now[0]
            with TestClient(main.app) as client:
                refresh_attempt = client.post("/api/auth/login", json={"password": password})
                self.assertEqual(refresh_attempt.status_code, 429)
                retry_after = int(refresh_attempt.headers["Retry-After"])
                self.assertGreater(retry_after, 0)

                time_now[0] += retry_after + 1
                recovered = client.post("/api/auth/login", json={"password": password})
                self.assertEqual(recovered.status_code, 200)

            with TestClient(main.app) as client:
                first_fail = client.post("/api/auth/login", json={"password": "salah"})
                self.assertEqual(first_fail.status_code, 401)
                self.assertIn("Sisa", first_fail.json()["detail"])

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
                    (f"Receiver Satu {self.test_suffix}", "11" * 16, "22" * 32),
                    (f"Receiver Dua {self.test_suffix}", "33" * 16, "44" * 32),
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
                failed_receiver_login = client.post("/api/auth/receiver-login", json={
                    "username": receiver["username"],
                    "password": "incorrect",
                })
                self.assertEqual(failed_receiver_login.status_code, 401)
                self.assertFalse(client.get("/api/auth/session").json()["authenticated"])
                self.assertEqual(client.get("/api/messages").status_code, 401)

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

    def test_docs_disabled_by_default_and_enabled_via_env(self):
        # Default: docs disabled
        with patch.dict(os.environ, {
            "ENKRIPSIH_PASSWORD": "test-password-2026",
            "ENKRIPSIH_DB_PASSPHRASE": self.database_passphrase,
            "ENKRIPSIH_KEYBCA_SECRET": self.keybca_secret,
            "ENKRIPSIH_ENABLE_DOCS": "",
        }):
            from importlib import reload
            import backend.main as main_module
            reload(main_module)
            self.assertIsNone(main_module.app.docs_url)
            self.assertIsNone(main_module.app.redoc_url)
            self.assertIsNone(main_module.app.openapi_url)

        # With flag: docs enabled
        with patch.dict(os.environ, {
            "ENKRIPSIH_PASSWORD": "test-password-2026",
            "ENKRIPSIH_DB_PASSPHRASE": self.database_passphrase,
            "ENKRIPSIH_KEYBCA_SECRET": self.keybca_secret,
            "ENKRIPSIH_ENABLE_DOCS": "1",
        }):
            reload(main_module)
            self.assertEqual(main_module.app.docs_url, "/docs")
            self.assertEqual(main_module.app.redoc_url, "/redoc")
            self.assertEqual(main_module.app.openapi_url, "/openapi.json")

    def test_sender_spoofing_is_prevented(self):
        password = "enkripsih-test-password-2026"
        with patch.dict(os.environ, {
            "ENKRIPSIH_PASSWORD": password,
            "ENKRIPSIH_DB_PASSPHRASE": self.database_passphrase,
            "ENKRIPSIH_KEYBCA_SECRET": self.keybca_secret,
        }):
            with TestClient(main.app) as client:
                login = client.post("/api/auth/login", json={"password": password})
                self.assertEqual(login.status_code, 200)
                registered = client.post("/api/recipients/register", json={
                    "name": "Anggota Kirim",
                    "salt": "11" * 16,
                    "verifier": "22" * 32,
                })
                self.assertEqual(registered.status_code, 200)
                recipient_id = registered.json()["recipient_id"]

                # Valid send without sender fields (new behavior)
                sent = client.post("/api/messages/send", json={
                    "recipient_id": recipient_id,
                    "paket": self.fake_envelope(),
                })
                self.assertEqual(sent.status_code, 200)
                sent_data = sent.json()
                sender_info = main.get_message_by_id(sent_data["message_id"])
                # Sender should be from principal, not client input
                self.assertEqual(sender_info["sender_id"], "CMD-01")

            # Separate client: receiver cannot send messages
            with TestClient(main.app) as receiver_client:
                failed_send = receiver_client.post("/api/messages/send", json={
                    "recipient_id": recipient_id,
                    "paket": self.fake_envelope(),
                })
                # Unauthenticated = 401
                self.assertEqual(failed_send.status_code, 401)

    def test_security_response_headers_are_present(self):
        password = "enkripsih-test-password-2026"
        with patch.dict(os.environ, {
            "ENKRIPSIH_PASSWORD": password,
            "ENKRIPSIH_DB_PASSPHRASE": self.database_passphrase,
            "ENKRIPSIH_KEYBCA_SECRET": self.keybca_secret,
        }):
            with TestClient(main.app) as client:
                response = client.get("/api/auth/session")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
                self.assertIn("Content-Security-Policy", response.headers)
                csp = response.headers["Content-Security-Policy"]
                self.assertIn("default-src 'self'", csp)
                self.assertIn("frame-ancestors 'none'", csp)


    def test_receiver_burn_requires_prior_unlock(self):
        password = "enkripsih-test-password-2026"
        with patch.dict(os.environ, {
            "ENKRIPSIH_PASSWORD": password,
            "ENKRIPSIH_DB_PASSPHRASE": self.database_passphrase,
            "ENKRIPSIH_KEYBCA_SECRET": self.keybca_secret,
        }):
            with TestClient(main.app) as client:
                login = client.post("/api/auth/login", json={"password": password})
                self.assertEqual(login.status_code, 200)
                registered = client.post("/api/recipients/register", json={
                    "name": f"Rcv Burn {self.test_suffix}",
                    "salt": "11" * 16,
                    "verifier": "22" * 32,
                })
                self.assertEqual(registered.status_code, 200)
                recipient_id = registered.json()["recipient_id"]
                sent = client.post("/api/messages/send", json={
                    "recipient_id": recipient_id,
                    "paket": self.fake_envelope(),
                })
                self.assertEqual(sent.status_code, 200)
                msg_id = sent.json()["message_id"]

                # Log in as receiver
                client.post("/api/auth/logout")
                receiver_login = client.post("/api/auth/receiver-login", json={
                    "username": f"rcv burn {self.test_suffix}".lower(),
                    "password": registered.json()["temporary_password"],
                })
                self.assertEqual(receiver_login.status_code, 200)

                # Burn before unlock should fail
                burn_blocked = client.post(f"/api/messages/{msg_id}/burn")
                self.assertEqual(burn_blocked.status_code, 403)
                self.assertIn("belum dibuka", burn_blocked.json()["detail"])

                # Unlock first
                unlock = client.post(f"/api/messages/{msg_id}/unlock")
                self.assertEqual(unlock.status_code, 200)

                # Burn after unlock should succeed
                burn_ok = client.post(f"/api/messages/{msg_id}/burn")
                self.assertEqual(burn_ok.status_code, 200)
                stored = main.get_message_by_id(msg_id)
                self.assertEqual(stored["status"], "BURNED")
                self.assertEqual(stored["paket"], "")

                # Commander can burn any message
                client.post("/api/auth/logout")
                client.post("/api/auth/login", json={"password": password})
                sent2 = client.post("/api/messages/send", json={
                    "recipient_id": recipient_id,
                    "paket": self.fake_envelope(),
                })
                msg2 = sent2.json()["message_id"]
                burn_cmd = client.post(f"/api/messages/{msg2}/burn")
                self.assertEqual(burn_cmd.status_code, 200)

    def test_receiver_cannot_burn_foreign_message(self):
        password = "enkripsih-test-password-2026"
        with patch.dict(os.environ, {
            "ENKRIPSIH_PASSWORD": password,
            "ENKRIPSIH_DB_PASSPHRASE": self.database_passphrase,
            "ENKRIPSIH_KEYBCA_SECRET": self.keybca_secret,
        }):
            with TestClient(main.app) as client:
                login = client.post("/api/auth/login", json={"password": password})
                self.assertEqual(login.status_code, 200)
                reg1 = client.post("/api/recipients/register", json={
                    "name": f"Rcv A {self.test_suffix}",
                    "salt": "11" * 16, "verifier": "22" * 32,
                })
                reg2 = client.post("/api/recipients/register", json={
                    "name": f"Rcv B {self.test_suffix}",
                    "salt": "33" * 16, "verifier": "44" * 32,
                })
                self.assertEqual(reg1.status_code, 200)
                self.assertEqual(reg2.status_code, 200)
                recipient_a = reg1.json()["recipient_id"]
                recipient_b = reg2.json()["recipient_id"]

                # Commander sends a message to A
                sent = client.post("/api/messages/send", json={
                    "recipient_id": recipient_a,
                    "paket": self.fake_envelope(),
                })
                msg_id = sent.json()["message_id"]

                # Log in as B (different receiver)
                client.post("/api/auth/logout")
                client.post("/api/auth/receiver-login", json={
                    "username": f"rcv b {self.test_suffix}".lower(),
                    "password": reg2.json()["temporary_password"],
                })

                # B cannot unlock or burn A's message
                unlock_foreign = client.post(f"/api/messages/{msg_id}/unlock")
                self.assertEqual(unlock_foreign.status_code, 404)
                burn_foreign = client.post(f"/api/messages/{msg_id}/burn")
                self.assertEqual(burn_foreign.status_code, 404)

    def _register_real_secret_recipient(self, client, name):
        """Register a recipient whose verifier actually matches a known secret key."""
        secret = os.urandom(16).hex()  # 32 chars
        salt = os.urandom(16).hex()
        verifier = hashlib.pbkdf2_hmac(
            "sha256", secret.encode(),
            b"enkripsih:recipient:v1:" + bytes.fromhex(salt), 600_000, 32,
        ).hex()
        response = client.post("/api/recipients/register", json={
            "name": name, "salt": salt, "verifier": verifier,
        })
        self.assertEqual(response.status_code, 200)
        body = response.json()
        return body["recipient_id"], secret, body["temporary_password"]

    def test_encrypt_endpoint_rejects_wrong_secret_key(self):
        password = "enkripsih-test-password-2026"
        with patch.dict(os.environ, {
            "ENKRIPSIH_PASSWORD": password,
            "ENKRIPSIH_DB_PASSPHRASE": self.database_passphrase,
            "ENKRIPSIH_KEYBCA_SECRET": self.keybca_secret,
        }):
            with TestClient(main.app) as client:
                client.post("/api/auth/login", json={"password": password})
                recipient_id, secret, _ = self._register_real_secret_recipient(
                    client, f"Enc Wrong {self.test_suffix}"
                )
                wrong_key = "w" * 32
                response = client.post("/api/messages/encrypt", json={
                    "plaintext": "rahasia",
                    "recipient_id": recipient_id,
                    "secret_key": wrong_key,
                    "save": False,
                })
                self.assertEqual(response.status_code, 400)
                self.assertIn("tidak cocok", response.json()["detail"])

    def test_encrypt_and_decrypt_round_trip(self):
        password = "enkripsih-test-password-2026"
        with patch.dict(os.environ, {
            "ENKRIPSIH_PASSWORD": password,
            "ENKRIPSIH_DB_PASSPHRASE": self.database_passphrase,
            "ENKRIPSIH_KEYBCA_SECRET": self.keybca_secret,
        }):
            with TestClient(main.app) as client:
                client.post("/api/auth/login", json={"password": password})
                recipient_id, secret, temporary_password = (
                    self._register_real_secret_recipient(
                        client, f"Enc RT {self.test_suffix}"
                    )
                )
                encrypted = client.post("/api/messages/encrypt", json={
                    "plaintext": "kunci aman uji",
                    "recipient_id": recipient_id,
                    "secret_key": secret,
                    "save": True,
                })
                self.assertEqual(encrypted.status_code, 200)
                body = encrypted.json()
                self.assertEqual(body["saved"]["status"], "LOCKED")
                message_id = body["saved"]["message_id"]
                envelope = json.loads(body["paket"])
                self.assertEqual(envelope["v"], 5)
                # SECURITY FIX: expected_response must NOT be embedded in v5 envelope
                self.assertNotIn("expected_response", envelope)

                # Commander cannot use the receiver-only decrypt endpoint
                commander_decrypt = client.post("/api/messages/decrypt", json={
                    "message_id": message_id,
                })
                self.assertEqual(commander_decrypt.status_code, 403)

                # Receiver must change the temporary password before full access
                client.post("/api/auth/logout")
                receiver_login = client.post("/api/auth/receiver-login", json={
                    "username": f"enc rt {self.test_suffix}".lower(),
                    "password": temporary_password,
                })
                self.assertEqual(receiver_login.status_code, 200)
                self.assertTrue(receiver_login.json()["must_change_password"])
                change_password = client.post("/api/auth/change-password", json={
                    "new_password": "enkripsih-new-password-2026"
                })
                self.assertEqual(change_password.status_code, 200)

                # Receiver must supply the 12-symbol passkey from their hardware token.
                # Simulate KeyBCA: compute HMAC-SHA256(secret, challenge_bytes) -> 12 symbols.
                LETTERS = "TCXS"
                challenge_letters = str(envelope["challenge"])
                challenge_indices = [LETTERS.index(ch) for ch in challenge_letters]
                challenge_bytes = bytes(challenge_indices)
                mac = hmac.new(
                    secret.encode("utf-8"),
                    challenge_bytes, hashlib.sha256
                ).digest()
                resp_indices = [(mac[i // 4] >> ((i % 4) * 2)) & 3 for i in range(12)]
                passkey_letters = "".join(LETTERS[r] for r in resp_indices)

                decrypt_response = client.post("/api/messages/decrypt", json={
                    "message_id": message_id,
                    "passkey_letters": passkey_letters,
                })
                self.assertEqual(decrypt_response.status_code, 200)
                self.assertEqual(decrypt_response.json()["plaintext"], "kunci aman uji")
                stored = database.get_message_by_id(message_id)
                self.assertEqual(stored["status"], "UNLOCKED")

                # A wrong 12-letter passkey is rejected with 400
                bad_decrypt = client.post("/api/messages/decrypt", json={
                    "message_id": message_id,
                    "passkey_letters": "T" * 12,
                })
                self.assertEqual(bad_decrypt.status_code, 400)
                self.assertIn("salah", bad_decrypt.json()["detail"])

    def test_reissue_rotates_verifier_and_old_key_stops_working(self):
        password = "enkripsih-test-password-2026"
        with patch.dict(os.environ, {
            "ENKRIPSIH_PASSWORD": password,
            "ENKRIPSIH_DB_PASSPHRASE": self.database_passphrase,
            "ENKRIPSIH_KEYBCA_SECRET": self.keybca_secret,
        }):
            with TestClient(main.app) as client:
                client.post("/api/auth/login", json={"password": password})
                recipient_id, old_secret, _ = self._register_real_secret_recipient(
                    client, f"Reissue {self.test_suffix}"
                )
                reissued = client.post(f"/api/recipients/{recipient_id}/reissue")
                self.assertEqual(reissued.status_code, 200)
                new_secret = reissued.json()["new_secret_key"]
                self.assertNotEqual(new_secret, old_secret)
                self.assertGreaterEqual(len(new_secret), 24)

                old_key_rejected = client.post("/api/messages/encrypt", json={
                    "plaintext": "x",
                    "recipient_id": recipient_id,
                    "secret_key": old_secret,
                    "save": False,
                })
                self.assertEqual(old_key_rejected.status_code, 400)

                new_key_accepted = client.post("/api/messages/encrypt", json={
                    "plaintext": "x",
                    "recipient_id": recipient_id,
                    "secret_key": new_secret,
                    "save": False,
                })
                self.assertEqual(new_key_accepted.status_code, 200)

    def test_delete_recipient_cascades_messages_and_account(self):
        password = "enkripsih-test-password-2026"
        with patch.dict(os.environ, {
            "ENKRIPSIH_PASSWORD": password,
            "ENKRIPSIH_DB_PASSPHRASE": self.database_passphrase,
            "ENKRIPSIH_KEYBCA_SECRET": self.keybca_secret,
        }):
            with TestClient(main.app) as client:
                client.post("/api/auth/login", json={"password": password})
                recipient_id, _, _ = self._register_real_secret_recipient(
                    client, f"Delete {self.test_suffix}"
                )
                sent = client.post("/api/messages/send", json={
                    "recipient_id": recipient_id,
                    "paket": self.fake_envelope(),
                })
                self.assertEqual(sent.status_code, 200)
                self.assertEqual(database.get_messages_count_for_recipient(recipient_id), 1)

                deleted = client.delete(f"/api/recipients/{recipient_id}")
                self.assertEqual(deleted.status_code, 200)
                self.assertEqual(deleted.json()["deleted_messages"], 1)
                self.assertIsNone(database.get_recipient_key(recipient_id))
                self.assertEqual(database.get_messages_count_for_recipient(recipient_id), 0)
                self.assertIsNone(database.get_receiver_account(
                    f"delete {self.test_suffix}".lower()
                ))

                # Deleting again is a 404
                again = client.delete(f"/api/recipients/{recipient_id}")
                self.assertEqual(again.status_code, 404)

                # Non-commander cannot delete another member's record
                second_register = client.post("/api/recipients/register", json={
                    "name": f"Delete Other {self.test_suffix}",
                    "salt": "55" * 16, "verifier": "66" * 32,
                })
                self.assertEqual(second_register.status_code, 200)
                other = second_register.json()
                client.post("/api/auth/logout")
                other_login = client.post("/api/auth/receiver-login", json={
                    "username": f"delete other {self.test_suffix}".lower(),
                    "password": other["temporary_password"],
                })
                self.assertEqual(other_login.status_code, 200)
                forbidden = client.delete(f"/api/recipients/{other['recipient_id']}")
                self.assertEqual(forbidden.status_code, 403)


if __name__ == "__main__":
    unittest.main()

