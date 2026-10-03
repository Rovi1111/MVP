"""Администрирование: пользователи и журнал действий."""

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require
from app.models import User
from app.permissions import ROLE_LABELS, Permission
from app.repositories.audit import AuditRepository
from app.repositories.users import UserRepository
from app.services import users as users_service
from app.web.common import render

router = APIRouter()
_users = require(Permission.USERS_MANAGE)
PAGE_SIZE = 100
ACTION_LABELS = {
    "login": "Вход",
    "logout": "Выход",
    "create": "Создание",
    "update": "Изменение",
    "delete": "Удаление",
    "export": "Экспорт",
    "email": "Отправка на email",
    "ai_analysis": "AI-анализ",
    "ai_analysis_failed": "AI-анализ: ошибка",
}
ENTITY_LABELS = {
    "session": "сеанс",
    "user": "пользователь",
    "category": "категория",
    "cost_center": "ЦФО",
    "category_alias": "сопоставление статьи",
    "upload": "загрузка",
    "analysis": "анализ",
    "chart": "диаграмма",
    "settings": "настройки",
    "prompt_template": "шаблон промпта",
}


def _users_section(request: Request, db: Session, actor: User):
    context = {"users": UserRepository(db, actor.org_id).list(), "roles": ROLE_LABELS}
    return render(request, "partials/users.html", context, actor)


@router.get("/users")
def users_page(request: Request, actor: User = Depends(_users), db: Session = Depends(get_db)):
    context = {"users": UserRepository(db, actor.org_id).list(), "roles": ROLE_LABELS}
    return render(request, "users.html", context, actor)


@router.post("/users")
def create_user(
    request: Request,
    login: str = Form(""),
    full_name: str = Form(""),
    password: str = Form(""),
    role: str = Form(""),
    actor: User = Depends(_users),
    db: Session = Depends(get_db),
):
    users_service.create_user(db, actor, login, password, role, full_name)
    return _users_section(request, db, actor)


@router.post("/users/{user_id}")
def update_user(
    request: Request,
    user_id: int,
    full_name: str = Form(""),
    role: str = Form(""),
    is_active: bool = Form(False),
    password: str = Form(""),
    actor: User = Depends(_users),
    db: Session = Depends(get_db),
):
    users_service.update_user(
        db,
        actor,
        user_id,
        full_name=full_name,
        role=role,
        is_active=is_active,
        password=password or None,
    )
    return _users_section(request, db, actor)


@router.get("/audit")
def audit_page(
    request: Request,
    action: str = "",
    page: int = 1,
    actor: User = Depends(require(Permission.AUDIT_VIEW)),
    db: Session = Depends(get_db),
):
    repo = AuditRepository(db, actor.org_id)
    page = max(page, 1)
    entries = repo.recent(PAGE_SIZE + 1, (page - 1) * PAGE_SIZE, action or None)
    context = {
        "entries": entries[:PAGE_SIZE],
        "has_next": len(entries) > PAGE_SIZE,
        "page": page,
        "action": action,
        "actions": repo.actions(),
        "action_labels": ACTION_LABELS,
        "entity_labels": ENTITY_LABELS,
    }
    return render(request, "audit.html", context, actor)
