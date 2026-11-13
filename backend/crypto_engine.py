"""
Crypto Engine for Enkripsih
Uses the tactical Symbol-based KeyBCA algorithm (Triangle, Circle, Cross, Square)
matching the user's Python Colab scripts and ESP32 / Wemos D1 Mini microcontroller sketches.
"""

import os
import json
import hmac
import hashlib
import base64
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

CHAL_LEN = 4
RESP_LEN = 12
KEYBCA_SECRET_ENV = "ENKRIPSIH_KEYBCA_SECRET"  # nosec B105 — env var name string, not a password
KEYBCA_SECRET_MIN_LENGTH = 16

NAMES = ["△", "○", "✕", "□"]   # 0=T 1=C 2=X 3=S
LETTERS = "TCXS"

SYMBOL_MAP = {
    "T": 0, "△": 0,
    "C": 1, "O": 1, "○": 1,
    "X": 2, "✕": 2,
    "S": 3, "□": 3
}

def generate_tactical_challenge():
    """
    Generates a 4-symbol challenge (e.g. [0, 2, 1, 3] -> 'TXCS' / '△ ✕ ○ □')
    """
    challenge_indices = [secrets.randbelow(4) for _ in range(CHAL_LEN)]
    challenge_letters = "".join(LETTERS[c] for c in challenge_indices)
    challenge_symbols = " ".join(NAMES[c] for c in challenge_indices)
    return {
        "indices": challenge_indices,
        "letters": challenge_letters,
        "symbols": challenge_symbols
    }

def _get_keybca_secret() -> bytes:
    secret = os.environ.get(KEYBCA_SECRET_ENV, "")
    if not secret or len(secret) < KEYBCA_SECRET_MIN_LENGTH:
        raise RuntimeError(
            f"{KEYBCA_SECRET_ENV} belum diatur atau kurang dari {KEYBCA_SECRET_MIN_LENGTH} karakter. "
            "Jalankan aplikasi lewat run.py untuk memasukkan secret KeyBCA."
        )
    return secret.encode("utf-8")


def calculate_response_symbols(challenge_indices: list) -> list:
    """
    Menghitung respon 12 simbol dari 4 simbol challenge menggunakan HMAC-SHA-256.
    Sesuai persis dengan sketch C++ mikrokontroler.
    """
    secret_key = _get_keybca_secret()
    digest = hmac.new(secret_key, bytes(challenge_indices), hashlib.sha256).digest()
    return [(digest[i // 4] >> (2 * (i % 4))) & 3 for i in range(RESP_LEN)]

def response_to_string(resp_indices: list) -> dict:
    """
    Formats the 12 response symbols into letter string and unicode symbols.
    """
    letters = "".join(LETTERS[c] for c in resp_indices)
    symbols = " ".join(NAMES[c] for c in resp_indices)
    return {
        "indices": resp_indices,
        "letters": letters,
        "symbols": symbols
    }

def derive_tactical_key(resp_indices: list, salt: bytes) -> bytes:
    """
    Derives 32-byte AES-GCM key from response symbols using PBKDF2-HMAC-SHA256.
    """
    # 200,000 iterations matches user Colab script
    return hashlib.pbkdf2_hmac("sha256", bytes(resp_indices), salt, 200_000, 32)

def encrypt_intel_package(pesan: str, challenge_indices: list) -> dict:
    """
    Mengenkripsi pesan intelijen dengan AES-GCM menggunakan kunci turunan respon simbol.
    Paket = base64(salt + nonce + ciphertext)
    """
    resp = calculate_response_symbols(challenge_indices)
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = derive_tactical_key(resp, salt)
    
    ct = AESGCM(key).encrypt(nonce, pesan.encode("utf-8"), None)
    paket = base64.b64encode(salt + nonce + ct).decode("utf-8")
    
    return {
        "paket": paket
    }

def decrypt_intel_package(paket_b64: str, response_input: str) -> dict:
    """
    Mendekripsi paket intelijen menggunakan response code dari token KeyBCA (ESP32/Wemos).
    Input bisa berupa huruf (TCXS...) atau simbol (△○✕□...).
    """
    try:
        # Parse response code into indices [0..3]
        resp_indices = [SYMBOL_MAP[c] for c in response_input.upper() if c in SYMBOL_MAP]
        
        if len(resp_indices) != RESP_LEN:
            return {
                "success": False,
                "message": f"Panjang response token harus {RESP_LEN} simbol/huruf (Diterima: {len(resp_indices)})."
            }
        
        raw = base64.b64decode(paket_b64.strip())
        if len(raw) < 28:
            return {"success": False, "message": "Paket terenkripsi rusak atau tidak lengkap."}
            
        salt, nonce, ct = raw[:16], raw[16:28], raw[28:]
        key = derive_tactical_key(resp_indices, salt)
        
        decrypted_bytes = AESGCM(key).decrypt(nonce, ct, None)
        plaintext = decrypted_bytes.decode("utf-8")
        
        return {
            "success": True,
            "plaintext": plaintext
        }
    except InvalidTag:
        return {
            "success": False,
            "message": "Kode token respon salah atau paket data rusak (AES-GCM Authentication Tag Mismatch)."
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Gagal mendekripsi pesan: {str(e)}"
        }
