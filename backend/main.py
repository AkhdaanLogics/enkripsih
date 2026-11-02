"""FastAPI application for ENKRIPSIH encrypted message delivery."""

import base64
import binascii
import os
import json
import asyncio
import hmac
import hashlib
import secrets
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional, Any
from urllib.parse import urlsplit
import re
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .database import (
    init_db, log_event, save_message, get_messages,
    get_message_by_id, burn_message, register_recipient_key,
    get_recipient_keys, get_recipient_key,
    delete_recipient, reissue_recipient_key, get_messages_count_for_recipient,
    get_commander_profile, save_auth_session,
    get_auth_session, delete_auth_session, delete_auth_sessions_for_principal,
    update_auth_session_password_change, update_auth_session_expiry,
    change_receiver_password,
    get_receiver_account, provision_receiver_account,
    get_login_lockout, record_failed_login, clear_login_lockout,
    mark_message_decrypted, mark_face_verified,
)
from .crypto_engine import (
    calculate_response_symbols, response_to_string,
    SYMBOL_MAP, NAMES, LETTERS
)

SESSION_COOKIE = "enkripsih_session"
SESSION_IDLE_TIMEOUT_SECONDS = int(
    os.environ.get("ENKRIPSIH_SESSION_IDLE_TIMEOUT_SECONDS", "300")
)
if not 1 <= SESSION_IDLE_TIMEOUT_SECONDS <= 86_400:
    raise RuntimeError(
        "ENKRIPSIH_SESSION_IDLE_TIMEOUT_SECONDS harus antara 1 dan 86400."
    )
SESSION_COOKIE_MAX_AGE = 7200
active_sessions: dict[str, dict] = {}
PASSWORD_HASH_ITERATIONS = 600_000
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 300


@asynccontextmanager
async def lifespan(_: FastAPI):
    password = os.environ.get("ENKRIPSIH_PASSWORD", "")
    if len(password) < 16:
        raise RuntimeError(
            "ENKRIPSIH_PASSWORD belum diatur atau kurang dari 16 karakter. "
            "Jalankan aplikasi lewat run.py untuk memasukkan password."
        )
    keybca_secret = os.environ.get("ENKRIPSIH_KEYBCA_SECRET", "")
    if len(keybca_secret) < 16:
        raise RuntimeError(
            "ENKRIPSIH_KEYBCA_SECRET belum diatur atau kurang dari 16 karakter. "
            "Jalankan aplikasi lewat run.py untuk memasukkan secret."
        )
    init_db(
        confirm_plaintext_migration=os.environ.get("ENKRIPSIH_CONFIRM_DB_MIGRATION") == "yes",
        passphrase=os.environ.get("ENKRIPSIH_DB_PASSPHRASE"),
    )
    yield
docs_enabled = os.environ.get("ENKRIPSIH_ENABLE_DOCS", "").lower() in {"1", "true", "yes"}
app = FastAPI(
    title="ENKRIPSIH",
    description="Encrypted message delivery for registered members.",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if docs_enabled else None,
    redoc_url="/redoc" if docs_enabled else None,
    openapi_url="/openapi.json" if docs_enabled else None,
)


@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    import logging
    _logger = logging.getLogger("enkripsih.errors")
    _logger.error("[500] %s %s: %r", request.method, request.url.path, exc, exc_info=False)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Periksa log server untuk detail."},
        headers={"Cache-Control": "no-store"},
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
            "face_verified": bool(session["face_verified"]),
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
        "face_verified": session.get("face_verified", False),
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
            "expires_at": time.monotonic() + SESSION_IDLE_TIMEOUT_SECONDS,
        }


def _touch_session(token: str) -> None:
    if os.environ.get("DATABASE_URL"):
        update_auth_session_expiry(
            token,
            time.time() + SESSION_IDLE_TIMEOUT_SECONDS,
        )
        return

    session = active_sessions.get(token)
    if session is not None:
        session["expires_at"] = time.monotonic() + SESSION_IDLE_TIMEOUT_SECONDS


def _receiver_allowed_path(path: str, method: str) -> bool:
    if path in {"/api/auth/change-password", "/api/auth/logout", "/api/auth/activity"}:
        return method == "POST"
    if path in {"/api/messages", "/api/recipients"}:
        return method == "GET"
    if re.fullmatch(r"/api/recipients/[^/]+/verify", path):
        return method == "POST"
    if re.fullmatch(r"/api/messages/[^/]+(?:/ciphertext)?", path) and path != "/api/messages/decrypt":
        return method == "GET"
    if re.fullmatch(r"/api/messages/[^/]+/unlock", path):
        return method == "POST"
    if re.fullmatch(r"/api/messages/[^/]+/burn", path):
        return method == "POST"
    if path == "/api/messages/decrypt":
        return method == "POST"
    return False


@app.middleware("http")
async def protect_api(request: Request, call_next):
    public_auth_routes = {
        "/api/auth/login", "/api/auth/receiver-login", "/api/auth/session",
        "/api/health",
    }
    refreshed_session_token = None
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
                and not re.search(
                    r"^/api/messages/[^/]+/(?:unlock|burn)$",
                    request.url.path,
                )
                and request.url.path not in {
                    "/api/auth/change-password", "/api/auth/logout",
                    "/api/auth/activity", "/api/messages/decrypt",
                }
            ):
                return JSONResponse(
                    {"detail": "Ganti password sementara sebelum melanjutkan."},
                    status_code=403,
                    headers={"Cache-Control": "no-store"},
                )

        refreshed_session_token = request.cookies[SESSION_COOKIE]
        _touch_session(refreshed_session_token)
    elif request.url.path == "/api/auth/session":
        session_token = request.cookies.get(SESSION_COOKIE)
        if session_token and _session_principal(session_token) is not None:
            refreshed_session_token = session_token
            _touch_session(session_token)

    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    # Security response headers (applies to all responses)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "font-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    if refreshed_session_token:
        response.set_cookie(
            SESSION_COOKIE,
            refreshed_session_token,
            max_age=SESSION_COOKIE_MAX_AGE,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            path="/",
        )
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
    recipient_id: str
    paket: str

