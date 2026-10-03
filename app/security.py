"""Пароли, подписанные сессионные cookie и CSRF-токены."""

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from itsdangerous import BadSignature, URLSafeSerializer, URLSafeTimedSerializer

from app.config import get_settings

_hasher = PasswordHasher()
# Хеш для сравнения, когда пользователя нет: время ответа не выдаёт существование логина
_DUMMY_HASH = _hasher.hash("dummy-password")

MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and bool(password_hash)
    except (VerificationError, InvalidHashError):
        return False


def _session_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="session")


def password_fingerprint(password_hash: str) -> str:
    """Отпечаток хеша пароля: при смене пароля все прежние сессии перестают действовать."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def create_session_token(user_id: int, password_hash: str) -> str:
    payload = {"uid": user_id, "fp": password_fingerprint(password_hash)}
    return _session_serializer().dumps(payload)


def read_session_token(token: str | None) -> tuple[int, str] | None:
    """Возвращает (id пользователя, отпечаток пароля) или None, если cookie нет,
    она подделана или устарела."""
    if not token:
        return None
    try:
        data = _session_serializer().loads(token, max_age=get_settings().session_max_age)
    except BadSignature:
        return None
    if not isinstance(data, dict) or "uid" not in data or "fp" not in data:
        return None
    return data["uid"], data["fp"]


def _csrf_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().secret_key, salt="csrf")


def new_csrf_token() -> str:
    return _csrf_serializer().dumps(secrets.token_urlsafe(16))


def is_valid_csrf_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        _csrf_serializer().loads(token)
    except BadSignature:
        return False
    return True
