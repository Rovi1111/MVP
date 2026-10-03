"""Демо-данные: три организации, факт за два квартала 2025 года и бюджет.

Запуск: python -m app.cli seed
Данные проходят тот же путь, что и загрузка файла (валидация, сопоставление, версии).
В каждой организации есть все типы изменений между 1 и 2 кварталом
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
        name="Дистрибьютор кормов",
        prefix="feed",
        cost_centers=(("Склад Москва", 0.6), ("Склад Казань", 0.4)),
        fact={
            "Сухой корм": (1_200_000, 1_180_000, 1_220_000, 1_450_000, 1_480_000, 1_420_000),
            "Влажный корм": (800_000, 820_000, 780_000, 650_000, 640_000, 660_000),
            "Лакомства": (150_000, 150_000, 150_000, 150_000, 150_000, 150_000),
            "Ветеринарные диеты": (0, 0, 0, 280_000, 300_000, 320_000),
            "Аксессуары": (90_000, 95_000, 85_000, 0, 0, 0),
        },
        budget={
            "Сухой корм": (1_250_000,) * 6,
            "Влажный корм": (800_000,) * 6,
            "Лакомства": (150_000,) * 6,
            "Ветеринарные диеты": (0, 0, 0, 200_000, 200_000, 200_000),
            "Аксессуары": (90_000,) * 3 + (50_000,) * 3,
        },
    ),
    DemoOrg(
        name="IT-компания",
        prefix="it",
        cost_centers=(("Инфраструктура", 0.7), ("Разработка", 0.3)),
        fact={
            "Серверы CPU": (2_000_000, 1_900_000, 2_100_000, 2_400_000, 2_350_000, 2_450_000),
            "RAM": (600_000, 620_000, 580_000, 450_000, 440_000, 460_000),
            "SSD": (400_000, 400_000, 400_000, 400_000, 400_000, 400_000),
            "GPU": (0, 0, 0, 3_500_000, 1_200_000, 900_000),
            "Сеть": (300_000, 310_000, 290_000, 320_000, 330_000, 310_000),
            "Лицензии": (900_000, 900_000, 900_000, 950_000, 950_000, 950_000),
            "Аренда стоек": (250_000, 250_000, 250_000, 0, 0, 0),
        },
        budget={
            "Серверы CPU": (2_000_000,) * 3 + (2_200_000,) * 3,
            "RAM": (600_000,) * 6,
            "SSD": (400_000,) * 6,
            "GPU": (0, 0, 0, 2_500_000, 1_000_000, 1_000_000),
            "Сеть": (300_000,) * 6,
            "Лицензии": (900_000,) * 6,
            "Аренда стоек": (250_000,) * 3 + (0,) * 3,
        },
    ),
    DemoOrg(
        name="Стоматология",
        prefix="dent",
        cost_centers=(("Клиника на Ленина", 0.55), ("Клиника на Мира", 0.45)),
        fact={
            "Материалы": (420_000, 450_000, 480_000, 530_000, 560_000, 610_000),
            "Аренда": (350_000,) * 6,
            "Зарплата": (1_500_000, 1_500_000, 1_550_000, 1_480_000, 1_450_000, 1_430_000),
            "Оборудование": (0, 0, 0, 900_000, 150_000, 0),
            "Реклама": (120_000, 140_000, 100_000, 180_000, 200_000, 220_000),
            "Обучение персонала": (80_000, 60_000, 0, 0, 0, 0),
        },
        budget={
            "Материалы": (450_000,) * 3 + (500_000,) * 3,
            "Аренда": (350_000,) * 6,
            "Зарплата": (1_550_000,) * 6,
            "Оборудование": (0, 0, 0, 700_000, 100_000, 0),
            "Реклама": (130_000,) * 3 + (150_000,) * 3,
            "Обучение персонала": (80_000, 60_000, 40_000, 0, 0, 0),
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
    """Создаёт демо-организации; уже существующие пропускает. Возвращает сообщения."""
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
