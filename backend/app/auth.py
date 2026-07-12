"""Authentication & authorization: JWT + roles (admin / analyst / viewer).

Uses passlib(bcrypt) + python-jose when available, with pure-stdlib fallbacks
(pbkdf2 + HMAC-signed tokens) so auth keeps working even if those optional deps
are missing. Read endpoints are open; write/admin endpoints require a role.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User

ROLES = {"admin": 3, "analyst": 2, "viewer": 1}


# --------------------------- password hashing ------------------------------ #
def hash_password(password: str) -> str:
    try:
        from passlib.hash import bcrypt

        return "bcrypt$" + bcrypt.hash(password)
    except Exception:
        salt = hashlib.sha256(settings.jwt_secret.encode()).hexdigest()[:16]
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
        return "pbkdf2$" + salt + "$" + dk.hex()


def verify_password(password: str, hashed: str) -> bool:
    try:
        if hashed.startswith("bcrypt$"):
            from passlib.hash import bcrypt

            return bcrypt.verify(password, hashed[len("bcrypt$"):])
        if hashed.startswith("pbkdf2$"):
            _, salt, digest = hashed.split("$", 2)
            dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
            return hmac.compare_digest(dk.hex(), digest)
    except Exception:
        return False
    return False


# --------------------------- token encode/decode --------------------------- #
def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def create_token(user: User) -> str:
    exp = int(time.time()) + settings.jwt_expire_minutes * 60
    payload = {"sub": user.email, "uid": user.id, "role": user.role, "exp": exp}
    try:
        from jose import jwt

        return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    except Exception:
        body = _b64e(json.dumps(payload).encode())
        sig = _b64e(hmac.new(settings.jwt_secret.encode(), body.encode(), hashlib.sha256).digest())
        return f"{body}.{sig}"


def decode_token(token: str) -> Optional[dict]:
    try:
        from jose import jwt

        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except Exception:
        pass
    # stdlib fallback
    try:
        body, sig = token.split(".")
        expected = _b64e(hmac.new(settings.jwt_secret.encode(), body.encode(),
                                  hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64d(body))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


# --------------------------- user operations ------------------------------- #
def create_user(db: Session, email: str, password: str, full_name: str = "",
                role: str = "analyst") -> User:
    if role not in ROLES:
        role = "analyst"
    user = User(email=email.lower().strip(), full_name=full_name,
                hashed_password=hash_password(password), role=role, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.email == email.lower().strip()).first()
    if not user or not user.is_active or not verify_password(password, user.hashed_password):
        return None
    # last_login is best-effort — never block sign-in on SQLite write contention
    # (concurrent ingest/recompute can hold the write lock for tens of seconds).
    try:
        user.last_login = datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()
        user = db.query(User).filter(User.email == email.lower().strip()).first()
    return user


def seed_admin(db: Session) -> None:
    """Ensure demo login accounts exist (admin + analyst + viewer).

    Admin uses SEED_ADMIN_* from env. Analyst/viewer are fixed demo accounts
    documented in the README — created if missing so docs match reality.
    """
    if not db.query(User).filter(User.email == settings.seed_admin_email.lower()).first():
        create_user(db, settings.seed_admin_email, settings.seed_admin_password,
                    full_name="VigilAI Admin", role="admin")
    demo_users = [
        ("analyst@vigilai.dev", "analyst123", "analyst", "VigilAI Analyst"),
        ("viewer@vigilai.dev", "viewer123", "viewer", "VigilAI Viewer"),
    ]
    for email, password, role, full_name in demo_users:
        if not db.query(User).filter(User.email == email).first():
            create_user(db, email, password, full_name=full_name, role=role)


def user_to_dict(u: User) -> dict:
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role,
            "is_active": u.is_active,
            "last_login": u.last_login.isoformat() if u.last_login else None}


# --------------------------- FastAPI dependencies -------------------------- #
def get_current_user(authorization: str = Header(default=""),
                     db: Session = Depends(get_db)) -> Optional[User]:
    """Return the authenticated user or None (does not force auth)."""
    if not authorization.lower().startswith("bearer "):
        return None
    payload = decode_token(authorization[7:])
    if not payload:
        return None
    return db.get(User, payload.get("uid"))


def require_role(min_role: str = "viewer"):
    threshold = ROLES.get(min_role, 1)

    def _dep(user: Optional[User] = Depends(get_current_user)) -> User:
        if user is None:
            raise HTTPException(401, "authentication required")
        if ROLES.get(user.role, 0) < threshold:
            raise HTTPException(403, f"requires {min_role} role")
        return user

    return _dep
