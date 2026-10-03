from collections.abc import Sequence

from app.models import Analysis, PromptTemplate
from app.repositories.base import OrgRepository


class AnalysisRepository(OrgRepository[Analysis]):
    model = Analysis

    def recent(self, limit: int = 200) -> Sequence[Analysis]:
        return self.db.scalars(self._select().order_by(Analysis.id.desc()).limit(limit)).all()


class PromptTemplateRepository(OrgRepository[PromptTemplate]):
    model = PromptTemplate

    def list(self, only_active: bool = False) -> Sequence[PromptTemplate]:
        stmt = self._select().order_by(PromptTemplate.id)
        if only_active:
            stmt = stmt.where(PromptTemplate.is_active.is_(True))
        return self.db.scalars(stmt).all()
