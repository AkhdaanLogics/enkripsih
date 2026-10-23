"""
Enkripsih - Tactical Intelligence IoT System with KeyBCA-style Token & Face Verification.
Main FastAPI Application.
Supports Symbol-based KeyBCA Cryptography (Triangle, Circle, Cross, Square).
"""

import os
import json
import asyncio
import hmac
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional, Any
from urllib.parse import urlsplit
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .database import (
    init_db, log_event, save_message, get_messages,
    get_message_by_id, unlock_message, burn_message,
    get_commander_profile, save_auth_session, get_auth_session_expiry,
    delete_auth_session,
)
from .crypto_engine import (
    generate_tactical_challenge, calculate_response_symbols,
    response_to_string, encrypt_intel_package, decrypt_intel_package,
    SYMBOL_MAP, NAMES, LETTERS
)

SESSION_COOKIE = "enkripsih_session"
SESSION_TTL_SECONDS = 60 * 60
active_sessions: dict[str, float] = {}
login_attempts: dict[str, tuple[int, float]] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    password = os.environ.get("ENKRIPSIH_PASSWORD", "")
    if len(password) < 16:
        raise RuntimeError(
            "ENKRIPSIH_PASSWORD belum diatur atau kurang dari 16 karakter. "
            "Jalankan aplikasi lewat run.py untuk memasukkan password."
        )
    init_db(
        confirm_plaintext_migration=os.environ.get("ENKRIPSIH_CONFIRM_DB_MIGRATION") == "yes",
        passphrase=os.environ.get("ENKRIPSIH_DB_PASSPHRASE"),
    )
    yield

app = FastAPI(
    title="Enkripsih Tactical Hub",
    description="Military-grade Intelligence Communication & IoT KeyBCA Token Decoder System",
    version="1.0.0",
    lifespan=lifespan,
)


def _valid_session(token: Optional[str]) -> bool:
    if not token:
        return False
    if os.environ.get("DATABASE_URL"):
        expires_at = get_auth_session_expiry(token)
        if expires_at is None:
            return False
        if expires_at <= time.time():
            delete_auth_session(token)
            return False
        return True

    expires_at = active_sessions.get(token)
    if expires_at is None:
        return False
    if expires_at <= time.monotonic():
        active_sessions.pop(token, None)
        return False
    return True


