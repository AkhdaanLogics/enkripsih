"""FastAPI application for ENKRIPSIH encrypted message delivery."""

import base64
import binascii
import os
import json
import asyncio
import hmac
import hashlib
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional, Any
from urllib.parse import urlsplit
import re
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .database import (
    init_db, log_event, save_message, get_messages,
    get_message_by_id, burn_message, register_recipient_key,
    get_recipient_keys, get_recipient_key,
    get_commander_profile, save_auth_session,
    get_auth_session, delete_auth_session, delete_auth_sessions_for_principal,
    update_auth_session_password_change, change_receiver_password,
    get_receiver_account, provision_receiver_account,
)
from .crypto_engine import (
    calculate_response_symbols, response_to_string,
    SYMBOL_MAP, NAMES, LETTERS
)

SESSION_COOKIE = "enkripsih_session"
SESSION_TTL_SECONDS = 60 * 60
active_sessions: dict[str, dict] = {}
login_attempts: dict[str, tuple[int, float]] = {}
PASSWORD_HASH_ITERATIONS = 600_000


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
    title="ENKRIPSIH",
    description="Encrypted message delivery for registered members.",
    version="2.0.0",
    lifespan=lifespan,
)


def _valid_session(token: Optional[str]) -> bool:
    return _session_principal(token) is not None


def _session_principal(token: Optional[str]) -> dict | None:
    if not token:
        return None
    if os.environ.get("DATABASE_URL"):
        session = get_auth_session(token)
        if session is None:
            return None
        if float(session["expires_at"]) <= time.time():
            delete_auth_session(token)
            return None
        return {
            "principal_id": session["principal_id"],
            "role": session["role"],
            "must_change_password": bool(session["must_change_password"]),
        }

    session = active_sessions.get(token)
    if session is None:
        return None
    if session["expires_at"] <= time.monotonic():
        active_sessions.pop(token, None)
        return None
    return {
        "principal_id": session["principal_id"],
        "role": session["role"],
        "must_change_password": session["must_change_password"],
    }


def _store_session(token: str, expires_at: float, principal: dict) -> None:
    if os.environ.get("DATABASE_URL"):
        save_auth_session(
            token,
            expires_at,
            principal["principal_id"],
            principal["role"],
            principal["must_change_password"],
        )
    else:
        active_sessions[token] = {
            **principal,
            "expires_at": time.monotonic() + SESSION_TTL_SECONDS,
        }


def _receiver_allowed_path(path: str, method: str) -> bool:
    if path in {"/api/auth/change-password", "/api/auth/logout"}:
        return method == "POST"
    if path in {"/api/messages", "/api/recipients"}:
        return method == "GET"
    if re.fullmatch(r"/api/recipients/[^/]+/verify", path):
        return method == "POST"
    if re.fullmatch(r"/api/messages/[^/]+(?:/ciphertext)?", path):
        return method == "GET"
    return False


