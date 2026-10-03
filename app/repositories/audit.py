from collections.abc import Sequence

from sqlalchemy import select

from app.models import AuditLog
from app.repositories.base import OrgRepository


class AuditRepository(OrgRepository[AuditLog]):
    model = AuditLog

    def recent(
        self, limit: int = 200, offset: int = 0, action: str | None = None
    ) -> Sequence[AuditLog]:
        stmt = self._select().order_by(AuditLog.id.desc()).limit(limit).offset(offset)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        return self.db.scalars(stmt).all()

    def actions(self) -> list[str]:
        stmt = select(AuditLog.action).where(AuditLog.org_id == self.org_id).distinct()
        return sorted(self.db.scalars(stmt))
