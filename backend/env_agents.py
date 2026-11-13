"""Backend helper: auto-append a new AGENT_<NAME>_SECRET_KEY line to .env,
and read agent keys directly from .env on demand (no in-memory cache).
Falls back to os.environ when .env is absent (e.g. Vercel runtime)."""
import os
import re
import base64
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Resolve .env path relative to the project root (parent of backend/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

# Matches existing agent lines, case-insensitive on the agent name.
_AGENT_LINE_RE = re.compile(
    r'^AGENT_(?P<name>[A-Z0-9_]+)_SECRET_KEY=.*$',
    re.MULTILINE,
)

_KEYBCA_SECRET_ENV = "ENKRIPSIH_KEYBCA_SECRET"  # nosec B105 — env var name string, not a password


def _get_master_key() -> bytes:
    """Derive a 32-byte AES-GCM key from ENKRIPSIH_KEYBCA_SECRET.

    We use PBKDF2 (32-byte output) so any length of KEYBCA_SECRET works
    without leaking the raw secret directly into the AES key material.
    """
    secret = os.environ.get(_KEYBCA_SECRET_ENV, "")
    if len(secret) < 16:
        raise RuntimeError(
            f"{_KEYBCA_SECRET_ENV} belum diatur atau kurang dari 16 karakter."
        )
    import hashlib
    return hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), b"enkripsih:agent-secret:v1", 600_000, 32)


def encrypt_agent_secret(plaintext: str) -> str:
    """Encrypt an agent secret key with AES-GCM and return base64(nonce+ct)."""
    key = _get_master_key()
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("utf-8")


def decrypt_agent_secret(blob: str | None) -> str | None:
    """Decrypt a base64(nonce+ct) blob produced by encrypt_agent_secret()."""
    if not blob:
        return None
    try:
        key = _get_master_key()
        raw = base64.b64decode(blob)
        nonce, ct = raw[:12], raw[12:]
        return AESGCM(key).decrypt(nonce, ct, None).decode("utf-8")
    except Exception:
        return None


def read_agent_secret_from_db(recipient_id: str, encrypted_secret: str | None) -> str | None:
    """Decrypt and return the agent secret key stored in DB for a recipient."""
    return decrypt_agent_secret(encrypted_secret)


def write_agent_secret_to_db(recipient_id: str, plaintext_secret: str) -> str:
    """Encrypt the plaintext secret and return the base64 blob to persist in DB."""
    return encrypt_agent_secret(plaintext_secret)


def _normalize_agent_key(name: str) -> str:
    """Return a safe key variable suffix for the .env file.
    Uses uppercase and replaces any non-alphanumeric with underscores.
    """
    safe = re.sub(r'[^A-Za-z0-9]', '_', name.strip())
    # Collapse multiple underscores and trim
    safe = re.sub(r'_+', '_', safe).strip('_').upper()
    if len(safe) < 2:
        return None
    return safe


def _env_var_name(name: str) -> str:
    suffix = _normalize_agent_key(name)
    if suffix is None:
        return None
    return f"AGENT_{suffix}_SECRET_KEY"


def read_agent_secret_key(name: str) -> str | None:
    """Read AGENT_<NAME>_SECRET_KEY from .env or os.environ.

    Prefers os.environ first (Vercel), then .env file (local dev).
    No cache: always re-reads so edits take effect without restart.
    """
    var_name = _env_var_name(name)
    if var_name:
        env_val = os.environ.get(var_name)
        if env_val and len(env_val) >= 32:
            return env_val

    suffix = _normalize_agent_key(name)
    if suffix is None:
        return None

    if not _ENV_PATH.exists():
        return None

    content = _ENV_PATH.read_text(encoding='utf-8')
    for line in content.splitlines():
        m = _AGENT_LINE_RE.match(line.strip())
        if not m:
            continue
        if m.group('name').lower() == suffix.lower():
            value = line.split('=', 1)[1].strip()
            # Strip surrounding quotes if present
            if value.startswith(('"', "'")) and value.endswith(value[0]):
                value = value[1:-1]
            return value or None
    return None


