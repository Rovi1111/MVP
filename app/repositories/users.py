from sqlalchemy import func, select

from app.models import User
from app.repositories.base import OrgRepository


class UserRepository(OrgRepository[User]):
    model = User

    def login_exists(self, login: str) -> bool:
        """Логины уникальны во всей системе, поэтому проверка не ограничена организацией."""
        stmt = select(func.count()).select_from(User).where(User.login == login)
        return bool(self.db.scalar(stmt))
