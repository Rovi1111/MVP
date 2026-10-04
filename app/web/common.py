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
from app.services.markdown import render_markdown
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
    "dynamics": "Динамика расходов",
    "step_day": "день",
    "step_month": "месяц",
    "step_quarter": "квартал",
    "step_year": "год",
}


@dataclass(frozen=True)
class NavItem:
    title: str
    url: str
    permission: Permission | None = None
    icon: str = ""  # содержимое SVG-иконки 24×24 (контурный стиль)


_ICONS = {
    "chart": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    "bookmark": '<path d="M6 3h12v18l-6-4-6 4z"/>',
    "upload": '<path d="M12 16V4M7 9l5-5 5 5M4 20h16"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    "book": '<path d="M4 5a2 2 0 0 1 2-2h14v16H6a2 2 0 0 0-2 2zM4 21V5M9 8h7"/>',
    "sliders": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4"/>',
    "users": (
        '<path d="M16 20v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8'
        'M22 20v-1a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/>'
    ),
    "clock": '<path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18M12 7v5l3 2"/>',
}


# Пункты меню; каждый виден только при наличии права
NAV_ITEMS: list[NavItem] = [
    NavItem("Анализ расходов", "/web/dashboard", Permission.ANALYTICS_VIEW, _ICONS["chart"]),
    NavItem("Сохранённые анализы", "/web/analyses", Permission.ANALYTICS_VIEW, _ICONS["bookmark"]),
    NavItem("Ввод данных", "/web/data", Permission.DATA_MANUAL, _ICONS["upload"]),
    NavItem("Загрузки", "/web/uploads", Permission.ANALYTICS_VIEW, _ICONS["list"]),
    NavItem("Справочники", "/web/reference", Permission.REFERENCE_MANAGE, _ICONS["book"]),
    NavItem("Настройки", "/web/settings", Permission.SETTINGS_MANAGE, _ICONS["sliders"]),
    NavItem("Пользователи", "/web/users", Permission.USERS_MANAGE, _ICONS["users"]),
    NavItem("Журнал", "/web/audit", Permission.AUDIT_VIEW, _ICONS["clock"]),
]


def can(user: User | None, permission: Permission | str) -> bool:
    return user is not None and has_permission(user.role, Permission(permission))


def nav_for(user: User | None) -> list[NavItem]:
    if user is None:
        return []
    return [i for i in NAV_ITEMS if i.permission is None or can(user, i.permission)]


def asset(name: str) -> str:
    """Адрес статического файла с меткой времени изменения — чтобы браузер
    не показывал устаревшие стили и скрипты из кэша после обновления сервиса."""
    path = BASE_DIR / "static" / name
    version = int(path.stat().st_mtime) if path.exists() else 0
    return f"/static/{name}?v={version}"


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


templates.env.globals.update(can=can, nav_for=nav_for, Permission=Permission, asset=asset)
templates.env.filters.update(
    role_label=lambda role: ROLE_LABELS.get(Role(role), role),
    label=lambda code: LABELS.get(code, code),
    money=format_money,
    pct=format_pct,
    ru_date=format_date,
    md=render_markdown,
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
