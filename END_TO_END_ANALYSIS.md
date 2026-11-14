
# ENKRIPSIH — End-to-End Architecture Analysis

---

## 1. Mengapa Aplikasi Ini End-to-End (E2E)

End-to-end di sini berarti: seluruh alur kriptografis — dari generate key, enkripsi, transmisi, penyimpanan, hingga dekripsi — terjadi tanpa plaintext pernah menyentuh server.

### Tahap & Lokasi
- Key Generation: Browser (Commander) — crypto.subtle.generateKey + PBKDF2 600k iterasi
- Encryption: Browser (Commander) — AES-GCM 256-bit, IV random 96-bit
- Transmission: HTTPS (TLS 1.2+) — hanya ciphertext (paket JSON) yang transit
- Storage: Server (PostgreSQL / SQLCipher) — ciphertext status LOCKED, verifier key terpisah
- Key Exchange: Hardware KeyBCA (ESP32/Wemos) — Challenge 4 simbol → HMAC-SHA256 → 12 simbol response
- Key Derivation: Browser (Receiver) — PBKDF2 200k iterasi dari 12 simbol + salt → AES-GCM key
- Decryption: Browser (Receiver) — AES-GCM decrypt, verifikasi tag, plaintext ditampilkan

Bukti teknis:
- Frontend: frontend/js/crypto.js → deriveBitsFromDeviceResponse(), encryptMessage(), decryptMessage()
- Backend: main.py → /api/messages/encrypt (hanya simpan paket), /api/messages/decrypt (hanya validasi PBKDF2 + AES-GCM tag)
- Server tidak pernah menerima secret key, passphrase, atau plaintext.

## 2. Kelebihan (Strengths)
- Keamanan Kriptografis: AES-GCM, PBKDF2 600k/200k, Argon2id, HMAC-SHA256
- Zero-Trust Server: Server cannot decrypt meski db dicuri
- Hardware-Bound Decryption: Receiver butuh device fisik KeyBCA → 2FA hardware-native
- Key Rotation & Revocation: /reissue generate salt+verifier baru, ciphertext lama tetap decryptable
- Agent Key Management: Secret key agen dienkripsi AES-GCM, simpan di DB, fallback .env
- Audit Trail Lengkap: Semua auth, transmit, decrypt, burn, key rotation, login attempt → audit_logs
- Session Security: HttpOnly Secure SameSite=Lax, idle timeout 5 menit, lockout 5× → 5 menit
- CSP Strict: default-src self; script-src self; style-src self; no inline, no CDN
- Database Encryption at Rest: SQLCipher + Argon2id-wrapped master key / PostgreSQL TLS
- Backup/Restore Terintegrasi: Argon2id + AES-GCM, integrity check, legacy DPAPI support
- Face Biometric (2FA Commander): Haar cascade + histogram, threshold 75%, explicit enrollment
- Responsive UI: Grid 2-col desktop, stack mobile, touch targets 44px+, dark mode via CSS vars

## 3. Kekurangan (Weaknesses / Known Gaps)
1. Agent secret encryption key turunan dari ENKRIPSIH_KEYBCA_SECRET (Tinggi) — rotate secret = semua agent key undecryptable. Perlu ENKRIPSIH_AGENT_WRAP_KEY terpisah.
2. /api/auth/login return 200 body kosong saat gagal (Sedang) — leak timing, API inkonsisten. Harus 401 JSON seragam.
3. Face auth pakai Haar cascade + block-mean histogram (Sedang) — mudah spoof. Hanya second factor.
4. CORS trusted proxy detection hanya private IP ranges (Sedang) — risiko di belakang cloud LB.
5. Rate-limit decrypt pakai tabel login_lockouts prefix decrypt: (Rendah) — collision potential.
6. Tidak ada API versioning (Rendah) — breaking change butuh coordinated deploy.
7. /api/health expose session store type & DB host (Rendah) — info leak. Gate behind ENKRIPSIH_ENABLE_DOCS.
8. In-memory session fallback (Vercel) wipe on cold start (Ops) — gampang misconfigure.
9. Tidak ada request body size limit global (Rendah) — FastAPI default unlimited.
10. Font Google Fonts di index.html tapi CSP font-src self (Rendah) — browser block. Hapus link, pakai WOFF2 lokal.

## 4. Tech Stack — Frontend
- Vanilla HTML/CSS/JS (ES2022, no bundler): Zero dep, CSP-friendly, auditable, deploy static
- CSS Custom Properties: Design tokens terpusat (--pad, --radius-card, --elevation-*, --font-sans/mono)
- Web Crypto API: crypto.subtle — PBKDF2, AES-GCM, HKDF, generateKey — hardware-accelerated
- WebSocket API: Real-time update tanpa polling berlebih
- IntersectionObserver: Lazy-load / scroll-aware tour highlights
- Fetch API + AbortController: Request cancellation, timeout handling
- IndexedDB (opsional): Cache ciphertext untuk offline decrypt

