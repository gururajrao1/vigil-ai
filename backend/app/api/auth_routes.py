"""Authentication + user-management API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import (
    authenticate,
    create_token,
    create_user,
    get_current_user,
    require_role,
    user_to_dict,
)
from ..database import get_db
from ..models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterReq(BaseModel):
    email: str
    password: str
    full_name: str = ""
    role: str = "analyst"


class LoginReq(BaseModel):
    email: str
    password: str


@router.post("/register")
def register(req: RegisterReq, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == req.email.lower().strip()).first():
        raise HTTPException(400, "email already registered")
    # First user becomes admin; subsequent public registrations are viewers.
    role = "admin" if db.query(User).count() == 0 else "viewer"
    user = create_user(db, req.email, req.password, req.full_name, role)
    return {"token": create_token(user), "user": user_to_dict(user)}


@router.post("/login")
def login(req: LoginReq, db: Session = Depends(get_db)):
    user = authenticate(db, req.email, req.password)
    if not user:
        raise HTTPException(401, "invalid credentials")
    return {"token": create_token(user), "user": user_to_dict(user)}


@router.get("/me")
def me(user: User | None = Depends(get_current_user)):
    if not user:
        raise HTTPException(401, "not authenticated")
    return user_to_dict(user)


# ------------------------------- admin: users ------------------------------ #
@router.get("/users")
def list_users(db: Session = Depends(get_db), _admin=Depends(require_role("admin"))):
    return {"users": [user_to_dict(u) for u in db.query(User).all()]}


class NewUserReq(BaseModel):
    email: str
    password: str
    full_name: str = ""
    role: str = "analyst"


@router.post("/users")
def add_user(req: NewUserReq, db: Session = Depends(get_db),
             _admin=Depends(require_role("admin"))):
    from ..auth import ROLES
    if req.role not in ROLES:
        raise HTTPException(400, f"role must be one of: {', '.join(sorted(ROLES))}")
    if db.query(User).filter(User.email == req.email.lower().strip()).first():
        raise HTTPException(400, "email already registered")
    user = create_user(db, req.email, req.password, req.full_name, req.role)
    return user_to_dict(user)


class RoleReq(BaseModel):
    role: str


@router.patch("/users/{user_id}/role")
def set_role(user_id: int, req: RoleReq, db: Session = Depends(get_db),
             _admin=Depends(require_role("admin"))):
    from ..auth import ROLES
    if req.role not in ROLES:
        raise HTTPException(400, f"role must be one of: {', '.join(sorted(ROLES))}")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "user not found")
    user.role = req.role
    db.commit()
    return user_to_dict(user)
