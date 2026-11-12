# ENKRIPSIH

Aplikasi web untuk mengirim pesan terenkripsi dari **Sender** ke banyak **Receiver** terdaftar. Pesan dienkripsi di sisi server dengan Web Crypto (PBKDF2-HMAC-SHA-256 dan AES-GCM), lalu server menyimpan paket ciphertext. Receiver hanya dapat membuka pesan dengan respons dari perangkat passkey Wemos D1 Mini.

> **Prototipe, bukan sistem produksi.** Gunakan hanya data sintetis. Enkripsi sisi-klien membantu mencegah plaintext tersimpan pada database/API normal, tetapi tidak melindungi pengguna dari server atau JavaScript frontend yang telah dikompromikan, malware di perangkat, atau kebocoran secret key.

## Daftar Isi

- [Fitur Utama](#fitur-utama)
- [Arsitektur](#arsitektur)
- [Alur Pemakaian](#alur-pemakaian)
- [Struktur Proyek](#struktur-proyek)
- [Menjalankan di Windows](#menjalankan-di-windows)
- [Menjalankan di Vercel](#menjalankan-di-vercel)
- [Migrasi Lokal ke PostgreSQL](#migrasi-lokal-ke-postgresql)
- [Pengujian](#pengujian)
- [Catatan Keamanan](#catatan-keamanan)
- [Video Demo](#video-demo)

## Fitur Utama

| Fitur | Keterangan |
|---|---|
| End-to-end encryption | AES-GCM-256 + PBKDF2-SHA-256 (200.000 iterasi), plaintext tidak pernah tersimpan di server |
| Multi-penerima | 1 Sender, N Receiver, masing-masing dengan secret key & akun terpisah |
| Kunci agen di DB | `agent_secret` disimpan terenkripsi di database — deploy Vercel tanpa perlu env vars |
| Perangkat passkey | Wemos D1 Mini (ESP8266) menjalankan firmware KeyBCA, menghasilkan 12 simbol respons dari 4 simbol challenge |
| Burn pesan | Hapus ciphertext permanen dari database |
| Throttle brute-force | 5 percobaan gagal → lock 5 menit untuk login, decrypt, dan face verify |
| UI anti-slop | Design system "tactical data terminal", mobile-first, onboarding tour |
| WebSocket real-time | Broadcast event (pesan baru, dibakar, dibuka) ke semua client |

## Arsitektur

```
┌──────────────┐    HTTPS      ┌──────────────────────┐    TLS      ┌────────────────────┐
│  Sender      │──────────────>│  Backend FastAPI     │────────────>│  PostgreSQL Neon   │
│  (Browser)   │               │  (Vercel serverless) │             │  (US-East-2)       │
└──────────────┘               └──────────┬───────────┘             └────────────────────┘
                                          │
                                          │ WebSocket
                                          ▼
┌──────────────┐    HTTPS      ┌──────────────────────┐
│  Receiver    │<─────────────>│  (event broadcast)   │
│  (Browser)   │               └──────────────────────┘
└──────┬───────┘
       │ Serial USB (4 simbol challenge)
       ▼
┌──────────────────────┐
│  Wemos D1 Mini       │  HMAC-SHA256(MASTER_SECRET, challenge)
│  (KeyBCA firmware)   │  → Dynamic Truncation → 12 simbol response
│  OLED + 2 Tombol     │  → Receiver salin 12 simbol ke browser
│  + Buzzer + LiPo     │
└──────────────────────┘
```

**Stack teknologi**

| Lapisan | Teknologi |
|---|---|
| Frontend | Vanilla JS (ES6), HTML5 + CSS3 custom, Web Crypto API, Vercel static |
| Backend | Python 3.9+, FastAPI + Uvicorn, `cryptography`, `psycopg`, `argon2-cffi`, Vercel serverless |
| Database | PostgreSQL Neon (cloud), SQLite + SQLCipher (lokal dev) |
| IoT | Wemos D1 Mini (ESP8266), firmware C++ (Arduino IDE), BearSSL, OLED SSD1306 |
| Face Auth | OpenCV + numpy (Haar Cascade, cosine similarity) — *backend ready, belum di-wire ke UI* |

## Alur Pemakaian

1. **Sender** masuk dengan password aplikasi (`ENKRIPSIH_PASSWORD`).
2. Buka **Kelola anggota** untuk mendaftarkan anggota dan membuat secret key acak. Aplikasi membuat akun receiver dengan username berdasarkan nama anggota dan password sementara acak. Simpan keduanya saat hanya ditampilkan sekali; bagikan password akun dan secret key melalui kanal aman yang berbeda.
3. Anggota memilih jenis akun **Receiver**, masuk dengan username dan password sementara, lalu wajib menetapkan password pribadi minimal 16 karakter. Setelah itu anggota hanya melihat inbox dan pesan miliknya.
4. Sender memilih anggota, menulis pesan, lalu mengirim. Aplikasi membuat challenge empat simbol untuk pesan dan menyimpannya bersama envelope terenkripsi.
5. Receiver melihat challenge di **Kotak masuk**, memasukkan urutan empat simbol ke perangkat passkey Wemos yang `MASTER_SECRET`-nya sama persis dengan secret key anggota, lalu mengetik respons 12 simbol perangkat di browser.
6. Perhitungan HMAC passkey mengikuti firmware: HMAC-SHA-256 dengan secret key anggota dan empat byte challenge bernilai `0`–`3`; tidak ada prefix maupun ID anggota dalam input HMAC. Respons 12 simbol hanya memiliki 24 bit kemungkinan, jadi mudah ditebak dengan brute force — gunakan hanya untuk demo/data sintetis, bukan komunikasi nyata. Password akun hanya untuk autentikasi.
7. Sender dapat membuat ulang akun/password sementara anggota dari **Kelola anggota**. Tindakan itu mencabut sesi receiver sebelumnya dan mengharuskan penggantian password saat login berikutnya; secret key enkripsi tidak berubah.
8. **Hapus ciphertext** mengosongkan paket pesan pada database aplikasi. Ini bukan jaminan penghapusan fisik dari WAL, backup, atau media penyimpanan PostgreSQL.

Setiap anggota sebaiknya menggunakan secret key acak yang berbeda. Jika kunci hilang, pesan lama tidak dapat dibuka; daftarkan anggota/kunci baru untuk komunikasi selanjutnya. Verifier di server masih dapat digunakan untuk tebakan offline jika kunci lemah, jadi jangan memakai password manusia.

## Struktur Proyek

```
enkripsih/
├── run.py                     # Entry point lokal (Windows)
├── requirements.txt           # Dependency Python
├── pyproject.toml
├── .env.example               # Template env vars
├── frontend/
│   ├── index.html             # UI utama (Sender & Receiver)
│   ├── css/style.css          # Design system tactical data terminal
│   └── js/
│       ├── app.js             # State + router
│       ├── auth.js            # Login, session, cookie
│       ├── commander.js       # Alur kirim pesan (Sender)
│       ├── receiver.js        # Alur buka pesan (Receiver)
│       ├── message_crypto.js  # Web Crypto: derive verifier
│       ├── keybca_token.js    # Helper 12-simbol response
│       └── tour.js            # Onboarding tour
├── backend/
│   ├── main.py                # FastAPI app + semua endpoint
│   ├── database.py            # Schema + migrasi + CRUD
│   ├── crypto_engine.py       # KeyBCA: HMAC, PBKDF2, AES-GCM
│   ├── env_agents.py          # Encrypt/decrypt agent_secret di DB
│   ├── face_auth.py           # Face auth (backend only)
│   ├── secure_backup.py       # Backup terenkripsi SQLite
│   └── tests/                 # pytest (34 test)
├── iot_microcontroller/
│   ├── wemos_d1_mini/         # Sketch Arduino + OLED + tombol
│   └── esp32_keybca/         # Versi ESP32
└── slides/
    ├── tools-tech.md          # Tabel tools & teknologi
    └── diagrams/              # Flowchart Mermaid
```

## Menjalankan di Windows

Siapkan environment dan dependency:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Atur `ENKRIPSIH_PASSWORD` ke password login unik minimal 16 karakter. Untuk Neon/PostgreSQL, isi `DATABASE_URL` menggunakan connection string dari panel provider dan pertahankan TLS (`sslmode=require`). Encode karakter khusus dalam password URL (misalnya `@` menjadi `%40`). Jangan memasukkan kredensial ke Git atau membagikannya. Jika teman Anda ingin testing lokal, berikan file `.env.example` dan minta dia membuat kredensial miliknya sendiri untuk keamanan.

Sesi login otomatis berakhir setelah 5 menit tanpa aktivitas. Atur `ENKRIPSIH_SESSION_IDLE_TIMEOUT_SECONDS` di environment deployment untuk mengubahnya; nilainya harus antara 1 dan 86400 detik. Aktivitas aplikasi memperpanjang sesi, sedangkan heartbeat koneksi latar belakang tidak dihitung sebagai aktivitas.

Password akun receiver disimpan sebagai hash PBKDF2-HMAC-SHA-256 dengan salt acak. Password sementara hanya dikembalikan saat akun dibuat/direset; aplikasi tidak memiliki fitur pemulihan password lama.

Jika `DATABASE_URL` dikosongkan, aplikasi memakai SQLCipher lokal dan meminta passphrase database yang berbeda dari password login. Simpan file database beserta file kunci `.key.argon2`; kehilangan salah satunya dapat membuat database tidak dapat dibuka.

Jalankan server:

```powershell
.\.venv\Scripts\python.exe run.py
```

Buka <http://localhost:8000>. `run.py` membaca `.env`. Jangan expose port ke internet atau mengubah bind address dari localhost tanpa meninjau autentikasi, TLS, pembatasan percobaan, dan deployment multi-instance.

## Menjalankan di Vercel

Backend (FastAPI) di-deploy sebagai serverless function. Frontend disajikan oleh FastAPI melalui `/static` dan `/`.

**Env vars yang perlu di-set di Vercel Dashboard:**

| Var | Contoh | Keterangan |
|---|---|---|
| `ENKRIPSIH_PASSWORD` | 32 char acak | Password login Sender, minimal 16 char |
| `ENKRIPSIH_KEYBCA_SECRET` | 32 char acak | Master key KeyBCA, minimal 16 char — harus sama di semua Wemos |
| `ENKRIPSIH_DB_PASSPHRASE` | 32 char acak | Passphrase SQLCipher (kalau pakai SQLite), minimal 16 char |
| `DATABASE_URL` | `postgresql://...` | Connection string Neon (US-East-2), `sslmode=require` |
| `ENKRIPSIH_SESSION_IDLE_TIMEOUT_SECONDS` | `300` | Optional, default 300 detik |

> **Catatan:** `.env` tidak persist di Vercel runtime. Kunci agen untuk receiver baru disimpan terenkripsi di database (`agent_secret`), jadi tidak perlu menambah env var tiap daftar anggota baru.

## Migrasi Lokal ke PostgreSQL

Hentikan server, buat backup terenkripsi dan uji pemulihannya. Pastikan `DATABASE_URL` menunjuk ke database PostgreSQL baru yang kosong. Lalu:

```powershell
.\.venv\Scripts\python.exe -m backend.migrate_to_postgres --source E:\enkripsih\backend\enkripsih.db
```

Migrator meminta passphrase database lokal (jika sumber terenkripsi) dan konfirmasi `MIGRATE`. Record lama tanpa penerima baru ditandai `LEGACY`. Migrator tidak menghapus sumber lokal.

## Pengujian

Jalankan tes:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -v
```

Tes transmisi memeriksa endpoint pengiriman, penyimpanan ciphertext tanpa metadata/plaintext lama, verifikasi secret key, round-trip AES-GCM dengan kunci cocok, kegagalan kunci salah, autentikasi API, status pesan lama, serta penghapusan ciphertext. Saat ini: **34 test pass**.

## Video Demo
Lihat demonstrasi penggunaan alat fisik untuk membuka pesan di [`VIDEO_DEMO.md`](VIDEO_DEMO.md).

- Gunakan hanya `localhost` untuk demo; API dan WebSocket memerlukan sesi login.
- Secret key tidak dikirim sebagai field API, tetapi verifier dikirim untuk verifikasi. Kode frontend disajikan oleh aplikasi, sehingga server yang dikompromikan dapat mengubah kode enkripsi/dekripsi.
- Jangan mencatat, menempelkan, atau mengirim secret key maupun connection string ke log, chat, issue publik, atau repositori.
- Endpoint token IoT lama bukan bagian dari alur UI pesan dan bukan pengganti autentikasi perangkat yang aman.

## Dokumentasi & Materi

| Materi | Link |
|---|---|
| Flowchart & diagram alur | [Google Drive](https://drive.google.com/drive/folders/1GI7Vqc96OBDakjI7JJHdpANcP_7V6cju?usp=sharing) |
| Simulasi Wemos D1 Mini (Wokwi) | [wokwi.com/projects/479672497803902977](https://wokwi.com/projects/479672497803902977) |
| Tabel tools & teknologi | [`slides/tools-tech.md`](slides/tools-tech.md) |
| Diagram Mermaid (source) | [`slides/diagrams/00-ringkasan.mmd`](slides/diagrams/00-ringkasan.mmd) |
| Live demo | <https://enkripsih.vercel.app> |