def list_agent_env_keys() -> dict[str, str]:
    """Return all agent keys from os.environ + .env as {normalized_name: key}."""
    result: dict[str, str] = {}

    # 1. From os.environ (Vercel runtime)
    for key, value in os.environ.items():
        if key.startswith("AGENT_") and key.endswith("_SECRET_KEY") and len(value) >= 32:
            agent_name = key[len("AGENT_"):-len("_SECRET_KEY")]
            result[agent_name] = value

    # 2. From .env file (local dev, fallback)
    if _ENV_PATH.exists():
        content = _ENV_PATH.read_text(encoding='utf-8')
        for line in content.splitlines():
            m = _AGENT_LINE_RE.match(line.strip())
            if not m:
                continue
            raw_name = m.group('name')
            value = line.split('=', 1)[1].strip()
            if value.startswith(('"', "'")) and value.endswith(value[0]):
                value = value[1:-1]
            if len(value) >= 32 and raw_name not in result:
                result[raw_name] = value

    return result


def upsert_agent_secret_key(name: str, secret_key: str) -> str:
    """Add or update AGENT_<NAME>_SECRET_KEY in .env.

    - If a line with the same (case-insensitive) agent name exists, update it.
    - Otherwise, append a new line.
    Returns the full variable name (e.g. 'AGENT_TOBY_SECRET_KEY').
    """
    suffix = _normalize_agent_key(name)
    if suffix is None:
        raise ValueError(f"Nama agen '{name}' tidak dapat dijadikan variabel .env")

    var_name = f"AGENT_{suffix}_SECRET_KEY"

    if not _ENV_PATH.exists():
        # Create a fresh .env with just this agent line
        _ENV_PATH.write_text(f"{var_name}={secret_key}\n", encoding='utf-8')
        return var_name

    content = _ENV_PATH.read_text(encoding='utf-8')
    lines = content.splitlines()

    new_lines = []
    replaced = False
    for line in lines:
        m = _AGENT_LINE_RE.match(line)
        if m and m.group('name').lower() == suffix.lower():
            # Same agent name (case-insensitive) — update the value
            new_lines.append(f"{var_name}={secret_key}")
            replaced = True
        else:
            new_lines.append(line)

    if not replaced:
        new_lines.append(f"{var_name}={secret_key}")

    _ENV_PATH.write_text('\n'.join(new_lines) + '\n', encoding='utf-8')
    return var_name


def upsert_agent_secret_key_inplace(name: str, secret_key: str) -> str:
    """Same as upsert_agent_secret_key but only updates an existing key;
    does not append a new line if the agent doesn't exist yet.
    Used by /reissue to keep the same env key name but with a new value.
    """
    suffix = _normalize_agent_key(name)
    if suffix is None:
        raise ValueError(f"Nama agen '{name}' tidak dapat dijadikan variabel .env")

    var_name = f"AGENT_{suffix}_SECRET_KEY"

    if not _ENV_PATH.exists():
        return var_name  # Nothing to update

    content = _ENV_PATH.read_text(encoding='utf-8')
    lines = content.splitlines()

    new_lines = []
    for line in lines:
        m = _AGENT_LINE_RE.match(line)
        if m and m.group('name').lower() == suffix.lower():
            new_lines.append(f"{var_name}={secret_key}")
        else:
            new_lines.append(line)

    _ENV_PATH.write_text('\n'.join(new_lines) + '\n', encoding='utf-8')
    return var_name


def list_agent_keys_from_db() -> list[tuple[str, str]]:
    """Return a list of (agent_name, plaintext_secret_key) for every agent
    that has an encrypted agent_secret stored in the database. This is the
    runtime source of truth on Vercel where .env entries do not persist.
    """
    from .database import get_recipient_keys
    out: list[tuple[str, str]] = []
    for row in get_recipient_keys(include_secrets=True):
        blob = row.get("agent_secret")
        if not blob:
            continue
        try:
            key = decrypt_agent_secret(blob)
        except Exception:
            # If the key can't be decrypted, skip it — the agent needs a
            # fresh registration or reissue.
            continue
        if key and len(key) >= 32:
            out.append((row["name"], key))
    return out
