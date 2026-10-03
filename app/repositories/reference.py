from collections.abc import Sequence

from sqlalchemy import func, select

from app.models import BudgetLine, Category, CategoryAlias, CostCenter, ExpenseRecord
from app.repositories.base import OrgRepository


class _NamedRepository[M](OrgRepository[M]):
    def list(self, only_active: bool = False) -> Sequence[M]:
        stmt = self._select().order_by(self.model.name)
        if only_active:
            stmt = stmt.where(self.model.is_active.is_(True))
        return self.db.scalars(stmt).all()

    def _usage_count(self, column_name: str, obj_id: int) -> int:
        total = 0
        for model in (ExpenseRecord, BudgetLine):
            stmt = (
                select(func.count())
                .select_from(model)
                .where(model.org_id == self.org_id, getattr(model, column_name) == obj_id)
            )
            total += self.db.scalar(stmt) or 0
        return total


class CategoryRepository(_NamedRepository[Category]):
    model = Category

    def is_used(self, category_id: int) -> bool:
        return self._usage_count("category_id", category_id) > 0


class CostCenterRepository(_NamedRepository[CostCenter]):
    model = CostCenter

    def is_used(self, cost_center_id: int) -> bool:
        return self._usage_count("cost_center_id", cost_center_id) > 0


class AliasRepository(OrgRepository[CategoryAlias]):
    model = CategoryAlias

    def list(self) -> Sequence[CategoryAlias]:
        return self.db.scalars(self._select().order_by(CategoryAlias.alias)).all()

    def delete_for_category(self, category_id: int) -> None:
        for alias in self.db.scalars(
            self._select().where(CategoryAlias.category_id == category_id)
        ):
            self.db.delete(alias)