class RegisterRecipientRequest(BaseModel):
    name: str
    salt: str
    verifier: str
    secret_key: Optional[str] = None  # Plain secret key — if provided, auto-written to .env

class VerifyRecipientKeyRequest(BaseModel):
    verifier: str

class KeyBCACalculateRequest(BaseModel):
    challenge: Any # can be string 'TCXS' or list [0,1,2,3]
    hmac_signature: Optional[str] = None  # HMAC-SHA256 of challenge using ENKRIPSIH_IOT_TOKEN

class IoTSolveRequest(BaseModel):
    device_id: Optional[str] = "WEMOS-D1-MINI"
    challenge: str
    token: str
    hmac_signature: Optional[str] = None  # HMAC-SHA256 of f"{device_id}:{challenge}:{token}"

# --- WebSocket Endpoint ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    session_token = websocket.cookies.get(SESSION_COOKIE)
    principal = _session_principal(session_token)
    origin = websocket.headers.get("origin")
    if not origin:
        await websocket.close(code=1008, reason="Origin header wajib ada.")
        return
    expected_scheme = "https" if websocket.url.scheme == "wss" else "http"
    parsed_origin = urlsplit(origin)
    if (
        principal is None
        or parsed_origin.scheme != expected_scheme
        or parsed_origin.netloc != websocket.url.netloc
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

# --- Diagnostics ---
@app.get("/api/health")
def api_health(request: Request):
    """Liveness + configuration probe. No auth.

    Surfaces whether the request landed on a server where the required
    env vars are present and where the session store (in-memory or DB)
    is reachable. Useful for Vercel: a 200 here with ``session_store:
    "in_memory"`` means login works but is wiped on cold start, which
    is the classic Vercel 401-after-login symptom.
    """
    import traceback
    db_url = os.environ.get("DATABASE_URL")
    has_password = len(os.environ.get("ENKRIPSIH_PASSWORD", "")) >= 16
    has_keybca = len(os.environ.get("ENKRIPSIH_KEYBCA_SECRET", "")) >= 16
    # Count agent keys visible to runtime (os.environ or .env file)
    agent_key_count = 0
    try:
        from .env_agents import list_agent_env_keys
        agent_key_count = len(list_agent_env_keys())
    except Exception:
        pass
    payload: dict = {
        "ok": bool(db_url) or has_password,
        "session_store": "database" if db_url else "in_memory",
        "database_configured": bool(db_url),
        "database_host": (urlsplit(db_url).hostname if db_url else None),
        "password_configured": has_password,
        "keybca_configured": has_keybca,
        "agent_keys_found": agent_key_count,
        "idle_timeout_seconds": SESSION_IDLE_TIMEOUT_SECONDS,
    }
    if db_url:
        # A live DB is the only thing that makes sessions survive across
        # Vercel cold-starts, so this check is the single most useful
        # one on Vercel. Run it inside try/except so a transient DB
        # outage surfaces as ok=False instead of a 500.
        try:
            from .database import get_auth_session_count
            payload["db_ok"] = True
            payload["session_rows"] = get_auth_session_count()
        except Exception as exc:
            payload["db_ok"] = False
            payload["db_error"] = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )[-400:]
    return JSONResponse(content=payload)


# --- Authentication & Face Biometrics ---
@app.post("/api/auth/login")
def login(req: LoginRequest, request: Request, response: Response):
    now = time.time()
    lockout_key = _login_lockout_id(request, None)
    attempts, locked_until = get_login_lockout(lockout_key, now)
    if locked_until > now:
        retry_after = int(locked_until - now) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Terlalu banyak percobaan. Coba lagi dalam {retry_after} detik.",
            headers={"Retry-After": str(retry_after)},
        )

    configured_password = os.environ.get("ENKRIPSIH_PASSWORD", "")
    if not hmac.compare_digest(req.password, configured_password):
        _handle_failed_login(
            lockout_key, now,
            "Password tidak benar. ",
            "Percobaan login komandan gagal.",
        )
        return

    clear_login_lockout(lockout_key)
    token = secrets.token_urlsafe(32)
    expires_at = time.time() + SESSION_IDLE_TIMEOUT_SECONDS
    principal = {
        "principal_id": "CMD-01",
        "role": "COMMANDER",
        "must_change_password": False,
        "face_verified": False,
    }
    _store_session(token, expires_at, principal)
    _set_session_cookie(response, request, token)
    log_event("AUTH", "SUCCESS", "Login komandan berhasil.")
    return {
        "success": True,
        "idle_timeout_seconds": SESSION_IDLE_TIMEOUT_SECONDS,
        **principal,
    }


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_COOKIE_MAX_AGE,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )


def _login_lockout_id(request: Request, account_id: str | None) -> str:
    if account_id:
        return f"account:{account_id.lower()}"
    # Security: only trust X-Forwarded-For when the request genuinely originated
    # from a trusted proxy.  In standalone uvicorn (host="127.0.0.1") there is
    # no reverse proxy, so the real client IP is request.client.host.
    # Trusting a client-supplied XFF without a trusted proxy in front would let
    # an attacker rotate IPs per-request and bypass the 5-attempt lockout.
    client_host = request.client.host if request.client else "unknown"
    # Only honor XFF behind a trusted proxy; detect this via a single hop
    # from a loopback/10/172.16/192.168 origin OR when explicitly configured.
    trusted_xff = _is_trusted_proxy(request)
    if trusted_xff:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded and _looks_like_ip(forwarded):
            return f"ip:{forwarded}"
    return f"ip:{client_host}"


