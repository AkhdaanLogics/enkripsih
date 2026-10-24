"""
Enkripsih - Startup Script
Launches the FastAPI backend and serves the frontend on http://localhost:8000
"""

import uvicorn
import os
from getpass import getpass
from dotenv import load_dotenv

load_dotenv()

from backend.database import database_needs_migration, database_needs_passphrase_setup


def configure_local_security():
    password = os.environ.get("ENKRIPSIH_PASSWORD")
    if not password:
        password = getpass("Buat/masukkan password aplikasi (minimal 16 karakter): ")
    if len(password) < 16:
        raise SystemExit("Password harus minimal 16 karakter. Server tidak dijalankan.")
    os.environ["ENKRIPSIH_PASSWORD"] = password

    if not os.environ.get("DATABASE_URL"):
        database_passphrase = os.environ.get("ENKRIPSIH_DB_PASSPHRASE")
        is_new_database_passphrase = database_needs_passphrase_setup()
        if not database_passphrase:
            database_passphrase = getpass(
                "Buat/masukkan passphrase database (minimal 16 karakter): "
            )
            if is_new_database_passphrase:
                confirmation = getpass("Ulangi passphrase database: ")
                if database_passphrase != confirmation:
                    raise SystemExit("Passphrase tidak cocok. Server tidak dijalankan.")
        if len(database_passphrase) < 16:
            raise SystemExit("Passphrase database harus minimal 16 karakter.")
        if database_passphrase == password:
            raise SystemExit("Passphrase database harus berbeda dari password login.")
        os.environ["ENKRIPSIH_DB_PASSPHRASE"] = database_passphrase

    if not os.environ.get("DATABASE_URL") and database_needs_migration():
        print(
            "\nDatabase lama belum terenkripsi. Sebelum lanjut, buat backup offline "
            "terenkripsi, lalu pastikan backup dapat dipulihkan."
        )
        confirmation = input("Ketik MIGRATE untuk mengenkripsi database lama: ")
        if confirmation != "MIGRATE":
            raise SystemExit("Migrasi dibatalkan; server tidak dijalankan.")
        os.environ["ENKRIPSIH_CONFIRM_DB_MIGRATION"] = "yes"

def main():
    configure_local_security()
    print("""
    ====================================================================
      ███████╗███╗   ██╗██╗  ██╗██████╗ ██╗██████╗ ███████╗██╗██╗  ██╗
      ██╔════╝████╗  ██║██║ ██╔╝██╔══██╗██║██╔══██╗██╔════╝██║██║  ██║
      █████╗  ██╔██╗ ██║█████═╝ ██████╔╝██║██████╔╝███████╗██║███████║
      ██╔══╝  ██║╚██╗██║██╔═██╗ ██╔══██╗██║██╔═══╝ ╚════██║██║██╔══██║
      ███████╗██║ ╚████║██║ ╚██╗██║  ██║██║██║     ███████║██║██║  ██║
      ╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝     ╚══════╝╚═╝╚═╝  ╚═╝
    ====================================================================
      Tactical Intelligence IoT Hub & KeyBCA Token Decoder System
      Hardware Target : Wemos D1 Mini (ESP8266)
    ====================================================================
      [+] Frontend & Backend  : http://localhost:8000
      [+] Interactive API Docs: http://localhost:8000/docs
      [+] WebSocket Server    : ws://localhost:8000/ws
    ====================================================================
    Tekan CTRL + C untuk menghentikan server.
    """)
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=False)

if __name__ == "__main__":
    main()