@app.middleware("http")
async def protect_api(request: Request, call_next):
    public_auth_routes = {
        "/api/auth/login", "/api/auth/receiver-login", "/api/auth/session",
    }
    if request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        if origin and request.method not in {"GET", "HEAD", "OPTIONS"}:
            parsed_origin = urlsplit(origin)
            if (
                parsed_origin.scheme != request.url.scheme
                or parsed_origin.netloc != request.headers.get("host")
            ):
                return JSONResponse({"detail": "Cross-origin request ditolak."}, status_code=403)
    if request.url.path.startswith("/api/") and request.url.path not in public_auth_routes:
        principal = _session_principal(request.cookies.get(SESSION_COOKIE))
        if principal is None:
            return JSONResponse(
                {"detail": "Login diperlukan."},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )
        request.state.principal = principal
        if principal["role"] == "RECEIVER":
            if not _receiver_allowed_path(request.url.path, request.method):
                return JSONResponse(
                    {"detail": "Akses hanya tersedia untuk akun komandan."},
                    status_code=403,
                    headers={"Cache-Control": "no-store"},
                )
            if (
                principal["must_change_password"]
                and request.url.path not in {
                    "/api/auth/change-password", "/api/auth/logout",
                }
            ):
                return JSONResponse(
                    {"detail": "Ganti password sementara sebelum melanjutkan."},
                    status_code=403,
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
        self.session_principals: dict[WebSocket, dict] = {}

    async def connect(self, websocket: WebSocket, session_token: str, principal: dict):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.session_tokens[websocket] = session_token
        self.session_principals[websocket] = principal

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        self.session_tokens.pop(websocket, None)
        self.session_principals.pop(websocket, None)

    async def disconnect_principal(self, principal_id: str):
        for websocket, principal in list(self.session_principals.items()):
            if principal.get("principal_id") != principal_id:
                continue
            try:
                await websocket.close(code=1008, reason="Akun receiver direset.")
            except (WebSocketDisconnect, RuntimeError, OSError):
                pass
            finally:
                self.disconnect(websocket)

    async def disconnect_session(self, session_token: str):
        for websocket in list(self.active_connections):
            if self.session_tokens.get(websocket) == session_token:
                try:
                    await websocket.close(code=1008, reason="Sesi login berakhir.")
                except (WebSocketDisconnect, RuntimeError, OSError):
                    pass
                finally:
                    self.disconnect(websocket)

    async def broadcast(self, message: dict, recipient_id: str | None = None):
        for connection in list(self.active_connections):
            principal = self.session_principals.get(connection, {})
            if principal.get("role") == "RECEIVER":
                if principal.get("principal_id") != recipient_id:
                    continue
            try:
                await connection.send_json(message)
            except (WebSocketDisconnect, RuntimeError, OSError):
                self.disconnect(connection)

manager = ConnectionManager()

# --- Pydantic Schemas ---
class FaceAuthRequest(BaseModel):
    image_base64: str
    user_id: Optional[str] = "CMD-01"

class LoginRequest(BaseModel):
    password: str

class ReceiverLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(max_length=128)

class ChangePasswordRequest(BaseModel):
    new_password: str = Field(max_length=128)

class SendMessageRequest(BaseModel):
    sender_id: Optional[str] = "CMD-01"
    sender_name: Optional[str] = "Kolonel M. Haris"
    recipient_id: str
    paket: str

class RegisterRecipientRequest(BaseModel):
    name: str
    salt: str
    verifier: str

class VerifyRecipientKeyRequest(BaseModel):
    verifier: str

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
    principal = _session_principal(session_token)
    origin = websocket.headers.get("origin")
    expected_scheme = "https" if websocket.url.scheme == "wss" else "http"
    parsed_origin = urlsplit(origin) if origin else None
    if (
        principal is None
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
    await manager.connect(websocket, session_token, principal)
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
    principal = {
        "principal_id": "CMD-01",
        "role": "COMMANDER",
        "must_change_password": False,
    }
    _store_session(token, expires_at, principal)
    _set_session_cookie(response, request, token)
    login_attempts.pop(client_id, None)
    log_event("AUTH", "SUCCESS", "Login komandan berhasil.")
    return {"success": True, "expires_in": SESSION_TTL_SECONDS, **principal}


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )


def _password_hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS
    ).hex()


def _new_receiver_password() -> str:
    return secrets.token_urlsafe(18)


def _issue_receiver_account(recipient_id: str, username: str) -> str:
    temporary_password = _new_receiver_password()
    salt = secrets.token_bytes(16)
    provision_receiver_account(
        recipient_id,
        username,
        salt.hex(),
        _password_hash(temporary_password, salt),
    )
    delete_auth_sessions_for_principal(recipient_id)
    for token, session in list(active_sessions.items()):
        if session["principal_id"] == recipient_id:
            active_sessions.pop(token, None)
    return temporary_password


