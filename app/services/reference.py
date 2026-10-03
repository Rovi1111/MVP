"""Справочники: категории (статьи расходов), ЦФО, сопоставления статей."""

from sqlalchemy.orm import Session

from app.errors import ConflictError, InvalidDataError, NotFoundError
from app.models import Category, CategoryAlias, CostCenter, User
from app.repositories.reference import AliasRepository, CategoryRepository, CostCenterRepository
from app.services.audit import log_action
from app.services.parsing import clean_name, normalize_name

_KINDS = {
    "category": (CategoryRepository, Category, "Категория"),
    "cost_center": (CostCenterRepository, CostCenter, "ЦФО"),
}


class CategoryResolver:
    """Находит категорию по названию из файла: сначала справочник, затем алиасы."""

    def __init__(self, db: Session, org_id: int):
        self._by_name: dict[str, int] = {}
        for alias in AliasRepository(db, org_id).list():
            self._by_name[alias.alias] = alias.category_id
        for category in CategoryRepository(db, org_id).list():
            self._by_name[normalize_name(category.name)] = category.id

    def resolve(self, name: str) -> int | None:
        return self._by_name.get(normalize_name(name))


def _repo(db: Session, org_id: int, kind: str):
    if kind not in _KINDS:
        raise NotFoundError("Неизвестный справочник")
    repo_cls, model, label = _KINDS[kind]
    return repo_cls(db, org_id), model, label


def _check_unique(repo, label: str, name: str, exclude_id: int | None = None) -> None:
    key = normalize_name(name)
    for item in repo.list():
        if item.id != exclude_id and normalize_name(item.name) == key:
            raise ConflictError(f"{label} «{item.name}» уже есть в справочнике")


def build_item(db: Session, org_id: int, kind: str, name: str):
    """Создаёт запись справочника без аудита и commit (используется также импортом)."""
    repo, model, label = _repo(db, org_id, kind)
    name = clean_name(name or "")
    if not name:
        raise InvalidDataError("Название не может быть пустым")
    if len(name) > 200:
        raise InvalidDataError("Название длиннее 200 символов")
    _check_unique(repo, label, name)
    return repo.add(model(name=name))


def create_item(db: Session, actor: User, kind: str, name: str):
    item = build_item(db, actor.org_id, kind, name)
    log_action(db, actor, "create", kind, item.id, {"name": item.name})
    db.commit()
    return item


def update_item(
    db: Session,
    actor: User,
    kind: str,
    item_id: int,
    *,
    name: str | None = None,
    is_active: bool | None = None,
):
    repo, _, label = _repo(db, actor.org_id, kind)
    item = repo.get(item_id)
    if item is None:
        raise NotFoundError(f"{label}: запись не найдена")
    changes: dict = {}
    if name is not None and clean_name(name) != item.name:
        name = clean_name(name)
        if not name:
            raise InvalidDataError("Название не может быть пустым")
        _check_unique(repo, label, name, exclude_id=item.id)
        item.name = changes["name"] = name
    if is_active is not None and is_active != item.is_active:
        item.is_active = changes["is_active"] = is_active
    if changes:
        log_action(db, actor, "update", kind, item.id, changes)
    db.commit()
    return item


def delete_item(db: Session, actor: User, kind: str, item_id: int) -> None:
    repo, _, label = _repo(db, actor.org_id, kind)
    item = repo.get(item_id)
    if item is None:
        raise NotFoundError(f"{label}: запись не найдена")
    if repo.is_used(item.id):
        raise ConflictError(
            f"{label} «{item.name}» используется в данных — её нельзя удалить, но можно отключить"
        )
    if kind == "category":
        AliasRepository(db, actor.org_id).delete_for_category(item.id)
    log_action(db, actor, "delete", kind, item.id, {"name": item.name})
    db.delete(item)
    db.commit()


def build_alias(db: Session, org_id: int, source_name: str, category_id: int) -> None:
    """Запоминает сопоставление «название из файла → категория» (без commit)."""
    key = normalize_name(source_name)
    repo = AliasRepository(db, org_id)
    for alias in repo.list():
        if alias.alias == key:
            alias.category_id = category_id
            return
    repo.add(CategoryAlias(alias=key, category_id=category_id))


def delete_alias(db: Session, actor: User, alias_id: int) -> None:
    alias = AliasRepository(db, actor.org_id).get(alias_id)
    if alias is None:
        raise NotFoundError("Сопоставление не найдено")
    log_action(db, actor, "delete", "category_alias", alias.id, {"alias": alias.alias})
    db.delete(alias)
    db.commit()
