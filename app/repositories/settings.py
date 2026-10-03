from app.models import Setting
from app.repositories.base import OrgRepository


class SettingRepository(OrgRepository[Setting]):
    model = Setting

    def as_dict(self) -> dict[str, str]:
        return {s.key: s.value for s in self.list()}

    def set(self, key: str, value: str) -> None:
        setting = self.db.scalar(self._select().where(Setting.key == key))
        if setting is None:
            self.add(Setting(key=key, value=value))
        else:
            setting.value = value