@app.post("/api/auth/receiver-login")
def receiver_login(req: ReceiverLoginRequest, request: Request, response: Response):
    client_id = request.client.host if request.client else "unknown"
    attempts, locked_until = login_attempts.get(client_id, (0, 0.0))
    now = time.monotonic()
    if locked_until > now:
        raise HTTPException(status_code=429, detail="Terlalu banyak percobaan. Coba lagi beberapa menit.")

    account = get_receiver_account(req.username.strip())
    salt = bytes.fromhex(account["password_salt"]) if account else bytes(16)
    expected_hash = account["password_hash"] if account else "00" * 32
    actual_hash = _password_hash(req.password, salt)
    password_valid = hmac.compare_digest(actual_hash, expected_hash)
    if account is None or not password_valid:
        attempts += 1
        lock_until = now + 300 if attempts >= 5 else 0.0
        login_attempts[client_id] = (0 if lock_until else attempts, lock_until)
        log_event("AUTH", "DENIED", "Percobaan login receiver gagal.")
        raise HTTPException(status_code=401, detail="Nama pengguna atau password tidak benar.")

    login_attempts.pop(client_id, None)
    token = secrets.token_urlsafe(32)
    expires_at = time.time() + SESSION_TTL_SECONDS
    principal = {
        "principal_id": account["recipient_id"],
        "role": "RECEIVER",
        "must_change_password": bool(account["must_change_password"]),
    }
    _store_session(token, expires_at, principal)
    _set_session_cookie(response, request, token)
    log_event("AUTH", "SUCCESS", f"Login receiver [{account['recipient_id']}] berhasil.")
    return {"success": True, "expires_in": SESSION_TTL_SECONDS, **principal}


@app.post("/api/auth/change-password")
def change_password(req: ChangePasswordRequest, request: Request):
    principal = getattr(request.state, "principal", None)
    if not principal or principal["role"] != "RECEIVER":
        raise HTTPException(status_code=403, detail="Fitur ini hanya untuk akun receiver.")
    if len(req.new_password) < 16:
        raise HTTPException(status_code=400, detail="Password baru minimal 16 karakter.")
    salt = secrets.token_bytes(16)
    change_receiver_password(
        principal["principal_id"],
        salt.hex(),
        _password_hash(req.new_password, salt),
    )
    token = request.cookies.get(SESSION_COOKIE)
    if token and os.environ.get("DATABASE_URL"):
        update_auth_session_password_change(token, False)
    elif token in active_sessions:
        active_sessions[token]["must_change_password"] = False
    principal["must_change_password"] = False
    log_event("AUTH", "SUCCESS", f"Password receiver [{principal['principal_id']}] diperbarui.")
    return {"success": True}


@app.get("/api/auth/session")
def get_session(request: Request):
    principal = _session_principal(request.cookies.get(SESSION_COOKIE))
    return {"authenticated": principal is not None, **(principal or {})}


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
@app.get("/api/recipients")
def list_recipients(request: Request = None):
    principal = getattr(request.state, "principal", None) if request else None
    if principal and principal["role"] == "RECEIVER":
        recipient = get_recipient_key(principal["principal_id"])
        if not recipient:
            return {"recipients": []}
        return {
            "recipients": [{
                "id": recipient["id"],
                "name": recipient["name"],
                "salt": recipient["salt"],
            }]
        }
    return {"recipients": get_recipient_keys()}


@app.post("/api/recipients/register")
def register_recipient(req: RegisterRecipientRequest):
    name = req.name.strip()
    if not 2 <= len(name) <= 80:
        raise HTTPException(status_code=400, detail="Nama anggota harus 2 sampai 80 karakter.")
    if not re.fullmatch(r"[0-9a-fA-F]{32}", req.salt):
        raise HTTPException(status_code=400, detail="Salt kunci tidak valid.")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", req.verifier):
        raise HTTPException(status_code=400, detail="Verifier kunci tidak valid.")

    recipient_id = secrets.token_urlsafe(12)
    username = name.lower()
    if get_receiver_account(username):
        raise HTTPException(
            status_code=409,
            detail="Nama pengguna sudah dipakai. Pilih nama anggota yang berbeda.",
        )
    temporary_password = _new_receiver_password()
    password_salt = secrets.token_bytes(16)
    if not register_recipient_key(
        recipient_id, name, req.salt.lower(), req.verifier.lower(),
        username, password_salt.hex(),
        _password_hash(temporary_password, password_salt),
    ):
        raise HTTPException(
            status_code=409,
            detail="Nama anggota sudah terdaftar. Gunakan nama berbeda atau hubungi admin untuk rotasi kunci.",
        )
    log_event("KEY", "SUCCESS", f"Kunci verifier anggota [{recipient_id}] didaftarkan.")
    return {
        "success": True,
        "recipient_id": recipient_id,
        "name": name,
        "username": username,
        "temporary_password": temporary_password,
    }


