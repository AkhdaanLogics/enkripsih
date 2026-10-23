# ENKRIPSIH - Tactical Intelligence IoT Hub & KeyBCA Token Decoder

Sistem demo transmisi pesan dengan enkripsi **PBKDF2 + AES-GCM** dan alur token bergaya **KeyBCA** menggunakan empat simbol (**△ Triangle, ○ Circle, ✕ Cross, □ Square**). Backend lokal memakai login password, sesi untuk API, dan database SQLCipher dengan kunci yang dilindungi Windows DPAPI. Ini masih prototipe: jangan gunakan untuk pesan sensitif atau produksi.

---

## 📐 Arsitektur Sistem 3 Device

```
  [Device 1: Laptop Komandan] (Sender)
     │
     ├── 1. Login password aplikasi
     ├── 2. Tulis Pesan Intelijen & Tentukan Klasifikasi (Top Secret)
     ├── 3. Enkripsi AES-GCM & Generate 4-Simbol Challenge (contoh: △ ○ ✕ □ / TCXS)
     ▼
  [Server / Backend Enkripsih (Python FastAPI)]
     │
     ├── Menyimpan Ciphertext (Kunci Dekripsi TIDAK Disimpan di Server!)
     │
     ├──► Broadcast Challenge ke:
     │
     ├─────────► [Device 2: Wemos D1 Mini / ESP32 Token] (Pemecah Kode)
     │                │
     │                ├── Memasukkan 4 Simbol Challenge via 4 Tombol Fisik
     │                ├── Chip Hardware menghitung HMAC-SHA256 (<2ms)
     │                └── Layar OLED Menampilkan 12 Simbol Respon Dekripsi
     │
     └─────────► [Device 3: Receiver Terminal (Bawahan)] (Penerima)
                      │
                      ├── Menerima notifikasi transmisi terenkripsi
                      ├── Memasukkan 12 Simbol Respon Token dari KeyBCA
                      └── Ciphertext didekripsi & Pesan Taktis Terbuka!
```

---

## 🔣 Pemetaan Simbol Kriptografi

| Simbol Grafis | Huruf Shorthand | Nilai Index | Keterangan |
| :---: | :---: | :---: | :---: |
| **△** | `T` | `0` | Triangle |
| **○** | `C` / `O` | `1` | Circle |
| **✕** | `X` | `2` | Cross |
| **□** | `S` | `3` | Square |

- **Panjang Challenge:** 4 Simbol (contoh: `△ ○ ✕ □` / `TCXS`)
- **Panjang Respon Token:** 12 Simbol (contoh: `TCXSSTCCXTSC`)
- **Kunci Dekripsi:** Diturunkan secara lokal via `PBKDF2-HMAC-SHA256(Respon, Salt, 200.000 iterasi)`.

---

## 🚀 Fitur Utama

1. **Akses aplikasi:**
   - Login memakai password aplikasi (minimal 16 karakter) yang dimasukkan saat server dijalankan.
   - Endpoint API dan WebSocket memerlukan sesi login.

2. **KeyBCA Symbol Challenge-Response Engine:**
   - Emulator browser untuk pengujian alur challenge-response.
   - **Virtual Skeuomorphic KeyBCA Token** di web: body realistis, LCD dot-matrix, tombol simbol taktis (`△`, `○`, `✕`, `□`), dan tombol merah `OK/Power`.

3. **Optimasi untuk ESP32 / Wemos D1 Mini (ESP8266):**
   - Eksekusi instan (<2 milidetik) dan hemat RAM (<1KB).
   - Mendukung input tombol fisik, layar OLED I2C 128x64, Serial Monitor USB, atau kirim langsung via WiFi HTTP.
   - Disertakan script `serial_bridge.py` untuk menghubungkan mikrokontroler via kabel USB langsung ke web!

4. **Receiver Terminal (Prajurit / Intel Bawahan):**
   - Monitoring kotak masuk transmisi secara real-time via WebSockets.
   - Kolom validasi token KeyBCA 12-simbol.
   - Animasi dekripsi teks ala Cyber/Matrix deciphering.
   - Fitur penghancuran pesan permanen (*Burn / Self-Destruct*).

