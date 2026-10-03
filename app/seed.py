"""Демо-данные: организация с обычными статьями расходов, факт за два квартала 2025 года и бюджет.

Запуск: python -m app.cli seed
Данные проходят тот же путь, что и загрузка файла (валидация, сопоставление, версии).
В данных есть все типы изменений между 1 и 2 кварталом
(рост, снижение, новая, исчезнувшая, без изменений) и перерасходы бюджета.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.datasources import DataSource, RawRow
from app.models import Organization, User
from app.permissions import Role
from app.services import imports, prompts
from app.services.users import build_user

# Пароль демо-пользователей (только для локального знакомства с системой)
DEFAULT_PASSWORD = "demo-2025-expenses"
YEAR = 2025
MONTHS = range(1, 7)
# Платежи внутри месяца: (день, доля суммы) — чтобы была осмысленной детализация по дням
PAYMENT_DAYS = ((5, 0.5), (15, 0.3), (25, 0.2))


@dataclass(frozen=True)
class DemoOrg:
    name: str
    prefix: str  # логины: <prefix>_admin, <prefix>_manager, <prefix>_employee
    cost_centers: tuple[tuple[str, float], ...]  # (ЦФО, доля расходов)
    fact: dict[str, tuple[int, ...]]  # категория → суммы по месяцам (январь–июнь)
    budget: dict[str, tuple[int, ...]]


DEMO_ORGS = [
    DemoOrg(
        name="Демо-компания",
        prefix="demo",
        cost_centers=(("Офис", 0.6), ("Склад", 0.4)),
        fact={
            "Закупки": (2_400_000, 2_300_000, 2_500_000, 2_900_000, 3_000_000, 3_200_000),
            "Зарплата": (1_800_000, 1_800_000, 1_850_000, 1_900_000, 1_900_000, 1_950_000),
            "Аренда": (400_000,) * 6,
            "Маркетинг": (300_000, 320_000, 280_000, 220_000, 200_000, 180_000),
            "Логистика": (350_000, 340_000, 360_000, 420_000, 450_000, 480_000),
            "Связь и ПО": (0, 0, 0, 150_000, 150_000, 160_000),
            "Командировки": (120_000, 90_000, 60_000, 0, 0, 0),
        },
        budget={
            "Закупки": (2_500_000,) * 3 + (2_700_000,) * 3,
            "Зарплата": (1_850_000,) * 6,
            "Аренда": (400_000,) * 6,
            "Маркетинг": (300_000,) * 6,
            "Логистика": (350_000,) * 3 + (400_000,) * 3,
            "Связь и ПО": (0, 0, 0, 120_000, 120_000, 120_000),
            "Командировки": (100_000,) * 3 + (50_000,) * 3,
        },
    ),
]


class SeedSource(DataSource):
    """Источник демо-данных. Заодно — минимальный пример собственного DataSource."""

    code = "seed"

    def __init__(self, rows: list[RawRow]):
        self.rows = rows

    @property
    def label(self) -> str:
        return "Демо-данные"

    def fetch(self) -> list[RawRow]:
        return self.rows


def fact_rows(org: DemoOrg) -> list[RawRow]:
    """Факт по дням: каждая месячная сумма разбита на платежи и ЦФО."""
    rows: list[RawRow] = []
    for category, monthly in org.fact.items():
        for month, total in zip(MONTHS, monthly, strict=True):
            if not total:
                continue
            for day, day_share in PAYMENT_DAYS:
                for cost_center, center_share in org.cost_centers:
                    amount = round(total * day_share * center_share, 2)
                    rows.append(
                        RawRow(len(rows) + 1, date(YEAR, month, day), category, amount, cost_center)
                    )
    return rows


def budget_rows(org: DemoOrg) -> list[RawRow]:
    """Бюджет по месяцам, без разбивки по ЦФО."""
    rows: list[RawRow] = []
    for category, monthly in org.budget.items():
        for month, total in zip(MONTHS, monthly, strict=True):
            if total:
                rows.append(RawRow(len(rows) + 1, f"{YEAR}-{month:02}", category, total))
    return rows


def _load(db: Session, admin: User, kind: str, rows: list[RawRow]) -> None:
    upload = imports.create_preview(db, admin, kind, SeedSource(rows))
    upload = imports.confirm_upload(db, admin, upload.id)
    unmatched = imports.describe(db, admin, upload)["unmatched"]
    if unmatched:
        # Все статьи демо-данных становятся категориями справочника
        imports.apply_mapping(db, admin, upload.id, {name: {} for name in unmatched})


def seed(db: Session, password: str = DEFAULT_PASSWORD) -> list[str]:
    """Создаёт демо-организацию; уже существующую пропускает. Возвращает сообщения."""
    messages = []
    for demo in DEMO_ORGS:
        if db.scalar(select(Organization).where(Organization.name == demo.name)):
            messages.append(f"«{demo.name}» уже существует — пропущено")
            continue
        org = Organization(name=demo.name)
        db.add(org)
        db.flush()
        users = {
            role: build_user(db, org.id, f"{demo.prefix}_{role.value}", password, role)
            for role in Role
        }
        prompts.ensure_defaults(db, org.id)
        db.commit()
        _load(db, users[Role.ADMIN], "fact", fact_rows(demo))
        _load(db, users[Role.ADMIN], "budget", budget_rows(demo))
        logins = ", ".join(user.login for user in users.values())
        messages.append(f"«{demo.name}» создана. Пользователи: {logins}")
    return messages
