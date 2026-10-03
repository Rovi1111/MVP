"""Роли и матрица прав. Единственное место, где описано, кому что разрешено."""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    MANAGER = "manager"
    EMPLOYEE = "employee"


ROLE_LABELS: dict[Role, str] = {
    Role.ADMIN: "Администратор",
    Role.MANAGER: "Руководитель",
    Role.EMPLOYEE: "Базовый сотрудник",
}


class Permission(StrEnum):
    USERS_MANAGE = "users:manage"  # пользователи и роли
    DATA_UPLOAD = "data:upload"  # загрузка факта/бюджета из файла
    DATA_MANUAL = "data:manual"  # ручной ввод (форма/JSON)
    REFERENCE_MANAGE = "reference:manage"  # категории, ЦФО, сопоставление статей
    ANALYTICS_VIEW = "analytics:view"  # сравнение, план-факт, дашборд
    AI_RUN = "ai:run"  # запуск AI-анализа
    REPORTS = "reports:use"  # отчёты: просмотр, экспорт, email
    SETTINGS_MANAGE = "settings:manage"  # настройки Ollama, шаблоны промптов
    AUDIT_VIEW = "audit:view"  # журнал действий


_ALL = frozenset(Permission)

MATRIX: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: _ALL,
    # SPEC, раздел 14, п. 2: руководитель может всё
    Role.MANAGER: _ALL,
    Role.EMPLOYEE: frozenset(
        {
            Permission.DATA_UPLOAD,
            Permission.DATA_MANUAL,
            Permission.ANALYTICS_VIEW,
            Permission.AI_RUN,
            Permission.REPORTS,
        }
    ),
}


def has_permission(role: Role | str, permission: Permission) -> bool:
    try:
        return permission in MATRIX[Role(role)]
    except ValueError:
        return False