Tidak pakai: React/Vue/Svelte, TypeScript, Webpack/Vite, Tailwind, npm runtime deps.
Alasan: Surface area minimal, CSP strict, bundle < 50 KB gzipped, cold start instan.

## 5. Tech Stack — Backend
- Python 3.11+: Stdlib kaya, crypto library matang
- FastAPI 0.109+: Async native, OpenAPI otomatis, Pydantic validation, performa tinggi
- Uvicorn 0.27+: ASGI server production-ready, worker multiprocess via Gunicorn
- SQLCipher (sqlcipher3) 4.x: SQLite + AES-256 transparent encryption, zero-config local dev
- PostgreSQL (psycopg3) 15+: Production DB, connection pooling, TLS, JSONB, horizontal scale
- Argon2 (argon2-cffi) 21.3+: Memory-hard KDF untuk wrap DB master key (RFC 9106)
- cryptography 42+: AES-GCM, PBKDF2, HKDF — constant-time, FIPS-aware, audited
- OpenCV (opencv-python-headless) 4.9+: Face detection (Haar) + feature extraction
- python-dotenv 1.0+: Load .env lokal, production pakai env vars asli
- argon2.low_level: Direct Argon2id API untuk key_protection.py seal/unseal

Arsitektur Database:
Local Dev: SQLite + SQLCipher (enkripsih.db + .key.argon2)
Production: PostgreSQL (DATABASE_URL) + TLS
Migration: migrate_to_postgres.py (one-way, idempotent)
Backup: secure_backup.py (Argon2id + AES-GCM, integrity check)

Dependency Pinning: requirements.txt + pip-tools/uv untuk reproducible build.

## 6. Alasan Arsitektur Utama
- Client-side encryption: Threat model honest but curious / db leak
- Hardware KeyBCA (ESP32): Hilangkan phishing, keylogger, clipboard steal
- PBKDF2 600k/200k: 600k ≈ 1.2s → brute-force infeasible; 200k user-facing tapi tetap mahal
- AES-GCM 256-bit: Authenticated encryption, IV 96-bit random → nonce misuse resistance
- Salt per-message 16 byte: Mencegah rainbow table & key reuse
- Argon2id untuk DB key wrap: Memory-hard (64 MiB, t=3, p=4) → GPU/ASIC resistant
- Session cookie + idle timeout: Stateful auth simpel, revocable, CSRF-safe
- WebSocket untuk real-time: Lebih efisien dari polling 15s; event-driven
- CSP strict tanpa unsafe-inline: Mitigasi XSS klasik
- Vanilla frontend: Auditability — setiap baris JS bisa dibaca reviewer
- Dual DB mode: Dev lokal zero-config, prod scale-out PostgreSQL

## 7. Checklist Production Readiness
- HTTPS/TLS terminasi ✅ (reverse proxy Nginx/Caddy/Cloudflare)
- ENKRIPSIH_PASSWORD ≥16 char ✅ (enforced di lifespan)
- ENKRIPSIH_KEYBCA_SECRET ≥16 char ✅ (enforced di lifespan)
- ENKRIPSIH_IOT_TOKEN configured ✅ (required untuk IoT endpoints)
- DATABASE_URL (PostgreSQL + sslmode=require) ✅ (production wajib)
- ENKRIPSIH_DB_PASSPHRASE (local only) ✅ (≥16 char)
- ENKRIPSIH_ENABLE_DOCS=0 (prod) ✅ (disable Swagger)
- CSP header aktif ✅ (middleware protect_api)
- HSTS header ✅ (max-age=31536000; includeSubDomains)
- Secure cookie flags ✅ (httponly, secure, samesite=lax)
- Rate limit login/decrypt ✅ (5× → 300s lockout)
- Audit log enabled ✅ (tabel audit_logs)
- Backup terjadwal ⚠️ Manual (python -m backend.secure_backup backup)
- Font WOFF2 lokal ✅ (frontend/fonts/ — hapus link Google Fonts)
- Health check endpoint ✅ (/api/health, strip di prod via ENKRIPSIH_ENABLE_DOCS)

## 8. Ringkasan
ENKRIPSIH adalah sistem pengiriman pesan terenkripsi end-to-end yang lengkap untuk skenario komando–anggota dengan hardware token (KeyBCA).

Kekuatan: Crypto solid, zero-trust server, hardware-bound decrypt, key rotation, audit trail, DB encryption at rest, backup/restore, CSP strict.
Risiko utama: Agent secret key wrap tergantung KeyBCA secret (perlu dipisah), face auth lemah (hanya 2FA), login error handling inkonsisten.
Siap produksi dengan catatan: fix 3 item severity Tinggi/Sedang, pastikan env vars production ter-set, hapus Google Fonts link, schedule backup otomatis.
