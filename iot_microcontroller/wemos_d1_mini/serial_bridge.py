"""
Serial Bridge for Wemos D1 Mini / ESP32 to Enkripsih Web API
Reads token calculation events from the Microcontroller over USB COM port
and forwards them to the Enkripsih backend in real time.

SECURITY: All requests are signed with HMAC-SHA256 using ENKRIPSIH_IOT_TOKEN
to prevent unauthenticated injection via the serial bridge.
"""

import hashlib
import hmac
import os
import sys
import time
import requests
import serial
import serial.tools.list_ports

BACKEND_URL = "http://localhost:8000/api/iot/keybca/solve"
_IOS_TOKEN = os.environ.get("ENKRIPSIH_IOT_TOKEN", "")


def sign(payload: str) -> str:
    """Compute HMAC-SHA256(payload, ENKRIPSIH_IOT_TOKEN)."""
    return hmac.new(_IOS_TOKEN.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def find_serial_ports():
    ports = serial.tools.list_ports.comports()
    return [p.device for p in ports]

def run_bridge(port: str = None, baud: int = 115200):
    if not _IOS_TOKEN:
        print("[!] ENKRIPSIH_IOT_TOKEN tidak di-set — bridge akan mengirim tanpa sign (mode dev).")
    available = find_serial_ports()
    if not available:
        print("[!] Tidak ada port USB Serial (COM) yang terdeteksi.")
        print("    Pastikan mikrokontroler sudah dicolokkan ke laptop via kabel USB.")
        return

    if not port:
        print("[*] Port yang tersedia:")
        for idx, p in enumerate(available):
            print(f"    [{idx + 1}] {p}")
        port = available[0]
        print(f"[*] Menggunakan port default: {port}")

    try:
        ser = serial.Serial(port, baud, timeout=1)
        print(f"[+] Terhubung ke Mikrokontroler di {port} @ {baud} bps.")
        print("[*] Menunggu event kalkulasi token dari KeyBCA (ESP32/Wemos)...\n")

        while True:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if not line:
                continue

            print(f"[SERIAL] {line}")

            # Detect: [KEYBCA TOKEN SOLVED] Challenge: TCXS -> Response: TCXSSTCCXTSC
            if "[KEYBCA TOKEN SOLVED]" in line and "Challenge:" in line and "Response:" in line:
                try:
                    part_chal = line.split("Challenge:")[1].split("->")[0].strip()
                    part_resp = line.split("Response:")[1].strip()

                    device_id = f"KEYBCA-{port}"
                    payload = f"{device_id}:{part_chal}:{part_resp}"
                    signature = sign(payload) if _IOS_TOKEN else None

                    print(f"\n[>>>] Token Terdeteksi! Challenge: {part_chal} -> Response: {part_resp}")

                    post_payload = {
                        "device_id": device_id,
                        "challenge": part_chal,
                        "token": part_resp,
                    }
                    if signature:
                        post_payload["hmac_signature"] = signature

                    headers = {"Content-Type": "application/json"}
                    if signature:
                        headers["x-hmac-signature"] = signature

                    res = requests.post(
                        BACKEND_URL,
                        json=post_payload,
                        headers=headers,
                        timeout=3
                    )
                    if res.status_code == 200:
                        print("[OK] Berhasil diteruskan ke server Enkripsih!\n")
                    else:
                        print(f"[!] Server merespon status: {res.status_code}")
                except Exception as e:
                    print(f"[!] Gagal memproses payload: {e}")

    except serial.SerialException as se:
        print(f"[!] Gagal membuka port {port}: {se}")
    except KeyboardInterrupt:
        print("\n[*] Serial Bridge dihentikan.")

if __name__ == "__main__":
    com_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run_bridge(com_arg)
