"""Общее для веб-страниц: шаблоны, меню, форматирование, рендеринг."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.models import User
from app.permissions import ROLE_LABELS, Permission, Role, has_permission
from app.timeutil import to_local

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

LABELS = {
    "fact": "Факт",
    "budget": "Бюджет",
    "excel": "Файл",
    "manual": "Ручной ввод",
    "seed": "Демо-данные",
    "preview": "Черновик",
    "pending_mapping": "Ожидает сопоставления",
    "active": "Записана",
    "superseded": "Заменена",
    "cancelled": "Отменена",
    "day": "день",
    "month": "месяц",
    "quarter": "квартал",
    "year": "год",
    "increase": "Рост",
    "decrease": "Снижение",
    "new": "Новая",
    "removed": "Исчезнувшая",
    "no_change": "Без изменений",
    "comparison": "Сравнение периодов",
    "plan_fact": "План-факт",
}


@dataclass(frozen=True)
class NavItem:
    title: str
    url: str
    permission: Permission | None = None


# Пункты меню; каждый виден только при наличии права
NAV_ITEMS: list[NavItem] = [
    NavItem("Анализ расходов", "/web/dashboard", Permission.ANALYTICS_VIEW),
    NavItem("Сохранённые анализы", "/web/analyses", Permission.ANALYTICS_VIEW),
    NavItem("Ввод данных", "/web/data", Permission.DATA_MANUAL),
    NavItem("Загрузки", "/web/uploads", Permission.ANALYTICS_VIEW),
    NavItem("Справочники", "/web/reference", Permission.REFERENCE_MANAGE),
    NavItem("Настройки", "/web/settings", Permission.SETTINGS_MANAGE),
    NavItem("Пользователи", "/web/users", Permission.USERS_MANAGE),
    NavItem("Журнал", "/web/audit", Permission.AUDIT_VIEW),
]


def can(user: User | None, permission: Permission | str) -> bool:
    return user is not None and has_permission(user.role, Permission(permission))


def nav_for(user: User | None) -> list[NavItem]:
    if user is None:
        return []
    return [i for i in NAV_ITEMS if i.permission is None or can(user, i.permission)]


def format_money(value) -> str:
    """1234567.5 → «1 234 567,50» (неразрывные пробелы)."""
    if value is None:
        return "—"
    text = f"{Decimal(str(value)):,.2f}"
    return text.replace(",", " ").replace(".", ",")


def format_pct(value) -> str:
    if value is None:
        return "н/д"
    return f"{Decimal(str(value)):+.1f}".replace(".", ",") + " %"


def format_date(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    if isinstance(value, datetime):
        return to_local(value).strftime("%d.%m.%Y %H:%M")
    return value.strftime("%d.%m.%Y")


templates.env.globals.update(can=can, nav_for=nav_for, Permission=Permission)
templates.env.filters.update(
    role_label=lambda role: ROLE_LABELS.get(Role(role), role),
    label=lambda code: LABELS.get(code, code),
    money=format_money,
    pct=format_pct,
    ru_date=format_date,
)


def render(
    request: Request,
    template: str,
    context: dict | None = None,
    user: User | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    ctx = {
        "user": user,
        "csrf_token": request.state.csrf_token,
        "app_name": get_settings().app_name,
        **(context or {}),
    }
    return templates.TemplateResponse(request, template, ctx, status_code=status_code)