---

## 📂 Struktur Direktori Proyek

```
e:\enkripsih/
├── backend/
│   ├── main.py              # FastAPI Web & WebSocket Server
│   ├── crypto_engine.py     # PBKDF2 + AES-GCM & Algoritma Respon Simbol HMAC-SHA256
│   ├── face_auth.py         # Endpoint opsional deteksi & verifikasi wajah
│   └── database.py          # SQLite persistence untuk pesan dan user
├── frontend/
│   ├── index.html           # Formulir kirim pesan terenkripsi
│   ├── css/
│   │   └── style.css        # Desain Dark Military Cyber UI
│   └── js/
│       ├── app.js           # Core state, Web Audio synthesizer, WebSocket
│       ├── face_auth.js     # Biometric webcam scanner controller
│       ├── commander.js     # Intel composer & sender logic
│       ├── keybca_token.js  # KeyBCA virtual emulator (Simbol △ ○ ✕ □)
│       └── receiver.js      # Receiver inbox & decryptor
├── iot_microcontroller/
│   ├── esp32_keybca/
│   │   └── esp32_keybca.ino # Firmware C++ siap flash ke ESP32 / Wemos D1 Mini
│   └── wemos_d1_mini/
│       ├── serial_bridge.py # Python USB Serial forwarder ke backend
│       └── WIRING_GUIDE.md  # Panduan skema pinout & wiring
├── run.py                   # Script sekali klik untuk menjalankan server
└── README.md
```

---

## ⚡ Cara Menjalankan

