"""Демо-данные: организация с обычными статьями расходов, факт и бюджет за 2024–2025 годы.

Запуск: python -m app.cli seed
Данные проходят тот же путь, что и загрузка файла (валидация, сопоставление, версии).
В них есть рост и снижение по статьям, сезонность, появившаяся и исчезнувшая статьи,
а бюджет меняется от месяца к месяцу и местами превышен.
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
# 24 месяца: январь 2024 — декабрь 2025
MONTHS = [(year, month) for year in (2024, 2025) for month in range(1, 13)]
# Платежи внутри месяца: (день, доля суммы) — чтобы была осмысленной детализация по дням
PAYMENT_DAYS = ((5, 0.5), (15, 0.3), (25, 0.2))

FLAT = (1.0,) * 12
# Коэффициенты по месяцам года: спад летом, пик в конце года
SEASON = (0.95, 0.92, 1.0, 1.0, 1.02, 0.95, 0.9, 0.9, 1.0, 1.08, 1.12, 1.3)
# Бюджет планируют с той же сезонностью, но осторожнее
PLAN_SEASON = (0.96, 0.94, 1.0, 1.0, 1.0, 0.96, 0.92, 0.92, 1.0, 1.05, 1.1, 1.2)
# Зарплата: квартальные премии и годовая в декабре
BONUS = (1.0, 1.0, 1.04, 1.0, 1.0, 1.06, 1.0, 1.0, 1.04, 1.0, 1.0, 1.18)
# Аренда: индексация с июля
INDEXATION = (1.0,) * 6 + (1.04,) * 6


@dataclass(frozen=True)
class Item:
    """Статья расходов демо-компании."""

    base: int  # факт в месяц на январь 2024
    growth: float  # рост факта за год
    season: tuple[float, ...]  # сезонность факта
    plan: tuple[int, int]  # месячный план на 2024 и 2025 годы
    plan_season: tuple[float, ...]  # распределение плана по месяцам года
    first: int = 0  # первый и последний месяц с расходами (0 — январь 2024)
    last: int = 23


@dataclass(frozen=True)
class DemoOrg:
    name: str
    prefix: str  # логины: <prefix>_admin, <prefix>_manager, <prefix>_employee
    cost_centers: tuple[tuple[str, float], ...]  # (ЦФО, доля расходов)
    items: dict[str, Item]

    def fact(self, category: str, index: int) -> int:
        """Факт статьи за месяц с номером index, округлённый до тысяч."""
        item = self.items[category]
        if not item.first <= index <= item.last:
            return 0
        month = MONTHS[index][1]
        return round(item.base * (1 + item.growth) ** (index / 12) * item.season[month - 1], -3)

    def budget(self, category: str, index: int) -> int:
        """План статьи за месяц: годовой уровень с распределением по месяцам."""
        item = self.items[category]
        year, month = MONTHS[index]
        return round(item.plan[year - 2024] * item.plan_season[month - 1], -3)


DEMO_ORGS = [
    DemoOrg(
        name="Демо-компания",
        prefix="demo",
        cost_centers=(("Офис", 0.6), ("Склад", 0.4)),
        items={
            "Закупки": Item(2_200_000, 0.22, SEASON, (2_350_000, 2_700_000), PLAN_SEASON),
            "Зарплата": Item(1_700_000, 0.10, BONUS, (1_750_000, 1_900_000), BONUS),
            "Аренда": Item(400_000, 0.0, INDEXATION, (400_000, 416_000), INDEXATION),
            "Маркетинг": Item(320_000, -0.25, SEASON, (300_000, 280_000), PLAN_SEASON),
            "Логистика": Item(300_000, 0.30, SEASON, (310_000, 370_000), PLAN_SEASON),
            "Связь и ПО": Item(140_000, 0.08, FLAT, (0, 130_000), FLAT, first=12),
            "Командировки": Item(110_000, -0.10, SEASON, (100_000, 80_000), PLAN_SEASON, last=20),
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
    for category in org.items:
        for index, (year, month) in enumerate(MONTHS):
            total = org.fact(category, index)
            for day, day_share in PAYMENT_DAYS if total else ():
                for cost_center, center_share in org.cost_centers:
                    amount = round(total * day_share * center_share, 2)
                    rows.append(
                        RawRow(len(rows) + 1, date(year, month, day), category, amount, cost_center)
                    )
    return rows


def budget_rows(org: DemoOrg) -> list[RawRow]:
    """Бюджет по месяцам, без разбивки по ЦФО."""
    rows: list[RawRow] = []
    for category in org.items:
        for index, (year, month) in enumerate(MONTHS):
            total = org.budget(category, index)
            if total:
                rows.append(RawRow(len(rows) + 1, f"{year}-{month:02}", category, total))
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
