# ENKRIPSIH

Aplikasi demo untuk mengirim pesan terenkripsi ke anggota terdaftar. Pesan dienkripsi di browser dengan Web Crypto (PBKDF2-HMAC-SHA-256 dan AES-GCM), lalu server menyimpan paket ciphertext. Pesan passkey baru dibuka receiver hanya dengan respons dari perangkat passkey.

Ini prototipe, bukan sistem komunikasi produksi atau skema yang telah diaudit. Gunakan hanya data sintetis. Enkripsi sisi-klien membantu mencegah plaintext tersimpan pada database/API normal, tetapi tidak melindungi pengguna dari server atau JavaScript frontend yang telah dikompromikan, malware di perangkat, atau kebocoran secret key.

## Alur pemakaian

1. Komandan masuk dengan password aplikasi (`ENKRIPSIH_PASSWORD`).
2. Buka **Kelola anggota** untuk mendaftarkan anggota dan membuat secret key acak. Aplikasi membuat akun receiver dengan username berdasarkan nama anggota dan password sementara acak. Simpan keduanya saat hanya ditampilkan sekali; bagikan password akun dan secret key melalui kanal aman yang berbeda.
3. Anggota memilih jenis akun **Anggota receiver**, masuk dengan username dan password sementara, lalu wajib menetapkan password pribadi minimal 16 karakter. Setelah itu anggota hanya melihat inbox dan pesan miliknya.
4. Komandan memilih anggota, memasukkan secret key anggota, menulis pesan, lalu mengirim. Aplikasi membuat challenge empat simbol untuk pesan dan menyimpannya bersama envelope terenkripsi.
5. Receiver melihat challenge di **Kotak masuk**, memasukkan urutan empat simbol ke perangkat passkey yang `SECRET_KEY`-nya sama persis dengan secret key anggota, lalu mengetik respons 12 simbol perangkat di browser. Pesan versi 4–5 tidak meminta secret key di browser; pesan versi 1–3 masih memerlukannya.
6. Perhitungan HMAC passkey mengikuti firmware: HMAC-SHA-256 dengan secret key anggota dan empat byte challenge bernilai `0`–`3`; tidak ada prefix maupun ID anggota dalam input HMAC. Pesan versi 5 menurunkan kunci AES-GCM dengan PBKDF2-HMAC-SHA-256 dari 12 nilai simbol `0`–`3`, salt mentah, dan 200.000 iterasi sesuai `backend/crypto_engine.py`. Respons 12 simbol hanya memiliki 24 bit kemungkinan, jadi mudah ditebak dengan brute force: gunakan hanya untuk demo/data sintetis, bukan komunikasi nyata. Password akun hanya untuk autentikasi.
7. Komandan dapat membuat ulang akun/password sementara anggota dari **Kelola anggota**. Tindakan itu mencabut sesi receiver sebelumnya dan mengharuskan penggantian password saat login berikutnya; secret key enkripsi tidak berubah.
8. **Hapus ciphertext** mengosongkan paket pesan pada database aplikasi. Ini bukan jaminan penghapusan fisik dari WAL, backup, atau media penyimpanan PostgreSQL.

Setiap anggota sebaiknya menggunakan secret key acak yang berbeda. Jika kunci hilang, pesan lama tidak dapat dibuka; daftarkan anggota/kunci baru untuk komunikasi selanjutnya. Verifier di server masih dapat digunakan untuk tebakan offline jika kunci lemah, jadi jangan memakai password manusia.

Receiver yang sudah ada sebelum akun receiver ditambahkan belum memiliki login. Komandan perlu membuka **Kelola anggota** lalu memilih **Buat/reset akun receiver** untuk tiap anggota; password sementara hanya tampil sekali. Pesan lama dari skema sebelumnya ditandai `LEGACY`; pesan itu tidak kompatibel dengan kunci anggota baru. Migrasi menghapus kolom lama seperti `plaintext`, subject, prioritas, dan challenge. Buat dan verifikasi backup sebelum menjalankan migrasi database aktif.