### 1. Menjalankan Server Web (Backend + Frontend)
Buka PowerShell di direktori proyek, siapkan dependensi sekali:
```bash
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
Lalu jalankan server:
```powershell
.\.venv\Scripts\python.exe run.py
```
Akses di browser:
- **Web Application:** [http://localhost:8000](http://localhost:8000)
- **Dokumentasi API Swagger:** [http://localhost:8000/docs](http://localhost:8000/docs)

Saat mulai, terminal meminta password login dan passphrase database (keduanya minimal 16 karakter dan harus berbeda). Passphrase database tidak disimpan ke file konfigurasi. SQLCipher mengenkripsi database; kunci database acak dibungkus dengan AES-GCM, menggunakan kunci turunan Argon2id (3 iterasi, 64 MiB memori) dan disimpan di `backend\enkripsih.db.key.argon2`. Lupa passphrase atau kehilangan file kunci berarti database tidak dapat dibuka.

Server hanya menerima koneksi dari komputer ini (`127.0.0.1`). Semua API dan WebSocket memerlukan sesi login, cookie sesi HttpOnly/SameSite, dan percobaan login dibatasi. Jangan mengubah host ke `0.0.0.0` atau meneruskan port `8000` ke internet.

Pada startup pertama dengan database lama yang masih plaintext, server akan meminta konfirmasi `MIGRATE`. Buat backup terenkripsi dan pastikan proses restore berhasil sebelum mengonfirmasi. Migrasi memverifikasi salinan SQLCipher sebelum mengganti file lama; file plaintext asli dihapus setelah penggantian berhasil. Jika database masih memakai key DPAPI versi sebelumnya, key akan dibungkus ulang dengan passphrase database dan file DPAPI lama dihapus setelah verifikasi.

Buat backup terenkripsi sebelum migrasi (hentikan server dulu):
```powershell
.\.venv\Scripts\python.exe -m backend.secure_backup backup --output D:\Enkripsih-Backup\enkripsih-sebelum-migrasi.enc
```
Masukkan passphrase database saat diminta jika database sudah terenkripsi, lalu pilih dan konfirmasi passphrase backup. File `.enc` dienkripsi dengan AES-GCM dan kunci turunan Argon2id; ia dapat dipindahkan ke komputer lain, tetapi tetap membutuhkan passphrase backup (dan passphrase database asli untuk backup dari database terenkripsi). Restore ke lokasi baru, jangan menimpa database aktif:
```powershell
.\.venv\Scripts\python.exe -m backend.secure_backup restore --source D:\Enkripsih-Backup\enkripsih-sebelum-migrasi.enc --output D:\Enkripsih-Backup\enkripsih-restore-check.db
```
Backup lama yang dibuat sebelum perubahan passphrase memakai DPAPI dan hanya bisa dipulihkan pada profil Windows pembuat backup. Jika restore menghasilkan database plaintext, lanjutkan migrasi saat server berikutnya dijalankan; hapus file plaintext hasil restore setelah pemeriksaan.

### Mode PostgreSQL untuk hosting
Mode lokal tetap memakai SQLCipher. Untuk memakai PostgreSQL jarak jauh, install dependency terbaru (`.\.venv\Scripts\python.exe -m pip install -r requirements.txt`), buat database PostgreSQL kosong dengan TLS dari provider pilihan, lalu hentikan aplikasi dan buat backup terverifikasi. Jangan masukkan connection string ke source code atau Git.

#### PostgreSQL yang dipasang di Windows (lokal)
1. Jalankan installer PostgreSQL, pastikan komponen **PostgreSQL Server** dan **pgAdmin 4** terpilih, lalu selesaikan instalasi. Ingat password yang Anda buat untuk role administrator `postgres`.
2. Buka pgAdmin 4, sambungkan ke server lokal, buka **Query Tool**, lalu buat role dan database khusus aplikasi (ganti password contoh dengan password kuat):
   ```sql
   CREATE ROLE enkripsih_app LOGIN PASSWORD 'GANTI_DENGAN_PASSWORD_KUAT';
   CREATE DATABASE enkripsih OWNER enkripsih_app;
   ```
3. Di PowerShell, isi connection string lokal. URL-encode karakter khusus dalam password (`@` menjadi `%40`, misalnya):
   ```powershell
   $env:DATABASE_URL = "postgresql://enkripsih_app:PASSWORD_URL_ENCODED@localhost:5432/enkripsih?sslmode=disable"
   ```
   `sslmode=disable` hanya untuk server PostgreSQL di komputer yang sama. Untuk database cloud/remote, gunakan TLS dan jangan menurunkan SSL mode.

Di PowerShell, atur URL database sebagai environment variable untuk sesi terminal ini:
```powershell
$env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require"
```
Pindahkan data yang sudah ada dengan utility migrasi; utility menolak target yang sudah berisi pesan atau audit log:
```powershell
.\.venv\Scripts\python.exe -m backend.migrate_to_postgres --source E:\enkripsih\backend\enkripsih.db
```
Masukkan passphrase database lokal saat diminta, lalu ketik `MIGRATE`. Utility memverifikasi jumlah record dan tidak menghapus database lokal. Untuk menjalankan API terhadap PostgreSQL lokal, pertahankan `$env:DATABASE_URL` dan jalankan `.\.venv\Scripts\python.exe run.py`; login aplikasi tetap diminta, tetapi passphrase SQLCipher lokal tidak digunakan.

Untuk deployment Vercel, set `DATABASE_URL` dan `ENKRIPSIH_PASSWORD` sebagai environment secrets di project settings (jangan gunakan `run.py`, karena itu meminta input interaktif). `pyproject.toml` mengarahkan entrypoint FastAPI. Ini mengaktifkan persistence PostgreSQL, tetapi **belum membuat seluruh aplikasi siap produksi/serverless**: broadcast WebSocket lintas instance masih memakai koneksi di memori tiap proses, pembatasan percobaan login juga lokal per proses, dan frontend/static routing harus diuji di deployment. Vercel Functions berjalan di lingkungan cloud; gunakan hanya data sintetis untuk demo dan tinjau kebijakan penyimpanan/lokasi provider.

Database lokal melindungi file saat tidak digunakan, bukan dari malware yang berjalan sebagai akun Windows Anda. Isi pesan setelah didekripsi masih disimpan di database. Alur KeyBCA dan firmware saat ini tetap bukan perlindungan kriptografi yang layak untuk pesan sungguhan; jangan gunakan data sensitif.

Untuk keamanan, endpoint IoT sekarang juga berada di balik sesi browser. Virtual KeyBCA di web tetap dapat digunakan setelah login, tetapi firmware/serial bridge lama belum membawa kredensial sesi dan akan ditolak; jangan membuka kembali endpoint perangkat tanpa rancangan autentikasi perangkat khusus.

---

### 2. Cara Menguji Seluruh Alur (Tanpa Hardware Fisik)
Kamu bisa langsung menguji seluruh konsepnya di browser:
1. Buka [http://localhost:8000](http://localhost:8000).
2. Masukkan password aplikasi yang diminta saat server dijalankan. Setelah login, pilih penerima, isi subjek dan pesan, lalu klik **"Enkripsi & Transmisikan Pesan"**.
3. Status sukses hanya muncul setelah server mengonfirmasi pesan berstatus terkunci dan ciphertext ditemukan kembali melalui API. Jika konfirmasi gagal, pesan tidak dilaporkan sebagai terkirim-terverifikasi.
4. Pindah ke tab **Token KeyBCA**:
   - Klik tombol merah **OK / POWER** untuk menyalakan token.
   - Tekan 4 tombol simbol sesuai challenge (contoh: tekan `△`, `○`, `✕`, `□`).
   - Token akan langsung menghitung dan menampilkan 12 simbol respon di layar (contoh: `TCXSSTCCXTSC`).
   - Klik **"Salin Token"** (atau klik **"Kirim via IoT"**).
5. Pindah ke tab **Kotak masuk**:
   - Pesan yang terenkripsi akan terlihat di inbox.
   - Masukkan 12 simbol respon token tadi ke kolom respon & klik **"DEKRIPSI DENGAN TOKEN KEYBCA"**.
   - Efek dekripsi teks Matrix akan berjalan dan pesan rahasia Komandan langsung terbuka!

### 3. Tes Pengiriman Pesan
Jalankan tes dari direktori proyek untuk membuktikan pesan tersimpan sebagai ciphertext dan hanya dapat dibuka dengan token yang tepat:
```bash
python -m unittest discover -s backend\tests -v
```
Tes memakai database sementara, memeriksa kontrol sesi API, enkripsi SQLCipher, Argon2id, migrasi database lama/DPAPI, serta backup dan restore terenkripsi; tes juga memastikan pesan kosong ditolak dan plaintext tidak tersimpan sebelum dekripsi.

### Batas keamanan dan API
Endpoint API dan WebSocket dilindungi sesi login; endpoint daftar/detail pesan tidak mengirim ciphertext atau token respons tersimpan. Token percobaan yang salah tidak dicatat ke audit log, dan endpoint audit log publik tidak tersedia. Mutasi API juga memeriksa Origin bila header tersebut dikirim.

SQLCipher melindungi database saat file tidak digunakan. Perlindungan ini tidak menghentikan malware yang berjalan sebagai akun Windows yang sama, dan pesan yang sudah didekripsi tetap disimpan sebagai plaintext di database. Enkripsi pesan dan alur token KeyBCA masih prototipe, bukan skema end-to-end yang telah diaudit. Tetap jalankan hanya di localhost dan jangan gunakan data sensitif.

---

### 4. Cara Menggunakan Board Hardware (ESP32 / Wemos D1 Mini)
1. Hubungkan mikrokontroler ke laptop via kabel USB.
2. Buka Arduino IDE, buka file [esp32_keybca.ino](file:///e:/enkripsih/iot_microcontroller/esp32_keybca/esp32_keybca.ino) dan klik **Upload**.
3. Hubungkan pin tombol & OLED sesuai diagram di tab `Panduan`.
4. Setelah ter-upload, kamu bisa:
   - **Metode A (Offline/Air-gapped):** Lihat 4 simbol challenge di web, tekan 4 tombol di alat fisik, lihat 12 simbol respon di layar OLED, lalu ketik di web Receiver!
   - **Metode B (Serial Bridge Otomatis):** Jalankan di terminal:
     ```bash
     python iot_microcontroller/wemos_d1_mini/serial_bridge.py
     ```
     **Catatan:** Firmware/serial bridge lama belum mendukung autentikasi sesi aplikasi, sehingga endpoint perangkat akan menolaknya. Jangan gunakan metode pengiriman otomatis atau membuka kembali endpoint tersebut sebelum autentikasi perangkat dirancang dan diuji.
