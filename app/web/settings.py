"""Настройки: Ollama, порог план-факта, SMTP, шаблоны промптов."""

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require
from app.errors import AppError
from app.models import User
from app.permissions import Permission
from app.services import ollama, prompts
from app.services import settings as settings_service
from app.services.ai_summary import PLACEHOLDERS
from app.web.common import render

router = APIRouter(prefix="/settings")
_admin = require(Permission.SETTINGS_MANAGE)
_FIELDS = (
    "ollama_url", "ollama_model", "ollama_timeout", "plan_fact_threshold",
    "smtp_host", "smtp_port", "smtp_user", "smtp_from",
)  # fmt: skip
_CHECKBOXES = ("ai_auto_run", "smtp_tls")


def _templates(request: Request, db: Session, user: User):
    context = {"templates": prompts.list_templates(db, user.org_id), "placeholders": PLACEHOLDERS}
    return render(request, "partials/prompt_templates.html", context, user)


@router.get("")
def settings_page(request: Request, user: User = Depends(_admin), db: Session = Depends(get_db)):
    context = {
        "settings": settings_service.get_org_settings(db, user.org_id),
        "templates": prompts.list_templates(db, user.org_id),
        "placeholders": PLACEHOLDERS,
    }
    return render(request, "settings.html", context, user)


@router.post("")
async def save_settings(
    request: Request, user: User = Depends(_admin), db: Session = Depends(get_db)
):
    form = await request.form()
    changes = {name: form.get(name, "") for name in _FIELDS if name in form}
    changes |= {name: name in form for name in _CHECKBOXES}
    if form.get("smtp_password"):  # пустое поле — пароль не меняем
        changes["smtp_password"] = form["smtp_password"]
    try:
        settings_service.update_org_settings(db, user, changes)
    except AppError as exc:
        return render(request, "partials/alert.html", {"message": exc.message}, user)
    context = {"message": "Настройки сохранены", "kind": "ok"}
    return render(request, "partials/alert.html", context, user)


@router.post("/ollama-check")
def ollama_check(request: Request, user: User = Depends(_admin), db: Session = Depends(get_db)):
    try:
        message = ollama.check_connection(settings_service.get_org_settings(db, user.org_id))
    except AppError as exc:
        return render(request, "partials/alert.html", {"message": exc.message}, user)
    return render(request, "partials/alert.html", {"message": message, "kind": "ok"}, user)


@router.post("/templates")
def create_template(
    request: Request,
    name: str = Form(""),
    text: str = Form(""),
    user: User = Depends(_admin),
    db: Session = Depends(get_db),
):
    prompts.create_template(db, user, name, text)
    return _templates(request, db, user)


@router.post("/templates/{template_id}")
def update_template(
    request: Request,
    template_id: int,
    name: str = Form(""),
    text: str = Form(""),
    is_active: bool = Form(False),
    user: User = Depends(_admin),
    db: Session = Depends(get_db),
):
    prompts.update_template(db, user, template_id, name=name, text=text, is_active=is_active)
    return _templates(request, db, user)


@router.post("/templates/{template_id}/delete")
def delete_template(
    request: Request, template_id: int, user: User = Depends(_admin), db: Session = Depends(get_db)
):
    prompts.delete_template(db, user, template_id)
    return _templates(request, db, user)
