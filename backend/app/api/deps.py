import hmac

from fastapi import Header, HTTPException, status

from app.config import get_settings


def require_api_key(x_api_key: str | None = Header(default=None)) -> str:
    """Partner authentication. Each PSP/bank integration gets its own key; the key id is the audit actor."""
    if x_api_key:
        for k in get_settings().api_key_set:
            if hmac.compare_digest(k, x_api_key):
                return f"key:{k[:4]}…"
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid X-API-Key")
