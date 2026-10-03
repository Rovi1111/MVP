"""Провайдеры аутентификации.

Чтобы добавить вход через Active Directory/LDAP, реализуйте AuthProvider
(проверка пароля во внешнем каталоге + поиск/создание локального User),
зарегистрируйте класс в PROVIDERS и задайте AUTH_PROVIDER в .env.
"""

from abc import ABC, abstractmethod

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User
from app.security import verify_password


class AuthProvider(ABC):
    @abstractmethod
    def authenticate(self, db: Session, login: str, password: str) -> User | None:
        """Возвращает активного пользователя или None, если вход невозможен."""


class LocalAuthProvider(AuthProvider):
    """Собственные логины и пароли, хеши в таблице users."""

    def authenticate(self, db: Session, login: str, password: str) -> User | None:
        user = db.scalar(select(User).where(User.login == login.strip()))
        password_ok = verify_password(user.password_hash if user else None, password)
        if user is None or not password_ok or not user.is_active:
            return None
        return user


PROVIDERS: dict[str, type[AuthProvider]] = {"local": LocalAuthProvider}


def get_auth_provider() -> AuthProvider:
    name = get_settings().auth_provider
    try:
        return PROVIDERS[name]()
    except KeyError:
        raise RuntimeError(f"Неизвестный AUTH_PROVIDER: {name}") from None
