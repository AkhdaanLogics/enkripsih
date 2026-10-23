"""
Serial Bridge for Wemos D1 Mini / ESP32 to Enkripsih Web API
Reads token calculation events from the Microcontroller over USB COM port
and forwards them to the Enkripsih backend in real time.
"""

import sys
import time
import requests
import serial
import serial.tools.list_ports

BACKEND_URL = "http://localhost:8000/api/iot/keybca/solve"

def find_serial_ports():
    ports = serial.tools.list_ports.comports()
    return [p.device for p in ports]

def run_bridge(port: str = None, baud: int = 115200):
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

                    print(f"\n[>>>] Token Terdeteksi! Challenge: {part_chal} -> Response: {part_resp}")

                    payload = {
                        "device_id": f"KEYBCA-{port}",
                        "challenge": part_chal,
                        "token": part_resp
                    }
                    res = requests.post(BACKEND_URL, json=payload, timeout=3)
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
