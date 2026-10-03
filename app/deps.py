"""FastAPI-зависимости: текущий пользователь, проверка прав, CSRF."""

from collections.abc import Callable
from hmac import compare_digest

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.permissions import Permission, has_permission
from app.security import is_valid_csrf_token, password_fingerprint, read_session_token

SESSION_COOKIE = "session"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
CSRF_FIELD = "csrf_token"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def find_current_user(request: Request, db: Session) -> User | None:
    """Пользователь по сессионной cookie или None, если сессия недействительна.

    Сессия недействительна, если cookie нет или подделана, пользователь удалён или отключён
    либо его пароль сменился после входа.
    """
    session = read_session_token(request.cookies.get(SESSION_COOKIE))
    user = db.get(User, session[0]) if session else None
    if (
        user is None
        or not user.is_active
        or not compare_digest(session[1], password_fingerprint(user.password_hash))
    ):
        return None
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = find_current_user(request, db)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход в систему")
    return user


def require(permission: Permission) -> Callable[..., User]:
    """Зависимость: пользователь с указанным правом, иначе 403."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user.role, permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав для этого действия")
        return user

    return checker


async def csrf_protect(request: Request) -> None:
    """Double-submit: токен из cookie должен совпасть с заголовком или полем формы."""
    if request.method in _SAFE_METHODS:
        return
    cookie = request.cookies.get(CSRF_COOKIE)
    sent = request.headers.get(CSRF_HEADER)
    if not sent:
        content_type = request.headers.get("content-type", "")
        if content_type.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
            sent = (await request.form()).get(CSRF_FIELD)
    if not (is_valid_csrf_token(cookie) and isinstance(sent, str) and compare_digest(cookie, sent)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF-токен отсутствует или неверен")
