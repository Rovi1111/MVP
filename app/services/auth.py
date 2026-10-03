"""Вход и выход: общая логика для API и веб-страниц."""

from fastapi import Response
from sqlalchemy.orm import Session

from app.auth import get_auth_provider
from app.config import get_settings
from app.deps import SESSION_COOKIE
from app.models import User
from app.security import create_session_token
from app.services.audit import log_action


def login(db: Session, login: str, password: str) -> User | None:
    user = get_auth_provider().authenticate(db, login, password)
    if user is not None:
        log_action(db, user, "login", "session")
        db.commit()
    return user


def logout(db: Session, user: User) -> None:
    log_action(db, user, "logout", "session")
    db.commit()


def set_session_cookie(response: Response, user: User) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user.id, user.password_hash),
        max_age=settings.session_max_age,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE)