def _is_trusted_proxy(request: Request) -> bool:
    """Return True only if the hop *before* the origin server is a known proxy."""
    if request.client is None:
        return False
    hop_ip = request.client.host
    # Loopback / private ranges are considered trusted hops (e.g., nginx on localhost)
    return (
        hop_ip.startswith("127.")
        or hop_ip == "::1"
        or hop_ip.startswith("10.")
        or hop_ip.startswith("172.")
        or hop_ip.startswith("192.168.")
    )


def _looks_like_ip(value: str) -> bool:
    import ipaddress
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _password_hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS
    ).hex()


def _handle_failed_login(
    lockout_key: str,
    now: float,
    error_detail: str,
    attempt_log_message: str,
) -> None:
    attempts, _ = get_login_lockout(lockout_key, now)
    attempts += 1
    locked_until = record_failed_login(
        lockout_key, attempts, now,
        max_attempts=LOGIN_MAX_ATTEMPTS,
        lockout_seconds=LOGIN_LOCKOUT_SECONDS,
    )
    if locked_until > now:
        retry_after = int(locked_until - now) + 1
        log_event("AUTH", "DENIED", attempt_log_message)
        raise HTTPException(
            status_code=429,
            detail=f"Akses dikunci sementara selama 5 menit. Coba lagi dalam {retry_after} detik.",
            headers={"Retry-After": str(retry_after)},
        )
    log_event("AUTH", "DENIED", attempt_log_message)
    remaining = max(0, LOGIN_MAX_ATTEMPTS - attempts)
    if remaining > 0:
        raise HTTPException(status_code=401, detail=f"{error_detail} Sisa {remaining} percobaan.")
    raise HTTPException(status_code=401, detail=error_detail)


def _new_receiver_password() -> str:
    return secrets.token_urlsafe(18)


def _iot_shared_secret() -> str:
    """Shared secret for authenticating IoT device / serial-bridge HMAC calls."""
    return os.environ.get("ENKRIPSIH_IOT_TOKEN", "")


def _verify_iot_hmac(payload: str, provided: str) -> bool:
    """Verify HMAC-SHA256(payload, ENKRIPSIH_IOT_TOKEN) == provided."""
    secret = _iot_shared_secret()
    if not secret or not provided:
        return False
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided.lower())


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
    now = time.time()
    username = req.username.strip().lower()
    lockout_key = _login_lockout_id(request, username)
    attempts, locked_until = get_login_lockout(lockout_key, now)
    if locked_until > now:
        retry_after = int(locked_until - now) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Terlalu banyak percobaan. Coba lagi dalam {retry_after} detik.",
            headers={"Retry-After": str(retry_after)},
        )

    account = get_receiver_account(req.username.strip())
    salt = bytes.fromhex(account["password_salt"]) if account else bytes(16)
    expected_hash = account["password_hash"] if account else "00" * 32
    actual_hash = _password_hash(req.password, salt)
    password_valid = hmac.compare_digest(actual_hash, expected_hash)
    if account is None or not password_valid:
        _handle_failed_login(
            lockout_key, now,
            "Nama pengguna atau password tidak benar. ",
            "Percobaan login receiver gagal.",
        )
        return

    clear_login_lockout(lockout_key)
    token = secrets.token_urlsafe(32)
    expires_at = time.time() + SESSION_IDLE_TIMEOUT_SECONDS
    principal = {
        "principal_id": account["recipient_id"],
        "role": "RECEIVER",
        "must_change_password": bool(account["must_change_password"]),
    }
    _store_session(token, expires_at, principal)
    _set_session_cookie(response, request, token)
    log_event("AUTH", "SUCCESS", f"Login receiver [{account['recipient_id']}] berhasil.")
    return {
        "success": True,
        "idle_timeout_seconds": SESSION_IDLE_TIMEOUT_SECONDS,
        **principal,
    }


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
    return {
        "success": True,
        "idle_timeout_seconds": SESSION_IDLE_TIMEOUT_SECONDS,
    }


@app.get("/api/auth/session")
def get_session(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    principal = _session_principal(token)
    if token and principal is not None:
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=SESSION_COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            path="/",
        )
    return {
        "authenticated": principal is not None,
        "idle_timeout_seconds": SESSION_IDLE_TIMEOUT_SECONDS,
        **(principal or {}),
    }


@app.post("/api/auth/activity", status_code=204)
def record_activity(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        _touch_session(token)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=SESSION_COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            path="/",
        )
    return Response(status_code=204)


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        active_sessions.pop(token, None)
        if os.environ.get("DATABASE_URL"):
            delete_auth_session(token)
        await manager.disconnect_session(token)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
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
def verify_face_endpoint(req: FaceAuthRequest, request: Request):
    principal = request.state.principal
    if principal["role"] != "COMMANDER":
        raise HTTPException(status_code=403, detail="Hanya komandan yang dapat verifikasi wajah.")
    from .face_auth import verify_commander_face
    result = verify_commander_face(req.image_base64, req.user_id or "CMD-01")
    if result.get("success"):
        token = request.cookies.get(SESSION_COOKIE)
        if token and token in active_sessions:
            active_sessions[token]["face_verified"] = True
        if os.environ.get("DATABASE_URL"):
            mark_face_verified(token)
        log_event("AUTH", "SUCCESS", f"Verifikasi wajah komandan {principal['principal_id']} BERHASIL.")
    return result