@app.middleware("http")
async def protect_api(request: Request, call_next):
    public_auth_routes = {"/api/auth/login", "/api/auth/session"}
    if request.url.path.startswith("/api/") and request.url.path not in public_auth_routes:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin:
                parsed_origin = urlsplit(origin)
                if (
                    parsed_origin.scheme != request.url.scheme
                    or parsed_origin.netloc != request.headers.get("host")
                ):
                    return JSONResponse({"detail": "Cross-origin request ditolak."}, status_code=403)
        if not _valid_session(request.cookies.get(SESSION_COOKIE)):
            return JSONResponse(
                {"detail": "Login diperlukan."},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )

    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.session_tokens: dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, session_token: str):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.session_tokens[websocket] = session_token

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        self.session_tokens.pop(websocket, None)

    async def disconnect_session(self, session_token: str):
        for websocket in list(self.active_connections):
            if self.session_tokens.get(websocket) == session_token:
                try:
                    await websocket.close(code=1008, reason="Sesi login berakhir.")
                except (WebSocketDisconnect, RuntimeError):
                    pass
                finally:
                    self.disconnect(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

manager = ConnectionManager()

# --- Pydantic Schemas ---
class FaceAuthRequest(BaseModel):
    image_base64: str
    user_id: Optional[str] = "CMD-01"

class LoginRequest(BaseModel):
    password: str

class SendMessageRequest(BaseModel):
    sender_id: Optional[str] = "CMD-01"
    sender_name: Optional[str] = "Kolonel M. Haris"
    target_unit: str
    subject: str
    priority: str
    plaintext: str

class DecryptRequest(BaseModel):
    token: str

class KeyBCACalculateRequest(BaseModel):
    challenge: Any # can be string 'TCXS' or list [0,1,2,3]

class IoTSolveRequest(BaseModel):
    device_id: Optional[str] = "WEMOS-D1-MINI"
    challenge: str
    token: str

# --- WebSocket Endpoint ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    session_token = websocket.cookies.get(SESSION_COOKIE)
    origin = websocket.headers.get("origin")
    expected_scheme = "https" if websocket.url.scheme == "wss" else "http"
    parsed_origin = urlsplit(origin) if origin else None
    if (
        not _valid_session(session_token)
        or (
            parsed_origin is not None
            and (
                parsed_origin.scheme != expected_scheme
                or parsed_origin.netloc != websocket.url.netloc
            )
        )
    ):
        await websocket.close(code=1008, reason="Login diperlukan.")
        return
    await manager.connect(websocket, session_token)
    try:
        while True:
            data = await websocket.receive_text()
            if not _valid_session(session_token):
                await websocket.close(code=1008, reason="Sesi login berakhir.")
                manager.disconnect(websocket)
                return
            try:
                payload = json.loads(data)
                if payload.get("type") == "PING":
                    await websocket.send_json({"type": "PONG", "time": datetime.now().isoformat()})
            except Exception:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# --- Authentication & Face Biometrics ---
@app.post("/api/auth/login")
def login(req: LoginRequest, request: Request, response: Response):
    client_id = request.client.host if request.client else "unknown"
    attempts, locked_until = login_attempts.get(client_id, (0, 0.0))
    now = time.monotonic()
    if locked_until > now:
        raise HTTPException(status_code=429, detail="Terlalu banyak percobaan. Coba lagi beberapa menit.")

    configured_password = os.environ.get("ENKRIPSIH_PASSWORD", "")
    if not hmac.compare_digest(req.password, configured_password):
        attempts += 1
        lock_until = now + 300 if attempts >= 5 else 0.0
        login_attempts[client_id] = (0 if lock_until else attempts, lock_until)
        log_event("AUTH", "DENIED", "Percobaan login gagal.")
        raise HTTPException(status_code=401, detail="Password tidak benar.")

    login_attempts.pop(client_id, None)
    token = secrets.token_urlsafe(32)
    expires_at = time.time() + SESSION_TTL_SECONDS
    if os.environ.get("DATABASE_URL"):
        save_auth_session(token, expires_at)
    else:
        active_sessions[token] = now + SESSION_TTL_SECONDS
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    log_event("AUTH", "SUCCESS", "Login berhasil.")
    return {"success": True, "expires_in": SESSION_TTL_SECONDS}


@app.get("/api/auth/session")
def get_session(request: Request):
    return {"authenticated": _valid_session(request.cookies.get(SESSION_COOKIE))}


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        active_sessions.pop(token, None)
        if os.environ.get("DATABASE_URL"):
            delete_auth_session(token)
        await manager.disconnect_session(token)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
    return {"success": True}


@app.get("/api/auth/commander-status")
def get_commander_status():
    profile = get_commander_profile("CMD-01")
    return {
        "status": "OK",
        "commander": {
            "id": profile["id"],
            "name": profile["name"],
            "rank": profile["rank"],
            "role": profile["role"],
            "face_enrolled": bool(profile["face_enrolled"]),
        } if profile else None,
    }

@app.post("/api/auth/verify-face")
def verify_face_endpoint(req: FaceAuthRequest):
    from .face_auth import verify_commander_face

    return verify_commander_face(req.image_base64, req.user_id or "CMD-01")

@app.post("/api/auth/register-face")
def register_face_endpoint(req: FaceAuthRequest):
    from .face_auth import register_commander_face

    return register_commander_face(req.image_base64, req.user_id or "CMD-01")

# --- Messages (Transmission & Decryption) ---
@app.post("/api/messages/send")
async def send_message_endpoint(req: SendMessageRequest):
    if not req.plaintext.strip():
        raise HTTPException(status_code=400, detail="Isi pesan intelijen tidak boleh kosong.")
    
    msg_id = f"MSG-{datetime.now().strftime('%m%d')}-{os.urandom(2).hex().upper()}"
    
    # 1. Generate 4-symbol challenge (e.g. TCXS / △ ○ ✕ □)
    chal_data = generate_tactical_challenge()
    
    # 2. Encrypt intel payload with PBKDF2 + AES-GCM
    enc_data = encrypt_intel_package(req.plaintext, chal_data["indices"])
    
    msg_record = {
        "id": msg_id,
        "sender_id": req.sender_id or "CMD-01",
        "sender_name": req.sender_name or "Kolonel M. Haris",
        "target_unit": req.target_unit,
        "subject": req.subject,
        "priority": req.priority,
        "challenge_letters": chal_data["letters"],
        "challenge_symbols": chal_data["symbols"],
        "paket": enc_data["paket"],
        "status": "LOCKED",
        "created_at": datetime.now().isoformat()
    }
    
    save_message(msg_record)
    log_event("TRANSMIT", "SUCCESS", f"Pesan [{msg_id}] ditransmisikan. Challenge: {chal_data['symbols']} ({chal_data['letters']})")
    
    # Broadcast to connected clients (KeyBCA token and Receiver)
    await manager.broadcast({
        "type": "NEW_MESSAGE",
        "message": {
            "id": msg_id,
            "target_unit": req.target_unit,
            "subject": req.subject,
            "priority": req.priority,
            "challenge_letters": chal_data["letters"],
            "challenge_symbols": chal_data["symbols"],
            "status": "LOCKED",
            "created_at": msg_record["created_at"]
        }
    })
    
    return {
        "success": True,
        "message_id": msg_id,
        "challenge_letters": chal_data["letters"],
        "challenge_symbols": chal_data["symbols"],
        "target_unit": req.target_unit,
        "status": "LOCKED"
    }

@app.get("/api/messages")
def get_all_messages():
    return {"messages": [_message_summary(msg) for msg in get_messages()]}


def _message_summary(msg: dict) -> dict:
    summary = {
        "id": msg["id"],
        "sender_id": msg["sender_id"],
        "sender_name": msg["sender_name"],
        "target_unit": msg["target_unit"],
        "subject": msg["subject"],
        "priority": msg["priority"],
        "challenge_letters": msg["challenge_letters"],
        "challenge_symbols": msg["challenge_symbols"],
        "status": msg["status"],
        "created_at": msg["created_at"],
        "decrypted_at": msg["decrypted_at"],
        "encrypted": bool(msg["paket"]) and msg["status"] != "BURNED",
    }
    if msg["status"] == "UNLOCKED":
        summary["plaintext"] = msg["plaintext"]
    return summary

@app.get("/api/messages/{msg_id}")
def get_message_detail(msg_id: str):
    msg = get_message_by_id(msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Pesan tidak ditemukan.")
    return _message_summary(msg)

@app.post("/api/messages/{msg_id}/decrypt")
async def decrypt_message_endpoint(msg_id: str, req: DecryptRequest):
    msg = get_message_by_id(msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Pesan tidak ditemukan.")
    
    if msg["status"] == "BURNED":
        raise HTTPException(status_code=400, detail="Pesan telah dihancurkan (Self-Destructed).")
    
    # Decrypt package with provided token
    dec_result = decrypt_intel_package(msg["paket"], req.token)
    
    if not dec_result["success"]:
        log_event("DECRYPT", "DENIED", f"Gagal mendekripsi [{msg_id}]. Token tidak valid.")
        return dec_result
    
    plaintext = dec_result["plaintext"]
    unlock_message(msg_id, plaintext)
    log_event("DECRYPT", "SUCCESS", f"Pesan [{msg_id}] berhasil didekripsi dengan token KeyBCA!")
    
    await manager.broadcast({
        "type": "MESSAGE_UNLOCKED",
        "message_id": msg_id,
        "decrypted_at": datetime.now().isoformat()
    })
    
    return {
        "success": True,
        "message": "Pesan intelijen berhasil diverifikasi & didekripsi!",
        "plaintext": plaintext,
        "status": "UNLOCKED"
    }

@app.post("/api/messages/{msg_id}/burn")
async def burn_message_endpoint(msg_id: str):
    msg = get_message_by_id(msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Pesan tidak ditemukan.")
    
    burn_message(msg_id)
    log_event("DECRYPT", "WARNING", f"Pesan [{msg_id}] dihancurkan secara permanen.")
    
    await manager.broadcast({
        "type": "MESSAGE_BURNED",
        "message_id": msg_id
    })
    
    return {"success": True, "message": "Pesan berhasil dihancurkan secara permanen."}

# --- KeyBCA Token IoT Endpoints ---
@app.post("/api/iot/keybca/calculate")
def calculate_token_endpoint(req: KeyBCACalculateRequest):
    """
    Computes KeyBCA 12-symbol response from 4-symbol challenge.
    Accepts letters (e.g. 'TCXS') or symbol indices.
    """
    input_str = str(req.challenge).strip()
    indices = [SYMBOL_MAP[c] for c in input_str.upper() if c in SYMBOL_MAP]
    
    # Pad to 4 if less
    while len(indices) < 4:
        indices.append(0)
    indices = indices[:4]
    
    resp_indices = calculate_response_symbols(indices)
    result = response_to_string(resp_indices)
    
    log_event("KEYBCA", "SUCCESS", f"KeyBCA menghitung respons untuk challenge '{input_str}'.")
    return {
        "success": True,
        "challenge_indices": indices,
        "challenge_letters": "".join(LETTERS[c] for c in indices),
        "challenge_symbols": " ".join(NAMES[c] for c in indices),
        "response_indices": result["indices"],
        "response_letters": result["letters"],
        "response_symbols": result["symbols"]
    }

@app.post("/api/iot/keybca/solve")
async def iot_solve_endpoint(req: IoTSolveRequest):
    """
    Called by Wemos D1 Mini / ESP32 or serial bridge to broadcast solved token.
    """
    log_event("KEYBCA", "SUCCESS", f"IoT [{req.device_id}] mengirim token untuk challenge {req.challenge}.")
    
    await manager.broadcast({
        "type": "IOT_TOKEN_SOLVED",
        "device_id": req.device_id,
        "challenge": req.challenge,
        "token": req.token,
        "timestamp": datetime.now().isoformat()
    })
    
    return {
        "success": True,
        "device_id": req.device_id,
        "challenge": req.challenge,
        "token": req.token
    }

# --- Static Frontend Files ---
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    def serve_index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