@app.post("/api/recipients/{recipient_id}/account")
async def reset_receiver_account(recipient_id: str):
    recipient = get_recipient_key(recipient_id)
    if not recipient:
        raise HTTPException(status_code=404, detail="Anggota tidak ditemukan.")
    username = recipient["name"].lower()
    temporary_password = _issue_receiver_account(recipient_id, username)
    await manager.disconnect_principal(recipient_id)
    log_event("AUTH", "WARNING", f"Akun receiver [{recipient_id}] dibuat atau direset.")
    return {
        "success": True,
        "recipient_id": recipient_id,
        "username": username,
        "temporary_password": temporary_password,
    }


@app.post("/api/recipients/{recipient_id}/verify")
def verify_recipient_key(
    recipient_id: str,
    req: VerifyRecipientKeyRequest,
    request: Request = None,
):
    if not re.fullmatch(r"[0-9a-fA-F]{64}", req.verifier):
        raise HTTPException(status_code=400, detail="Verifier kunci tidak valid.")
    recipient = get_recipient_key(recipient_id)
    principal = getattr(request.state, "principal", None) if request else None
    if (
        principal and principal["role"] == "RECEIVER"
        and principal["principal_id"] != recipient_id
    ):
        raise HTTPException(status_code=404, detail="Anggota tidak ditemukan.")
    is_valid = bool(
        recipient
        and hmac.compare_digest(recipient["verifier"], req.verifier.lower())
    )
    return {"valid": is_valid}


def _require_receiver_message_access(msg: dict, request: Request = None) -> None:
    principal = getattr(request.state, "principal", None) if request else None
    if (
        principal and principal["role"] == "RECEIVER"
        and principal["principal_id"] != msg["recipient_id"]
    ):
        raise HTTPException(status_code=404, detail="Pesan tidak ditemukan.")


@app.post("/api/messages/send")
async def send_message_endpoint(req: SendMessageRequest):
    recipient = get_recipient_key(req.recipient_id)
    if not recipient:
        raise HTTPException(status_code=404, detail="Anggota belum terdaftar.")
    if len(req.paket) > 1_500_000:
        raise HTTPException(status_code=413, detail="Paket pesan terlalu besar.")
    try:
        envelope = json.loads(req.paket)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail="Paket terenkripsi tidak valid.") from error
    if (
        not isinstance(envelope, dict)
        or type(envelope.get("v")) is not int
        or envelope.get("v") not in {1, 2, 3, 4, 5}
        or not all(
            isinstance(envelope.get(field), str)
            for field in ("salt", "iv", "ciphertext")
        )
    ):
        raise HTTPException(status_code=400, detail="Format paket terenkripsi tidak valid.")
    if envelope["v"] in {2, 3, 4, 5} and (
        not isinstance(envelope.get("challenge"), str)
        or not re.fullmatch(r"[TCXS]{4}", envelope["challenge"])
    ):
        raise HTTPException(status_code=400, detail="Challenge passkey tidak valid.")
    if not all(
        re.fullmatch(r"[A-Za-z0-9_-]+", envelope[field])
        for field in ("salt", "iv", "ciphertext")
    ):
        raise HTTPException(status_code=400, detail="Format paket terenkripsi tidak valid.")
    try:
        salt = base64.urlsafe_b64decode(envelope["salt"] + "=" * (-len(envelope["salt"]) % 4))
        iv = base64.urlsafe_b64decode(envelope["iv"] + "=" * (-len(envelope["iv"]) % 4))
        ciphertext = base64.urlsafe_b64decode(
            envelope["ciphertext"] + "=" * (-len(envelope["ciphertext"]) % 4)
        )
    except (ValueError, binascii.Error) as error:
        raise HTTPException(
            status_code=400,
            detail="Format paket terenkripsi tidak valid.",
        ) from error
    if len(salt) != 16 or len(iv) != 12 or len(ciphertext) < 16:
        raise HTTPException(status_code=400, detail="Paket terenkripsi tidak lengkap.")

    msg_id = f"MSG-{datetime.now().strftime('%m%d')}-{os.urandom(2).hex().upper()}"
    msg_record = {
        "id": msg_id,
        "sender_id": req.sender_id or "CMD-01",
        "sender_name": req.sender_name or "Kolonel M. Haris",
        "target_unit": recipient["name"],
        "recipient_id": recipient["id"],
        "paket": req.paket,
        "status": "LOCKED",
        "created_at": datetime.now().isoformat()
    }
    
    save_message(msg_record)
    log_event("TRANSMIT", "SUCCESS", f"Ciphertext pesan [{msg_id}] ditransmisikan.")
    
    await manager.broadcast({
        "type": "NEW_MESSAGE",
        "message": {
            "id": msg_id,
            "target_unit": recipient["name"],
            "status": "LOCKED",
            "created_at": msg_record["created_at"]
        }
    }, recipient_id=recipient["id"])
    
    return {
        "success": True,
        "message_id": msg_id,
        "target_unit": recipient["name"],
        "status": "LOCKED"
    }

