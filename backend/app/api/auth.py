"""Sign-in. The role comes from the account record — a person cannot pick a role at login."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_account
from app.config import get_settings
from app.db import get_db
from app.models import Account, AuthorityProfile, AuthSession, BankProfile, Role, VictimProfile
from app.security import new_token, token_hash, verify_password
from app.services import accounts as acc_svc
from app.services.audit import audit

router = APIRouter(prefix="/api/v1", tags=["Authentication"])


class LoginIn(BaseModel):
    login: str = Field(..., min_length=2, max_length=160, description="Email or user ID (e.g. V102)")
    password: str = Field(..., min_length=1, max_length=200)


class ProfileIn(BaseModel):
    phone: str | None = Field(None, max_length=20)
    bank_name: str | None = Field(None, max_length=80)
    own_vpa: str | None = Field(None, max_length=120)
    city: str | None = Field(None, max_length=80)
    preferred_language: str | None = Field(None, max_length=20)


def me_out(db: Session, a: Account) -> dict:
    role = db.get(Role, a.role)
    prof = None
    if a.role == "VICTIM":
        p = db.get(VictimProfile, a.id)
        prof = p and {"phone": p.phone, "bank_name": p.bank_name, "own_vpa": p.own_vpa, "city": p.city,
                      "preferred_language": p.preferred_language}
    elif a.role == "BANK":
        p = db.get(BankProfile, a.id)
        prof = p and {"bank_name": p.bank_name, "branch": p.branch, "employee_id": p.employee_id, "designation": p.designation}
    elif a.role == "CYBER":
        p = db.get(AuthorityProfile, a.id)
        prof = p and {"unit": p.unit, "jurisdiction": p.jurisdiction, "badge_no": p.badge_no, "designation": p.designation}
    return {"id": a.id, "email": a.email, "user_code": a.user_code, "name": a.name, "role": a.role,
            "role_label": role.label if role else a.role, "permissions": role.permissions if role else [],
            "org": a.org, "is_demo": a.is_demo, "profile": prof}


@router.post("/auth/login")
def login(req: LoginIn, db: Session = Depends(get_db)):
    key = req.login.strip().lower()
    a = db.scalar(select(Account).where((Account.email == key) | (Account.user_code == req.login.strip().upper())))
    if a is None or a.is_synthetic or not a.is_active or not verify_password(req.password, a.password_hash):
        audit(db, "LOGIN_FAILED", key[:80], source="auth", result="invalid credentials")
        db.commit()
        raise HTTPException(401, "Incorrect email / user ID or password.")
    token = new_token()
    now = datetime.now(timezone.utc)
    db.add(AuthSession(account_id=a.id, token_hash=token_hash(token),
                       expires_at=now + timedelta(hours=get_settings().session_hours)))
    a.last_login_at = now
    audit(db, "LOGIN", a.name, source="auth", actor_id=a.id, actor_role=a.role)
    db.commit()
    return {"token": token, "account": me_out(db, a)}


@router.post("/auth/logout", status_code=204)
def logout(authorization: str | None = Header(default=None), db: Session = Depends(get_db),
           a: Account = Depends(current_account)):
    s = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(authorization.split(" ", 1)[1].strip())))
    if s:
        s.revoked_at = datetime.now(timezone.utc)
    db.commit()


@router.get("/auth/me")
def me(db: Session = Depends(get_db), a: Account = Depends(current_account)):
    return me_out(db, a)


@router.patch("/auth/me/profile")
def update_profile(req: ProfileIn, db: Session = Depends(get_db), a: Account = Depends(current_account)):
    if a.role != "VICTIM":
        raise HTTPException(403, "Staff profiles are managed by the organisation.")
    p = db.get(VictimProfile, a.id) or VictimProfile(account_id=a.id)
    for k, v in req.model_dump(exclude_unset=True).items():
        setattr(p, k, (v or "").strip() or None)
    db.add(p)
    db.commit()
    return me_out(db, a)


@router.get("/auth/demo-accounts", summary="Demo sign-in details (only in dev/demo deployments)")
def demo_accounts():
    if not get_settings().show_demo_accounts:
        return []
    return [{"label": {"VICTIM": "Victim demo", "BANK": "Bank investigator demo", "CYBER": "Cyber crime officer demo"}[role]
             + (" (second account)" if code in ("V103", "B202") else ""),
             "email": email, "password": pw, "role": role, "name": name, "org": org}
            for email, pw, name, code, role, org, _ in acc_svc.DEMO_ACCOUNTS]


@router.get("/banks", summary="Banks with investigators on the platform (where a case can be sent)")
def banks(db: Session = Depends(get_db), _: Account = Depends(current_account)):
    return acc_svc.onboarded_banks(db)
