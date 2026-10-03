import hmac
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Account, AuthSession
from app.security import token_hash


def require_api_key(x_api_key: str | None = Header(default=None)) -> str:
    """Partner authentication (real-time risk API). Each PSP/bank integration gets its own key."""
    if x_api_key:
        for k in get_settings().api_key_set:
            if hmac.compare_digest(k, x_api_key):
                return f"key:{k[:4]}…"
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid X-API-Key")


def current_account(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> Account:
    """Signed-in person. Bearer token → session row (stored hashed) → account."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Please sign in.")
    th = token_hash(authorization.split(" ", 1)[1].strip())
    s = db.scalar(select(AuthSession).where(AuthSession.token_hash == th))
    now = datetime.now(timezone.utc)
    if s is None or s.revoked_at is not None or s.expires_at < now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Your session has ended. Please sign in again.")
    acc = db.get(Account, s.account_id)
    if acc is None or not acc.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Account disabled.")
    return acc


def roles(*allowed: str):
    def dep(acc: Account = Depends(current_account)) -> Account:
        if acc.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Your role does not have access to this.")
        return acc
    return dep


@dataclass
class Actor:
    """For audit lines."""
    name: str
    id: str | None
    role: str
