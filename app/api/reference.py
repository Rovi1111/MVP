from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import csrf_protect, get_current_user, require
from app.models import User
from app.permissions import Permission
from app.repositories.reference import AliasRepository, CategoryRepository, CostCenterRepository
from app.schemas import AliasOut, NamedItemCreate, NamedItemOut, NamedItemUpdate
from app.services import reference

router = APIRouter(tags=["reference"], dependencies=[Depends(csrf_protect)])
_editor = require(Permission.REFERENCE_MANAGE)


def _crud(path: str, kind: str, repo_cls) -> None:
    """Одинаковый CRUD для категорий и ЦФО."""

    @router.get(path, response_model=list[NamedItemOut], name=f"list_{kind}")
    def list_items(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
        return repo_cls(db, user.org_id).list()

    @router.post(
        path,
        response_model=NamedItemOut,
        status_code=status.HTTP_201_CREATED,
        name=f"create_{kind}",
    )
    def create_item(
        data: NamedItemCreate, user: User = Depends(_editor), db: Session = Depends(get_db)
    ):
        return reference.create_item(db, user, kind, data.name)

    @router.patch(path + "/{item_id}", response_model=NamedItemOut, name=f"update_{kind}")
    def update_item(
        item_id: int,
        data: NamedItemUpdate,
        user: User = Depends(_editor),
        db: Session = Depends(get_db),
    ):
        return reference.update_item(db, user, kind, item_id, **data.model_dump(exclude_unset=True))

    @router.delete(
        path + "/{item_id}", status_code=status.HTTP_204_NO_CONTENT, name=f"delete_{kind}"
    )
    def delete_item(item_id: int, user: User = Depends(_editor), db: Session = Depends(get_db)):
        reference.delete_item(db, user, kind, item_id)


_crud("/categories", "category", CategoryRepository)
_crud("/cost-centers", "cost_center", CostCenterRepository)


@router.get("/category-aliases", response_model=list[AliasOut])
def list_aliases(user: User = Depends(_editor), db: Session = Depends(get_db)):
    return [
        AliasOut(id=a.id, alias=a.alias, category_id=a.category_id, category=a.category.name)
        for a in AliasRepository(db, user.org_id).list()
    ]


@router.delete("/category-aliases/{alias_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alias(alias_id: int, user: User = Depends(_editor), db: Session = Depends(get_db)):
    reference.delete_alias(db, user, alias_id)