@app.get("/api/messages")
def get_all_messages(request: Request = None):
    principal = getattr(request.state, "principal", None) if request else None
    messages = get_messages()
    if principal and principal["role"] == "RECEIVER":
        messages = [
            message for message in messages
            if message["recipient_id"] == principal["principal_id"]
        ]
    return {"messages": [_message_summary(msg) for msg in messages]}


def _message_summary(msg: dict) -> dict:
    passkey_challenge = None
    encryption_version = None
    if msg["status"] != "BURNED" and msg["paket"]:
        try:
            envelope = json.loads(msg["paket"])
            version = envelope.get("v") if isinstance(envelope, dict) else None
            if type(version) is int and version in {1, 2, 3, 4, 5}:
                encryption_version = version
            challenge = envelope.get("challenge") if isinstance(envelope, dict) else None
            if isinstance(challenge, str) and re.fullmatch(r"[TCXS]{4}", challenge):
                passkey_challenge = challenge
        except json.JSONDecodeError:
            pass
    summary = {
        "id": msg["id"],
        "sender_id": msg["sender_id"],
        "sender_name": msg["sender_name"],
        "target_unit": msg["target_unit"],
        "recipient_id": msg["recipient_id"],
        "status": msg["status"],
        "created_at": msg["created_at"],
        "encrypted": bool(msg["paket"]) and msg["status"] != "BURNED",
        "passkey_challenge": passkey_challenge,
        "encryption_version": encryption_version,
    }
    return summary

@app.get("/api/messages/{msg_id}")
def get_message_detail(msg_id: str, request: Request = None):
    msg = get_message_by_id(msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Pesan tidak ditemukan.")
    _require_receiver_message_access(msg, request)
    return _message_summary(msg)

@app.get("/api/messages/{msg_id}/ciphertext")
def get_message_ciphertext(msg_id: str, request: Request = None):
    msg = get_message_by_id(msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Pesan tidak ditemukan.")
    _require_receiver_message_access(msg, request)
    if msg["status"] == "BURNED":
        raise HTTPException(status_code=410, detail="Pesan telah dihancurkan.")
    if msg["status"] == "LEGACY":
        raise HTTPException(
            status_code=410,
            detail="Pesan ini memakai format lama dan tidak dapat dibuka dengan secret key anggota.",
        )
    return {
        "message_id": msg["id"],
        "recipient_id": msg["recipient_id"],
        "paket": msg["paket"],
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
    }, recipient_id=msg["recipient_id"])
    
    return {"success": True, "message": "Pesan berhasil dihancurkan secara permanen."}

# --- Lexa Token IoT Endpoints (legacy /keybca route retained) ---
@app.post("/api/iot/keybca/calculate")
def calculate_token_endpoint(req: KeyBCACalculateRequest):
    """
    Computes a 12-symbol Lexa response from a 4-symbol challenge.
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
    
    log_event("KEYBCA", "SUCCESS", f"Lexa menghitung respons untuk challenge '{input_str}'.")
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