## Menjalankan di Windows

Siapkan environment dan dependency:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Atur `ENKRIPSIH_PASSWORD` ke password login unik minimal 16 karakter. Untuk Neon/PostgreSQL, isi `DATABASE_URL` menggunakan connection string dari panel provider dan pertahankan TLS (`sslmode=require`). Encode karakter khusus dalam password URL (misalnya `@` menjadi `%40`). Jangan memasukkan kredensial ke Git atau membagikannya.

Sesi login otomatis berakhir setelah 5 menit tanpa aktivitas. Atur `ENKRIPSIH_SESSION_IDLE_TIMEOUT_SECONDS` di environment deployment untuk mengubahnya; nilainya harus antara 1 dan 86400 detik. Aktivitas aplikasi memperpanjang sesi, sedangkan heartbeat koneksi latar belakang tidak dihitung sebagai aktivitas.

Password akun receiver disimpan sebagai hash PBKDF2-HMAC-SHA-256 dengan salt acak. Password sementara hanya dikembalikan saat akun dibuat/direset; aplikasi tidak memiliki fitur pemulihan password lama.

Jika `DATABASE_URL` dikosongkan, aplikasi memakai SQLCipher lokal dan meminta passphrase database yang berbeda dari password login. Simpan file database beserta file kunci `.key.argon2`; kehilangan salah satunya dapat membuat database tidak dapat dibuka.

Jalankan server:

```powershell
.\.venv\Scripts\python.exe run.py
```

Buka <http://localhost:8000>. `run.py` membaca `.env`. Jangan expose port ke internet atau mengubah bind address dari localhost tanpa meninjau autentikasi, TLS, pembatasan percobaan, dan deployment multi-instance.

## Migrasi lokal ke PostgreSQL

Hentikan server, buat backup terenkripsi dan uji pemulihannya. Pastikan `DATABASE_URL` menunjuk ke database PostgreSQL baru yang kosong. Lalu:

```powershell
.\.venv\Scripts\python.exe -m backend.migrate_to_postgres --source E:\enkripsih\backend\enkripsih.db
```

Migrator meminta passphrase database lokal (jika sumber terenkripsi) dan konfirmasi `MIGRATE`. Record lama tanpa penerima baru ditandai `LEGACY`. Migrator tidak menghapus sumber lokal.

## Pengujian

Jalankan tes:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests -v
```

Tes transmisi memeriksa endpoint pengiriman, penyimpanan ciphertext tanpa metadata/plaintext lama, verifikasi secret key, round-trip AES-GCM dengan kunci cocok, kegagalan kunci salah, autentikasi API, status pesan lama, serta penghapusan ciphertext.

## Catatan keamanan

- Gunakan hanya `localhost` untuk demo; API dan WebSocket memerlukan sesi login.
- Secret key tidak dikirim sebagai field API, tetapi verifier dikirim untuk verifikasi. Kode frontend disajikan oleh aplikasi, sehingga server yang dikompromikan dapat mengubah kode enkripsi/dekripsi.
- Jangan mencatat, menempelkan, atau mengirim secret key maupun connection string ke log, chat, issue publik, atau repositori.
- Endpoint token IoT lama bukan bagian dari alur UI pesan dan bukan pengganti autentikasi perangkat yang aman.

## Antislop

Setiap kali bekerja di frontend (HTML, CSS, JS di `frontend/`), load **semua**
skill antislop berikut secara otomatis, tanpa perlu diminta:

- `antislop` — filter inti: desain harus terasa karya desainer, bukan AI
- `antislop-ui` — layout, komponen, warna, dekorasi, motion
- `antislop-code` — code style & anti-patterns
- `antislop-human` — accessibility & contrast (WCAG)
- `antislop-copywriting` — headline, CTA, teks UI
- `antislop-layoutmobile` — mobile layout & responsive

Skill terpasang di `.agents/skills/` (sumber: `miqdadbadjuber/anti-slop`).