@app.post("/api/auth/register-face")
def register_face_endpoint(req: FaceAuthRequest):
    from .face_auth import register_commander_face

    return register_commander_face(req.image_base64, req.user_id or "CMD-01")

# --- Agent key helpers (reads .env directly, no in-memory cache) ---


# --- Endpoints that depend on agent keys ---
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

    encrypted_agent_secret = None
    if getattr(req, "secret_key", None):
        from .env_agents import write_agent_secret_to_db
        encrypted_agent_secret = write_agent_secret_to_db(recipient_id, req.secret_key)

    if not register_recipient_key(
        recipient_id, name, req.salt.lower(), req.verifier.lower(),
        username, password_salt.hex(),
        _password_hash(temporary_password, password_salt),
        agent_secret=encrypted_agent_secret,
    ):
        raise HTTPException(
            status_code=409,
            detail="Nama anggota sudah terdaftar. Gunakan nama berbeda atau hubungi admin untuk rotasi kunci.",
        )

    # Keep the legacy .env path working for local dev, but the DB copy is
    # now authoritative for the agent encryption endpoint on Vercel.
    if getattr(req, "secret_key", None):
        try:
            from .env_agents import upsert_agent_secret_key
            upsert_agent_secret_key(name, req.secret_key)
            log_event("KEY", "INFO", f"Kunci agen [{name}] ditambahkan ke .env otomatis.")
        except Exception as e:
            log_event("KEY", "WARNING", f"Gagal menulis .env untuk [{name}]: {e}")

    log_event("KEY", "SUCCESS", f"Kunci verifier anggota [{recipient_id}] didaftarkan.")
    if encrypted_agent_secret:
        log_event("KEY", "INFO", f"Secret key agen [{name}] disimpan terenkripsi ke database.")
    return {
        "success": True,
        "recipient_id": recipient_id,
        "name": name,
        "username": username,
        "temporary_password": temporary_password,
        "agent_env": bool(getattr(req, "secret_key", None)),
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


@app.delete("/api/recipients/{recipient_id}")
async def delete_recipient_endpoint(recipient_id: str, request: Request):
    principal = getattr(request.state, "principal", None) if request else None
    if not principal or principal["role"] != "COMMANDER":
        raise HTTPException(status_code=403, detail="Hanya komandan yang dapat menghapus anggota.")
    recipient = get_recipient_key(recipient_id)
    if not recipient:
        raise HTTPException(status_code=404, detail="Anggota tidak ditemukan.")

    deleted_msgs = delete_recipient(recipient_id)
    log_event("KEY", "WARNING", f"Anggota [{recipient_id}] dihapus beserta {deleted_msgs} pesan terkait.")

    await manager.broadcast(
        {"type": "RECIPIENT_DELETED", "recipient_id": recipient_id},
        recipient_id=recipient_id,
    )

    return {
        "success": True,
        "recipient_id": recipient_id,
        "deleted_messages": deleted_msgs,
    }


@app.post("/api/recipients/{recipient_id}/reissue")
async def reissue_recipient_key_endpoint(recipient_id: str, request: Request):
    principal = getattr(request.state, "principal", None) if request else None
    if not principal or principal["role"] != "COMMANDER":
        raise HTTPException(status_code=403, detail="Hanya komandan yang dapat me-reissue kunci anggota.")
    recipient = get_recipient_key(recipient_id)
    if not recipient:
        raise HTTPException(status_code=404, detail="Anggota tidak ditemukan.")

    new_secret_key = secrets.token_urlsafe(24)
    new_salt = secrets.token_hex(16)

    loop = asyncio.get_event_loop()
    new_verifier = await loop.run_in_executor(
        None,
        lambda: hashlib.pbkdf2_hmac(
            "sha256",
            new_secret_key.encode("utf-8"),
            b"enkripsih:recipient:v1:" + bytes.fromhex(new_salt),
            600_000,
            32,
        ).hex(),
    )

    if not reissue_recipient_key(recipient_id, new_salt, new_verifier):
        raise HTTPException(status_code=409, detail="Gagal me-reissue kunci.")

    from .env_agents import write_agent_secret_to_db
    from .database import update_agent_secret
    encrypted_new_secret = write_agent_secret_to_db(recipient_id, new_secret_key)
    update_agent_secret(recipient_id, encrypted_new_secret)

    # If this recipient has an agent key in .env, refresh the key in .env too
    try:
        from .env_agents import upsert_agent_secret_key_inplace
        upsert_agent_secret_key_inplace(recipient["name"], new_secret_key)
        log_event("KEY", "INFO", f"Kunci agen [{recipient['name']}] diperbarui di .env.")
    except Exception as e:
        log_event("KEY", "WARNING", f"Gagal menulis .env saat reissue [{recipient['name']}]: {e}")

    log_event("KEY", "WARNING", f"Kunci anggota [{recipient_id}] di-reissue. Kunci lama tidak lagi valid untuk pesan baru.")

    await manager.broadcast(
        {"type": "RECIPIENT_KEY_REISSUED", "recipient_id": recipient_id},
        recipient_id=recipient_id,
    )

    return {
        "success": True,
        "recipient_id": recipient_id,
        "new_secret_key": new_secret_key,
        "note": "Kunci baru hanya ditampilkan sekali. Bagikan ke anggota lewat jalur aman.",
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


@app.get("/api/agent-keys")
def agent_keys_endpoint(request: Request):
    """
    Returns the plaintext secret key for each env-configured agent.
    Reads directly from .env on each call (no cache).
    Commander-only: receiver or unauthenticated callers get 403.
    """
    principal = getattr(request.state, "principal", None) if request else None
    if not principal or principal["role"] != "COMMANDER":
        raise HTTPException(status_code=403, detail="Hanya komandan yang dapat melihat kunci agen.")
    # Read .env directly, match to DB recipients by name (case-insensitive).
    from .env_agents import list_agent_env_keys
    env_keys = list_agent_env_keys()
    recipients = get_recipient_keys()
    result = []
    for env_name, key in env_keys.items():
        # Find the DB recipient matching this env agent name
        rec = next(
            (r for r in recipients if r.get("name") and r["name"].lower().replace(' ', '_') == env_name.lower()),
            None,
        )
        result.append({
            "recipient_id": rec["id"] if rec else None,
            "name": rec["name"] if rec else env_name,
            "key": key,
        })
    return {"agent_keys": result}


def _require_receiver_message_access(msg: dict, request: Request = None) -> None:
    principal = getattr(request.state, "principal", None) if request else None
    if (
        principal and principal["role"] == "RECEIVER"
        and principal["principal_id"] != msg["recipient_id"]
    ):
        raise HTTPException(status_code=404, detail="Pesan tidak ditemukan.")


class EncryptMessageRequest(BaseModel):
    plaintext: str
    recipient_id: str
    secret_key: str
    save: bool = True


class EncryptAgentMessageRequest(BaseModel):
    """Commander only: encrypt to an agent whose key is stored server-side.
    No secret_key needed in the body — the server resolves it from .env cache.
    """
    plaintext: str
    recipient_id: str
    save: bool = True

def _verify_secret_key(recipient: dict, secret_key: str) -> bool:
    """Verify a secret key by recomputing its PBKDF2 verifier against the stored value.
    Runs in a thread-pool via verify_recipient_secret().
    """
    salt = bytes.fromhex(recipient["salt"].lower())
    computed = hashlib.pbkdf2_hmac(
        "sha256",
        secret_key.encode("utf-8"),
        b"enkripsih:recipient:v1:" + salt,
        600_000,
        32,
    ).hex()
    return hmac.compare_digest(computed, recipient["verifier"].lower())


async def verify_recipient_secret(recipient: dict, secret_key: str) -> bool:
    """Wrapper for verify logic so callers can use await (thread-pool safe)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _verify_secret_key, recipient, secret_key)


async def _compute_encrypt_work(recipient: dict, secret_key: str, plaintext: str):
    """Run the heavy, blocking crypto (PBKDF2 x2 + AES-GCM) off the event loop.

    Kept in one coroutine so the browser sees a single fast request instead of
    the event loop stalling for ~15s.
    """
    loop = asyncio.get_event_loop()

    def _work():
        import hashlib as _hl
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        salt = bytes.fromhex(recipient["salt"].lower())
        computed_verifier = _hl.pbkdf2_hmac(
            "sha256",
            secret_key.encode("utf-8"),
            b"enkripsih:recipient:v1:" + salt,
            600_000,
            32,
        ).hex()
        if not hmac.compare_digest(computed_verifier, recipient["verifier"].lower()):
            return {"error": "mismatch"}

        challenge_indices = [secrets.randbelow(4) for _ in range(4)]
        challenge_bytes = bytes(challenge_indices)
        mac = hmac.new(secret_key.encode("utf-8"), challenge_bytes, hashlib.sha256).digest()
        resp_indices = [(mac[i // 4] >> ((i % 4) * 2)) & 3 for i in range(12)]
        response_letters = "".join(LETTERS[r] for r in resp_indices)

        aes_salt = os.urandom(16)
        iv = os.urandom(12)
        aes_key = _hl.pbkdf2_hmac("sha256", bytes(resp_indices), aes_salt, 200_000, 32)
        ciphertext = AESGCM(aes_key).encrypt(iv, plaintext.encode("utf-8"), None)

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

        return {
            "challenge_indices": challenge_indices,
            "response_letters": response_letters,
            "resp_indices": resp_indices,
            "salt": b64url(aes_salt),
            "iv": b64url(iv),
            "ciphertext": b64url(ciphertext),
        }

    return await loop.run_in_executor(None, _work)


@app.post("/api/messages/encrypt")
async def encrypt_message_endpoint(req: EncryptMessageRequest, request: Request = None):
    principal = getattr(getattr(request, "state", None), "principal", None) if request else None
    if not principal or principal["role"] != "COMMANDER":
        raise HTTPException(status_code=403, detail="Hanya komandan yang dapat mengenkripsi pesan.")
    recipient = get_recipient_key(req.recipient_id)
    if not recipient:
        raise HTTPException(status_code=404, detail="Anggota belum terdaftar.")
    if len(req.plaintext) > 50_000:
        raise HTTPException(status_code=413, detail="Pesan terlalu panjang.")

    work = await _compute_encrypt_work(recipient, req.secret_key, req.plaintext)
    if work.get("error"):
        raise HTTPException(status_code=400, detail="Secret key tidak cocok dengan anggota yang terdaftar.")

    challenge_indices = work["challenge_indices"]

    envelope = {
        "v": 5,
        "salt": work["salt"],
        "iv": work["iv"],
        "ciphertext": work["ciphertext"],
        "challenge": "".join(LETTERS[c] for c in challenge_indices),
    }
    paket = json.dumps(envelope)

    sent_data = None
    if req.save:
        profile = get_commander_profile(principal["principal_id"])
        sender_name = profile["name"] if profile else principal["principal_id"]
        msg_id = f"MSG-{datetime.now().strftime('%m%d')}-{os.urandom(16).hex().upper()}"
        msg_record = {
            "id": msg_id,
            "sender_id": principal["principal_id"],
            "sender_name": sender_name,
            "target_unit": recipient["name"],
            "recipient_id": recipient["id"],
            "paket": paket,
            "status": "LOCKED",
            "created_at": datetime.now().isoformat()
        }
        save_message(msg_record)
        log_event("TRANSMIT", "SUCCESS", f"Ciphertext [{msg_id}] ditransmisikan ke {recipient['name']}.")
        await manager.broadcast({
            "type": "NEW_MESSAGE",
            "message": {
                "id": msg_id,
                "target_unit": recipient["name"],
                "status": "LOCKED",
                "created_at": msg_record["created_at"]
            }
        }, recipient_id=recipient["id"])
        sent_data = {
            "message_id": msg_id,
            "target_unit": recipient["name"],
            "status": "LOCKED"
        }

    return {
        "success": True,
        "paket": paket,
        "challenge_indices": challenge_indices,
        "challenge_letters": "".join(LETTERS[c] for c in challenge_indices),
        "challenge_symbols": " ".join(NAMES[c] for c in challenge_indices),
        "saved": sent_data,
    }


@app.post("/api/messages/encrypt-agent")
async def encrypt_agent_message_endpoint(req: EncryptAgentMessageRequest, request: Request = None):
    """Encrypt a message to an agent whose secret key is stored in the database.
    The commander does not need to know or type the secret key — the server
    reads it directly from the encrypted database record (fallback: .env)."""
    principal = getattr(getattr(request, "state", None), "principal", None) if request else None
    if not principal or principal["role"] != "COMMANDER":
        raise HTTPException(status_code=403, detail="Hanya komandan yang dapat mengenkripsi pesan.")
    recipient = get_recipient_key(req.recipient_id)
    if not recipient:
        raise HTTPException(status_code=404, detail="Anggota belum terdaftar.")
    if len(req.plaintext) > 50_000:
        raise HTTPException(status_code=413, detail="Pesan terlalu panjang.")

    # Prefer the encrypted agent key persisted in the database. This makes
    # newly registered agents work on Vercel without adding env vars.
    from .env_agents import read_agent_secret_key, read_agent_secret_from_db
    secret_key = read_agent_secret_from_db(recipient["id"], recipient.get("agent_secret"))
    key_source = "database"
    if not secret_key:
        secret_key = read_agent_secret_key(recipient["name"])
        key_source = "env"
    if not secret_key:
        raise HTTPException(
            status_code=400,
            detail=f"Anggota '{recipient['name']}' tidak memiliki kunci agen. "
                   f"Daftarkan anggota lewat form register atau tambah AGENT_{recipient['name'].upper().replace(' ', '_')}_SECRET_KEY ke .env/env vars.",
        )

    # Skip DB verifier check for agent keys — the persisted key is authoritative.
    work = await _compute_encrypt_work_agent(recipient, secret_key, req.plaintext)
    if work.get("error"):
        raise HTTPException(status_code=500, detail="Gagal mengenkripsi pesan.")

    challenge_indices = work["challenge_indices"]

    envelope = {
        "v": 5,
        "salt": work["salt"],
        "iv": work["iv"],
        "ciphertext": work["ciphertext"],
        "challenge": "".join(LETTERS[c] for c in challenge_indices),
    }
    paket = json.dumps(envelope)

    sent_data = None
    if req.save:
        profile = get_commander_profile(principal["principal_id"])
        sender_name = profile["name"] if profile else principal["principal_id"]
        msg_id = f"MSG-{datetime.now().strftime('%m%d')}-{os.urandom(16).hex().upper()}"
        msg_record = {
            "id": msg_id,
            "sender_id": principal["principal_id"],
            "sender_name": sender_name,
            "target_unit": recipient["name"],
            "recipient_id": recipient["id"],
            "paket": paket,
            "status": "LOCKED",
            "created_at": datetime.now().isoformat(),
        }
        save_message(msg_record)
        log_event("TRANSMIT", "SUCCESS", f"Ciphertext [{msg_id}] ditransmisikan ke {recipient['name']} (agent .env key).")
        await manager.broadcast({
            "type": "NEW_MESSAGE",
            "message": {
                "id": msg_id,
                "target_unit": recipient["name"],
                "status": "LOCKED",
                "created_at": msg_record["created_at"],
            },
        }, recipient_id=recipient["id"])
        sent_data = {
            "message_id": msg_id,
            "target_unit": recipient["name"],
            "status": "LOCKED",
        }

    return {
        "success": True,
        "paket": paket,
        "challenge_indices": challenge_indices,
        "challenge_letters": "".join(LETTERS[c] for c in challenge_indices),
        "challenge_symbols": " ".join(NAMES[c] for c in challenge_indices),
        "saved": sent_data,
    }


async def _compute_encrypt_work_agent(recipient: dict, secret_key: str, plaintext: str):
    """Same as _compute_encrypt_work but skips the DB verifier check.
    Used only for agents whose key is authoritative from .env."""
    loop = asyncio.get_event_loop()

    def _work():
        import hashlib as _hl
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        challenge_indices = [secrets.randbelow(4) for _ in range(4)]
        challenge_bytes = bytes(challenge_indices)
        mac = hmac.new(secret_key.encode("utf-8"), challenge_bytes, hashlib.sha256).digest()
        resp_indices = [(mac[i // 4] >> ((i % 4) * 2)) & 3 for i in range(12)]

        aes_salt = os.urandom(16)
        iv = os.urandom(12)
        aes_key = _hl.pbkdf2_hmac("sha256", bytes(resp_indices), aes_salt, 200_000, 32)
        ciphertext = AESGCM(aes_key).encrypt(iv, plaintext.encode("utf-8"), None)

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

        return {
            "challenge_indices": challenge_indices,
            "salt": b64url(aes_salt),
            "salt_hex": aes_salt.hex(),
            "iv": b64url(iv),
            "ciphertext": b64url(ciphertext),
        }

    return await loop.run_in_executor(None, _work)


@app.post("/api/messages/decrypt")
async def decrypt_message_endpoint(request: Request):
    """Receiver decrypts a message using the 12-symbol passkey response (or secret key for legacy).

    Body: { message_id, passkey_letters? }
    Returns: { success, plaintext, message_id }
    PBKDF2 (200k) runs on server — fast, non-blocking for the browser.
    """
    principal = getattr(request.state, "principal", None)
    if not principal:
        raise HTTPException(status_code=401, detail="Sesi tidak valid.")
    if principal["role"] != "RECEIVER":
        raise HTTPException(status_code=403, detail="Hanya anggota receiver yang dapat membuka pesan.")

    try:
        body = await request.json()
    except Exception:
        body = {}

    message_id = body.get("message_id", "").strip()
    passkey_letters = (body.get("passkey_letters") or "").strip().upper()

    msg = get_message_by_id(message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Pesan tidak ditemukan.")
    if msg["recipient_id"] != principal["principal_id"]:
        raise HTTPException(status_code=404, detail="Pesan ini bukan untuk akun Anda.")

    try:
        envelope = json.loads(msg["paket"])
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Format ciphertext tidak valid.")

    if envelope.get("v") != 5:
        raise HTTPException(status_code=400, detail="Format pesan lama — gunakan aplikasi lama untuk membuka.")

    if not passkey_letters or not re.fullmatch(r"[TCXS]{12}", passkey_letters):
        raise HTTPException(status_code=400, detail="Respons passkey 12 simbol wajib diisi. Masukkan respons dari perangkat KeyBCA Anda.")

    resp_indices = [LETTERS.find(ch) for ch in passkey_letters]

    # Throttle brute-force attempts on the expensive PBKDF2 step so a
    # compromised receiver account cannot starve the worker.
    lock_key = "decrypt:" + principal["principal_id"]
    now = time.time()
    dec_attempts, dec_locked_until = get_login_lockout(lock_key, now)
    if dec_locked_until > now:
        retry_after = int(dec_locked_until - now) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Terlalu banyak percobaan. Coba lagi dalam {retry_after} detik.",
            headers={"Retry-After": str(retry_after)},
        )

    salt = base64.urlsafe_b64decode(envelope["salt"] + "=" * (-len(envelope["salt"]) % 4))
    iv = base64.urlsafe_b64decode(envelope["iv"] + "=" * (-len(envelope["iv"]) % 4))
    ciphertext = base64.urlsafe_b64decode(envelope["ciphertext"] + "=" * (-len(envelope["ciphertext"]) % 4))

    # PBKDF2 200k — same as frontend deriveBitsFromDeviceResponse
    aes_key = hashlib.pbkdf2_hmac("sha256", bytes(resp_indices), salt, 200_000, 32)

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidTag
    try:
        plaintext_bytes = AESGCM(aes_key).decrypt(iv, ciphertext, None)
        plaintext = plaintext_bytes.decode("utf-8")
    except InvalidTag:
        dec_attempts += 1
        dec_locked = record_failed_login(
            lock_key, dec_attempts, now,
            max_attempts=5, lockout_seconds=300,
        )
        if dec_locked > now:
            retry_after = int(dec_locked - now) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Percobaan gagal berulang. Coba lagi dalam {retry_after} detik.",
                headers={"Retry-After": str(retry_after)},
            )
        raise HTTPException(status_code=400, detail="Respons passkey salah — pesan tidak dapat dibuka.")

    clear_login_lockout(lock_key)

    # Mark as decrypted
    mark_message_decrypted(message_id, principal["principal_id"])

    return {
        "success": True,
        "message_id": message_id,
        "plaintext": plaintext,
    }

@app.post("/api/messages/send")
async def send_message_endpoint(req: SendMessageRequest, request: Request = None):
    principal = getattr(getattr(request, "state", None), "principal", None) if request else None
    if not principal or principal["role"] != "COMMANDER":
        raise HTTPException(status_code=403, detail="Hanya komandan yang dapat mengirim pesan.")
    profile = get_commander_profile(principal["principal_id"])
    sender_id = principal["principal_id"]
    sender_name = profile["name"] if profile else principal["principal_id"]
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

    msg_id = f"MSG-{datetime.now().strftime('%m%d')}-{os.urandom(16).hex().upper()}"
    msg_record = {
        "id": msg_id,
        "sender_id": sender_id,
        "sender_name": sender_name,
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
def api_get_all_messages(request: Request):
    principal = getattr(request.state, "principal", None)
    is_receiver = bool(principal and principal["role"] == "RECEIVER")
    messages = get_messages()
    if is_receiver:
        messages = [
            message for message in messages
            if message["recipient_id"] == principal["principal_id"]
        ]
    # expected_response is never surfaced in the list view: the receiver must
    # derive it from their device, so it stays out of the summary payload.
    return {
        "messages": [
            _message_summary(msg, include_expected_response=False)
            for msg in messages
        ]
    }


def get_all_messages(include_expected_response: bool = False):
    messages = get_messages()
    return {
        "messages": [
            _message_summary(msg, include_expected_response=include_expected_response)
            for msg in messages
        ]
    }


def _message_summary(msg: dict, include_expected_response: bool = True) -> dict:
    passkey_challenge = None
    encryption_version = None
    expected_response = None
    if msg["status"] != "BURNED" and msg["paket"]:
        try:
            envelope = json.loads(msg["paket"])
            version = envelope.get("v") if isinstance(envelope, dict) else None
            if type(version) is int and version in {1, 2, 3, 4, 5}:
                encryption_version = version
            challenge = envelope.get("challenge") if isinstance(envelope, dict) else None
            if isinstance(challenge, str) and re.fullmatch(r"[TCXS]{4}", challenge):
                passkey_challenge = challenge
            response = envelope.get("expected_response") if isinstance(envelope, dict) else None
            if isinstance(response, str) and re.fullmatch(r"[TCXS]{12}", response) and encryption_version == 5:
                expected_response = response
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
        "decrypted_at": msg.get("decrypted_at"),
        "encrypted": bool(msg["paket"]) and msg["status"] not in {"BURNED", "UNLOCKED"},
        "passkey_challenge": passkey_challenge,
        "encryption_version": encryption_version,
    }
    if include_expected_response:
        summary["expected_response"] = expected_response
    return summary

@app.get("/api/messages/{msg_id}")
def get_message_detail(msg_id: str, request: Request = None):
    msg = get_message_by_id(msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Pesan tidak ditemukan.")
    _require_receiver_message_access(msg, request)
    principal = getattr(request.state, "principal", None) if request else None
    is_receiver = bool(principal and principal["role"] == "RECEIVER")
    return _message_summary(msg, include_expected_response=is_receiver)

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

@app.post("/api/messages/{msg_id}/unlock")
async def unlock_message_endpoint(msg_id: str, request: Request):
    msg = get_message_by_id(msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Pesan tidak ditemukan.")
    principal = getattr(request.state, "principal", None)
    if not principal or principal["role"] != "RECEIVER":
        raise HTTPException(status_code=403, detail="Hanya receiver yang dapat membuka pesan.")
    if msg["recipient_id"] != principal["principal_id"]:
        raise HTTPException(status_code=404, detail="Pesan tidak ditemukan.")
    if msg["status"] in {"BURNED", "UNLOCKED"}:
        return {"success": True, "already": True}
    mark_message_decrypted(msg_id, principal["principal_id"])
    log_event("DECRYPT", "SUCCESS", f"Pesan [{msg_id}] berhasil dibuka oleh receiver.")
    await manager.broadcast(
        {"type": "MESSAGE_UNLOCKED", "message_id": msg_id},
        recipient_id=principal["principal_id"],
    )
    return {"success": True}


@app.post("/api/messages/{msg_id}/burn")
async def burn_message_endpoint(msg_id: str, request: Request):
    msg = get_message_by_id(msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Pesan tidak ditemukan.")
    principal = getattr(request.state, "principal", None)
    if not principal:
        raise HTTPException(status_code=401, detail="Login diperlukan.")
    # Commander can burn any message; receiver can only burn their own decrypted message
    if principal["role"] == "COMMANDER":
        pass
    elif principal["role"] == "RECEIVER":
        if msg["recipient_id"] != principal["principal_id"]:
            raise HTTPException(status_code=404, detail="Pesan tidak ditemukan.")
        if not msg.get("decrypted_at"):
            raise HTTPException(
                status_code=403,
                detail="Pesan belum dibuka. Buka pesan terlebih dahulu sebelum menghapus."
            )
    else:
        raise HTTPException(status_code=403, detail="Akses ditolak.")

    burn_message(msg_id)
    log_event("DECRYPT", "WARNING", f"Pesan [{msg_id}] dihancurkan secara permanen.")
    
    await manager.broadcast({
        "type": "MESSAGE_BURNED",
        "message_id": msg_id
    }, recipient_id=msg["recipient_id"])
    
    return {"success": True, "message": "Pesan berhasil dihancurkan secara permanen."}

# --- Lexa Token IoT Endpoints (legacy /keybca route retained) ---
IOT_TOKEN = os.environ.get("ENKRIPSIH_IOT_TOKEN", "")
IOT_DEV_MODE = os.environ.get("ENKRIPSIH_IOT_DEV_MODE", "").lower() in {"1", "true", "yes"}


def _require_iot_hmac(payload: str, provided: str) -> None:
    """Enforce HMAC verification for IoT endpoints.

    Fails closed: if the IoT token is not configured AND dev mode is not
    explicitly enabled, the request is rejected with 503.

    Dev mode (ENKRIPSIH_IOT_DEV_MODE=1) is opt-in only — it must be
    explicitly set in the environment. By default, IoT HMAC is mandatory.
    """
    if not IOT_TOKEN:
        if not IOT_DEV_MODE:
            raise HTTPException(
                status_code=503,
                detail="IoT token authentication is not configured. "
                       "Set ENKRIPSIH_IOT_TOKEN in the environment to enable IoT endpoints.",
            )
        return  # dev mode: skip HMAC
    if not _verify_iot_hmac(payload, provided or ""):
        raise HTTPException(status_code=401, detail="HMAC signature tidak valid.")


@app.post("/api/iot/keybca/calculate")
def calculate_token_endpoint(req: KeyBCACalculateRequest):
    """
    Computes a 12-symbol Lexa response from a 4-symbol challenge.
    Requires hmac_signature (HMAC-SHA256 of challenge) using ENKRIPSIH_IOT_TOKEN.
    Fails closed when the token is not configured (opt-in dev mode only).
    """
    _require_iot_hmac(str(req.challenge), req.hmac_signature or "")
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
    Requires hmac_signature (HMAC of 'device_id:challenge:token') using ENKRIPSIH_IOT_TOKEN.
    Fails closed when the token is not configured (opt-in dev mode only).
    """
    payload = f"{req.device_id}:{req.challenge}:{req.token}"
    _require_iot_hmac(payload, req.hmac_signature or "")
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
