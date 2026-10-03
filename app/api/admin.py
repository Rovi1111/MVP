"""Настройки организации и шаблоны промптов."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import csrf_protect, require
from app.models import User
from app.permissions import Permission
from app.repositories.audit import AuditRepository
from app.schemas import (
    AuditOut,
    PromptTemplateCreate,
    PromptTemplateOut,
    PromptTemplateUpdate,
    SettingsOut,
    SettingsUpdate,
)
from app.services import ollama, prompts
from app.services import settings as settings_service
from app.services.ai_summary import PLACEHOLDERS

router = APIRouter(tags=["settings"], dependencies=[Depends(csrf_protect)])
_admin = require(Permission.SETTINGS_MANAGE)


def _settings_out(values: settings_service.OrgSettings) -> SettingsOut:
    data = {k: v for k, v in vars(values).items() if k != "smtp_password"}
    return SettingsOut(**data, smtp_configured=values.smtp_configured)


@router.get("/settings", response_model=SettingsOut)
def get_settings(user: User = Depends(_admin), db: Session = Depends(get_db)):
    return _settings_out(settings_service.get_org_settings(db, user.org_id))


@router.patch("/settings", response_model=SettingsOut)
def update_settings(
    data: SettingsUpdate, user: User = Depends(_admin), db: Session = Depends(get_db)
):
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    return _settings_out(settings_service.update_org_settings(db, user, changes))


@router.post("/settings/ollama/check")
def check_ollama(user: User = Depends(_admin), db: Session = Depends(get_db)):
    """Проверяет доступность Ollama и наличие модели. 503 с пояснением — если нет."""
    message = ollama.check_connection(settings_service.get_org_settings(db, user.org_id))
    return {"detail": message}


@router.get("/prompt-templates", response_model=list[PromptTemplateOut])
def list_templates(user: User = Depends(require(Permission.AI_RUN)), db: Session = Depends(get_db)):
    """Шаблоны для выбора при запуске AI-анализа."""
    return prompts.list_templates(db, user.org_id)


@router.get("/prompt-templates/placeholders")
def placeholders(user: User = Depends(_admin)) -> dict[str, str]:
    return PLACEHOLDERS


@router.post(
    "/prompt-templates", response_model=PromptTemplateOut, status_code=status.HTTP_201_CREATED
)
def create_template(
    data: PromptTemplateCreate, user: User = Depends(_admin), db: Session = Depends(get_db)
):
    return prompts.create_template(db, user, data.name, data.text, data.scenario)


@router.patch("/prompt-templates/{template_id}", response_model=PromptTemplateOut)
def update_template(
    template_id: int,
    data: PromptTemplateUpdate,
    user: User = Depends(_admin),
    db: Session = Depends(get_db),
):
    return prompts.update_template(db, user, template_id, **data.model_dump(exclude_unset=True))


@router.delete("/prompt-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: int, user: User = Depends(_admin), db: Session = Depends(get_db)):
    prompts.delete_template(db, user, template_id)


@router.get("/audit", response_model=list[AuditOut])
def audit_log(
    action: str | None = None,
    limit: int = 200,
    offset: int = 0,
    user: User = Depends(require(Permission.AUDIT_VIEW)),
    db: Session = Depends(get_db),
):
    """Журнал действий, от новых к старым."""
    return AuditRepository(db, user.org_id).recent(min(limit, 1000), offset, action)
