from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import func, or_, select, update

from app.models import (
    BudgetLine,
    Category,
    CostCenter,
    ExpenseRecord,
    Upload,
    UploadKind,
    UploadStatus,
)
from app.repositories.base import OrgRepository


class DataRow(NamedTuple):
    """Строка факта или плана для расчётов."""

    date: date
    grain: str
    category: str
    cost_center: str | None
    amount: Decimal


def _data_rows(db, model, conditions, start, end, cost_center_id) -> list[DataRow]:
    stmt = (
        select(model.date, model.grain, Category.name, CostCenter.name, model.amount)
        .join(Category, Category.id == model.category_id)
        .outerjoin(CostCenter, CostCenter.id == model.cost_center_id)
        .where(*conditions, model.date.between(start, end))
    )
    if cost_center_id is not None:
        stmt = stmt.where(model.cost_center_id == cost_center_id)
    return [DataRow(*row) for row in db.execute(stmt)]


class UploadRepository(OrgRepository[Upload]):
    model = Upload

    def next_version(self, kind: str) -> int:
        stmt = select(func.max(Upload.version)).where(
            Upload.org_id == self.org_id, Upload.kind == kind
        )
        return (self.db.scalar(stmt) or 0) + 1

    def history(self, kind: str | None = None, limit: int = 200) -> Sequence[Upload]:
        stmt = self._select().order_by(Upload.id.desc()).limit(limit)
        if kind:
            stmt = stmt.where(Upload.kind == kind)
        return self.db.scalars(stmt).all()

    def budget_versions(self) -> Sequence[Upload]:
        """Действующие версии бюджета, от новой к старой."""
        stmt = (
            self._select()
            .where(Upload.kind == UploadKind.BUDGET, Upload.status == UploadStatus.ACTIVE)
            .order_by(Upload.version.desc())
        )
        return self.db.scalars(stmt).all()


class ExpenseRepository(OrgRepository[ExpenseRecord]):
    model = ExpenseRecord

    def _active_in(self, ranges: Sequence[tuple[date, date]]):
        in_ranges = or_(*(ExpenseRecord.date.between(start, end) for start, end in ranges))
        return (
            ExpenseRecord.org_id == self.org_id,
            ExpenseRecord.is_active.is_(True),
            in_ranges,
        )

    def count_active_in(self, ranges: Sequence[tuple[date, date]]) -> int:
        if not ranges:
            return 0
        stmt = select(func.count()).select_from(ExpenseRecord).where(*self._active_in(ranges))
        return self.db.scalar(stmt) or 0

    def deactivate_in(self, ranges: Sequence[tuple[date, date]]) -> set[int]:
        """Снимает с учёта записи за указанные интервалы; возвращает затронутые загрузки."""
        if not ranges:
            return set()
        conditions = self._active_in(ranges)
        upload_ids = set(
            self.db.scalars(select(ExpenseRecord.upload_id).where(*conditions).distinct())
        )
        self.db.execute(update(ExpenseRecord).where(*conditions).values(is_active=False))
        return upload_ids

    def deactivate_upload(self, upload_id: int) -> None:
        self.db.execute(
            update(ExpenseRecord)
            .where(ExpenseRecord.org_id == self.org_id, ExpenseRecord.upload_id == upload_id)
            .values(is_active=False)
        )

    def has_active(self, upload_id: int) -> bool:
        stmt = (
            select(func.count())
            .select_from(ExpenseRecord)
            .where(
                ExpenseRecord.org_id == self.org_id,
                ExpenseRecord.upload_id == upload_id,
                ExpenseRecord.is_active.is_(True),
            )
        )
        return bool(self.db.scalar(stmt))

    def rows(self, start: date, end: date, cost_center_id: int | None = None) -> list[DataRow]:
        """Действующий факт за период (включительно)."""
        conditions = (ExpenseRecord.org_id == self.org_id, ExpenseRecord.is_active.is_(True))
        return _data_rows(self.db, ExpenseRecord, conditions, start, end, cost_center_id)

    def date_bounds(self) -> tuple[date | None, date | None]:
        stmt = select(func.min(ExpenseRecord.date), func.max(ExpenseRecord.date)).where(
            ExpenseRecord.org_id == self.org_id, ExpenseRecord.is_active.is_(True)
        )
        return tuple(self.db.execute(stmt).one())


class BudgetRepository(OrgRepository[BudgetLine]):
    model = BudgetLine

    def rows(
        self, upload_id: int, start: date, end: date, cost_center_id: int | None = None
    ) -> list[DataRow]:
        """Строки одной версии бюджета за период (включительно)."""
        conditions = (BudgetLine.org_id == self.org_id, BudgetLine.upload_id == upload_id)
        return _data_rows(self.db, BudgetLine, conditions, start, end, cost_center_id)

    def for_upload(
        self, upload_id: int, start: date | None = None, end: date | None = None
    ) -> Sequence[BudgetLine]:
        stmt = self._select().where(BudgetLine.upload_id == upload_id)
        if start and end:
            stmt = stmt.where(BudgetLine.date.between(start, end))
        return self.db.scalars(stmt).all()
