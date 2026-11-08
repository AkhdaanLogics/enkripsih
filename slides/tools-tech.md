# Tools & Teknologi — ENKRIPSIH

Tabel ini untuk slide presentasi. Semua item sudah diverifikasi dari kode sumber:
`requirements.txt`, `frontend/*`, `backend/*`, `iot_microcontroller/*`.

## Tabel 3 Kolom

| Frontend | Backend | Perangkat (IoT) |
|---|---|---|
| Vanilla JS (ES6), tanpa framework | Python 3.9+ | Wemos D1 Mini (ESP8266) |
| HTML5 + CSS3 custom design system | FastAPI + Uvicorn | Firmware C++ (Arduino IDE) |
| Web Crypto API (derive verifier) | `cryptography` (AES-GCM, PBKDF2, Argon2) | BearSSL HMAC-SHA256 + Dynamic Truncation (TOTP-style) |
| Responsive mobile-first | `psycopg` (PostgreSQL Neon, cloud) | OLED SSD1306 0.96" |
| UI anti-slop (murni custom, bukan Bootstrap) | SQLite + SQLCipher (lokal dev) | 2 Tombol + Buzzer piezo |
| Deploy: Vercel (static + serverless) | `pytest` (34 test) | Serial USB (input challenge) |
|  | `httpx` (WebSocket client) | WiFi HTTP (opsional, ke `/api/iot/keybca/solve`) |
|  | `python-dotenv` (env vars) | LiPo + TP4056 (power) |
|  | `argon2-cffi` (key wrap lokal) |  |
|  | `opencv-python` + `numpy` (face auth, backend ready) |  |

## Catatan Penting

- **Frontend tidak pakai Bootstrap.** Murni Vanilla JS + CSS custom. Jangan tulis "Bootstrap 5" di slide.
- **Wemos D1 Mini = "kunci fisik" per-receiver.** Alurnya: server kirim 4 simbol challenge → receiver ketik ke Wemos via Serial USB → Wemos hitung `HMAC-SHA256(MASTER_SECRET, challenge)` → Dynamic Truncation → 12 simbol response di OLED → receiver salin 12 simbol ke browser → server `PBKDF2-SHA256` + `AES-GCM` decrypt.
- **Face auth** sudah ada di `backend/face_auth.py` (OpenCV + Haar Cascade + cosine similarity, threshold 75%), **belum di-wire ke UI** → masukkan ke slide roadmap, bukan fitur aktif.
- **Deploy:** frontend + backend sama-sama di Vercel. Frontend disajikan oleh FastAPI (`/static`, `/`), bukan build terpisah.
- **PostgreSQL Neon** (US-East-2) untuk produksi, SQLite + SQLCipher untuk dev lokal. Migrasi: `python -m backend.migrate_to_postgres`.
- **AES-GCM** = enkripsi autentik (ciphertext + auth tag 16B), kunci 32 byte diturunkan dari 12 simbol response via PBKDF2-SHA256 200.000 iterasi.
- **Verifier** anggota dihitung PBKDF2-SHA256 600.000 iterasi (lebih berat dari kunci pesan) untuk proteksi offline brute-force.
- **Throttle** proteksi brute-force: 5 percobaan gagal → lock 5 menit, untuk login, decrypt, dan face verify.
- **Burn** = hapus `messages.paket` jadi NULL. Ini hapus aplikasi-level, bukan fisik (WAL/backup masih mungkin ada).

## Alur Singkat (untuk caption slide)

1. **Daftar anggota:** Sender login → isi form nama + secret key → server generate salt + verifier (PBKDF2-600k) + provision akun receiver (username + password sementara) → encrypt `agent_secret` AES-GCM simpan ke DB.
2. **Kirim pesan:** Sender pilih anggota + isi plaintext → server baca `agent_secret` dari DB → generate challenge 4 simbol → `HMAC-SHA256` → 12 simbol response → `PBKDF2-SHA256` (200k) → `AES-GCM` encrypt → simpan ciphertext status `LOCKED` → broadcast WebSocket.
3. **Buka pesan:** Receiver login → lihat inbox + challenge → ketik 4 simbol ke Wemos → Wemos hitung HMAC-SHA256 → 12 simbol di OLED → receiver salin ke browser → server `PBKDF2 + AES-GCM` decrypt → plaintext status `UNLOCKED` → opsional BURN.
