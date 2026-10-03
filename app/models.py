"""ORM-модели. Все таблицы с данными организации содержат org_id."""

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.db_types import Money


def utcnow() -> datetime:
    return datetime.now(UTC)


class UploadKind(StrEnum):
    FACT = "fact"
    BUDGET = "budget"


class UploadStatus(StrEnum):
    PREVIEW = "preview"  # разобрана, ждёт подтверждения пользователем
    PENDING_MAPPING = "pending_mapping"  # ждёт сопоставления статей
    ACTIVE = "active"  # данные записаны и участвуют в расчётах
    SUPERSEDED = "superseded"  # полностью заменена более новой версией
    CANCELLED = "cancelled"


class Grain(StrEnum):
    """Исходная детализация периода во входных данных."""

    DAY = "day"
    MONTH = "month"
    QUARTER = "quarter"


class OrgMixin:
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(OrgMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Логин уникален во всей системе: на форме входа организация не выбирается
    login: Mapped[str] = mapped_column(String(100), unique=True)
    full_name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    organization: Mapped[Organization] = relationship()


class Category(OrgMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("org_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CostCenter(OrgMixin, Base):
    __tablename__ = "cost_centers"
    __table_args__ = (UniqueConstraint("org_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CategoryAlias(OrgMixin, Base):
    """Запомненное сопоставление «название статьи из файла → категория»."""

    __tablename__ = "category_aliases"
    __table_args__ = (UniqueConstraint("org_id", "alias"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(String(200))  # нормализованное название
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))

    category: Mapped[Category] = relationship()


class Upload(OrgMixin, Base):
    """Одна загрузка данных (файл или ручной ввод) = одна версия."""

    __tablename__ = "uploads"
    __table_args__ = (UniqueConstraint("org_id", "kind", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(20), default="excel")
    file_name: Mapped[str] = mapped_column(String(255), default="")
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Номер версии присваивается при записи данных; у черновиков его нет
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=UploadStatus.PREVIEW)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    # Разобранные строки до подтверждения/сопоставления
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    author: Mapped[User] = relationship()


class ExpenseRecord(OrgMixin, Base):
    """Факт расходов."""

    __tablename__ = "expense_records"
    __table_args__ = (Index("ix_expense_org_date", "org_id", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id"), index=True)
    date: Mapped[date] = mapped_column(Date)
    grain: Mapped[str] = mapped_column(String(10), default=Grain.DAY)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    cost_center_id: Mapped[int | None] = mapped_column(ForeignKey("cost_centers.id"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    source: Mapped[str] = mapped_column(String(20), default="excel")
    # False — запись заменена более новой загрузкой за тот же месяц
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    category: Mapped[Category] = relationship()
    cost_center: Mapped[CostCenter | None] = relationship()


class BudgetLine(OrgMixin, Base):
    """План (бюджет). Версия бюджета = upload_id."""

    __tablename__ = "budget_lines"
    __table_args__ = (Index("ix_budget_org_date", "org_id", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id"), index=True)
    date: Mapped[date] = mapped_column(Date)
    grain: Mapped[str] = mapped_column(String(10), default=Grain.MONTH)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    cost_center_id: Mapped[int | None] = mapped_column(ForeignKey("cost_centers.id"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Money)

    category: Mapped[Category] = relationship()
    cost_center: Mapped[CostCenter | None] = relationship()


class PromptTemplate(OrgMixin, Base):
    __tablename__ = "prompt_templates"
    __table_args__ = (UniqueConstraint("org_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    scenario: Mapped[str] = mapped_column(String(50), default="")
    text: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Analysis(OrgMixin, Base):
    """Сохранённый расчёт: параметры, снимок результатов и текст AI-анализа."""

    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(255), default="")
    params: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    ai_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("prompt_templates.id"), nullable=True
    )
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    author: Mapped[User] = relationship()


class Setting(OrgMixin, Base):
    """Настройки, которые администратор меняет в UI (перекрывают .env)."""

    __tablename__ = "settings"
    __table_args__ = (UniqueConstraint("org_id", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100))
    value: Mapped[str] = mapped_column(Text, default="")


class AuditLog(OrgMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_org_created", "org_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    user_login: Mapped[str] = mapped_column(String(100), default="")
    action: Mapped[str] = mapped_column(String(50))
    entity: Mapped[str] = mapped_column(String(50), default="")
    entity_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
