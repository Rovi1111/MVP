"""Управление пользователями организации."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ConflictError, InvalidDataError, NotFoundError
from app.models import Organization, User
from app.permissions import Role
from app.repositories.users import UserRepository
from app.security import MIN_PASSWORD_LENGTH, hash_password
from app.services import prompts
from app.services.audit import log_action


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise InvalidDataError(f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")


def _check_role(role: str) -> str:
    try:
        return Role(role).value
    except ValueError:
        raise InvalidDataError(f"Неизвестная роль: {role}") from None


def build_user(
    db: Session, org_id: int, login: str, password: str, role: str, full_name: str = ""
) -> User:
    """Создаёт пользователя без записи в аудит (используется также CLI и seed)."""
    login = login.strip()
    if not login:
        raise InvalidDataError("Логин не может быть пустым")
    _check_password(password)
    repo = UserRepository(db, org_id)
    if repo.login_exists(login):
        raise ConflictError(f"Логин «{login}» уже занят")
    return repo.add(
        User(
            login=login,
            full_name=full_name.strip(),
            password_hash=hash_password(password),
            role=_check_role(role),
        )
    )


def create_user(
    db: Session, actor: User, login: str, password: str, role: str, full_name: str = ""
) -> User:
    user = build_user(db, actor.org_id, login, password, role, full_name)
    log_action(db, actor, "create", "user", user.id, {"login": user.login, "role": user.role})
    db.commit()
    return user


def update_user(
    db: Session,
    actor: User,
    user_id: int,
    *,
    full_name: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    password: str | None = None,
) -> User:
    user = UserRepository(db, actor.org_id).get(user_id)
    if user is None:
        raise NotFoundError("Пользователь не найден")

    changes: dict = {}
    if full_name is not None and full_name.strip() != user.full_name:
        user.full_name = changes["full_name"] = full_name.strip()
    if role is not None and _check_role(role) != user.role:
        if user.id == actor.id:
            raise ConflictError("Нельзя изменить собственную роль")
        user.role = changes["role"] = _check_role(role)
    if is_active is not None and is_active != user.is_active:
        if user.id == actor.id:
            raise ConflictError("Нельзя отключить собственную учётную запись")
        user.is_active = changes["is_active"] = is_active
    if password:
        _check_password(password)
        user.password_hash = hash_password(password)
        changes["password"] = "изменён"

    if changes:
        log_action(db, actor, "update", "user", user.id, changes)
    db.commit()
    return user


def create_admin(
    db: Session, org_name: str, login: str, password: str, full_name: str = ""
) -> User:
    """Создаёт администратора; организация создаётся, если её ещё нет (для CLI)."""
    org_name = org_name.strip()
    if not org_name:
        raise InvalidDataError("Название организации не может быть пустым")
    org = db.scalar(select(Organization).where(Organization.name == org_name))
    if org is None:
        org = Organization(name=org_name)
        db.add(org)
        db.flush()
    user = build_user(db, org.id, login, password, Role.ADMIN, full_name)
    prompts.ensure_defaults(db, org.id)
    db.commit()
    return user
