"""Backend helper: auto-append a new AGENT_<NAME>_SECRET_KEY line to .env,
and read agent keys directly from .env on demand (no in-memory cache)."""
import os
import re
from pathlib import Path

# Resolve .env path relative to the project root (parent of backend/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

# Matches existing agent lines, case-insensitive on the agent name.
_AGENT_LINE_RE = re.compile(
    r'^AGENT_(?P<name>[A-Z0-9_]+)_SECRET_KEY=.*$',
    re.MULTILINE,
)


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


def read_agent_secret_key(name: str) -> str | None:
    """Read AGENT_<NAME>_SECRET_KEY directly from .env on each call.

    No cache: always re-reads the file so edits to .env take effect
    without a server restart. Returns None if not found.
    """
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
    """Return all agent keys from .env as {normalized_name: key}."""
    if not _ENV_PATH.exists():
        return {}
    content = _ENV_PATH.read_text(encoding='utf-8')
    result: dict[str, str] = {}
    for line in content.splitlines():
        m = _AGENT_LINE_RE.match(line.strip())
        if not m:
            continue
        raw_name = m.group('name')
        value = line.split('=', 1)[1].strip()
        if value.startswith(('"', "'")) and value.endswith(value[0]):
            value = value[1:-1]
        if len(value) >= 32:
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
