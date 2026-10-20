import os
import json
from pathlib import Path
from typing import Optional
from backend.config import DATA_DIR

try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    keyring = None
    KEYRING_AVAILABLE = False

SERVICE_NAME = "robonest_ai_office"
FALLBACK_SECRETS_FILE = DATA_DIR / ".secrets.json"


class SecretManager:
    """
    Manages API keys and sensitive credentials safely.
    Lookup priority for get_secret:
    1. Environment variables
    2. OS Keyring (via keyring library)
    3. Local fallback file inside data/ (owner-readable/writable)
    """

    @classmethod
    def get_secret(cls, key: str) -> Optional[str]:
        # 1. Environment variable check
        env_val = os.getenv(key)
        if env_val:
            return env_val

        # 2. Keyring check
        if KEYRING_AVAILABLE:
            try:
                val = keyring.get_password(SERVICE_NAME, key)
                if val:
                    return val
            except Exception:
                pass

        # 3. Local fallback file
        if FALLBACK_SECRETS_FILE.exists():
            try:
                data = json.loads(FALLBACK_SECRETS_FILE.read_text(encoding="utf-8"))
                return data.get(key)
            except Exception:
                return None

        return None

    @classmethod
    def get_persisted_secret(cls, key: str) -> Optional[str]:
        """Read a keyring/local saved value without letting a process env var mask it."""
        if KEYRING_AVAILABLE:
            try:
                val = keyring.get_password(SERVICE_NAME, key)
                if val:
                    return val
            except Exception:
                pass
        if FALLBACK_SECRETS_FILE.exists():
            try:
                data = json.loads(FALLBACK_SECRETS_FILE.read_text(encoding="utf-8"))
                return data.get(key)
            except Exception:
                return None
        return None

    @classmethod
    def set_secret(cls, key: str, value: str) -> bool:
        # Try keyring first
        saved_keyring = False
        if KEYRING_AVAILABLE:
            try:
                keyring.set_password(SERVICE_NAME, key, value)
                saved_keyring = True
            except Exception:
                saved_keyring = False

        # Also persist to local data fallback
        try:
            data = {}
            if FALLBACK_SECRETS_FILE.exists():
                try:
                    data = json.loads(FALLBACK_SECRETS_FILE.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            data[key] = value
            FALLBACK_SECRETS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
            # Set file permissions to owner read/write only (600)
            try:
                os.chmod(FALLBACK_SECRETS_FILE, 0o600)
            except Exception:
                pass
            return True
        except Exception:
            return saved_keyring

    @classmethod
    def delete_secret(cls, key: str) -> bool:
        if KEYRING_AVAILABLE:
            try:
                keyring.delete_password(SERVICE_NAME, key)
            except Exception:
                pass

        if FALLBACK_SECRETS_FILE.exists():
            try:
                data = json.loads(FALLBACK_SECRETS_FILE.read_text(encoding="utf-8"))
                if key in data:
                    del data[key]
                    FALLBACK_SECRETS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
                return True
            except Exception:
                return False
        return True
