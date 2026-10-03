"""Базовый репозиторий: любой запрос ограничен организацией пользователя."""

from collections.abc import Sequence

from sqlalchemy import Select, select
from sqlalchemy.orm import Session


class OrgRepository[M]:
    """Доступ к таблице только в пределах одной организации.

    Репозитории — единственный слой, который строит запросы к данным,
    поэтому изоляция организаций обеспечивается здесь, а не в каждом роутере.
    """

    model: type[M]

    def __init__(self, db: Session, org_id: int):
        self.db = db
        self.org_id = org_id

    def _select(self) -> Select:
        return select(self.model).where(self.model.org_id == self.org_id)

    def get(self, obj_id: int) -> M | None:
        return self.db.scalar(self._select().where(self.model.id == obj_id))

    def list(self) -> Sequence[M]:
        return self.db.scalars(self._select().order_by(self.model.id)).all()

    def add(self, obj: M) -> M:
        obj.org_id = self.org_id
        self.db.add(obj)
        self.db.flush()
        return obj
