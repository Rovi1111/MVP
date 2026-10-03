"""Справочники категорий и ЦФО, список сопоставлений."""

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require
from app.models import User
from app.permissions import Permission
from app.repositories.reference import AliasRepository, CategoryRepository, CostCenterRepository
from app.services import reference
from app.web.common import render

router = APIRouter(prefix="/reference")
_editor = require(Permission.REFERENCE_MANAGE)
_TITLES = {"category": "Категории (статьи расходов)", "cost_center": "ЦФО"}
_REPOS = {"category": CategoryRepository, "cost_center": CostCenterRepository}


def _section(request: Request, db: Session, user: User, kind: str):
    context = {"kind": kind, "title": _TITLES[kind], "items": _REPOS[kind](db, user.org_id).list()}
    return render(request, "partials/reference_section.html", context, user)


@router.get("")
def reference_page(request: Request, user: User = Depends(_editor), db: Session = Depends(get_db)):
    context = {
        "sections": [
            {"kind": kind, "title": title, "items": _REPOS[kind](db, user.org_id).list()}
            for kind, title in _TITLES.items()
        ],
        "aliases": AliasRepository(db, user.org_id).list(),
    }
    return render(request, "reference.html", context, user)


@router.post("/aliases/{alias_id}/delete")
def delete_alias(
    request: Request, alias_id: int, user: User = Depends(_editor), db: Session = Depends(get_db)
):
    reference.delete_alias(db, user, alias_id)
    context = {"aliases": AliasRepository(db, user.org_id).list()}
    return render(request, "partials/aliases.html", context, user)


@router.post("/{kind}")
def create_item(
    request: Request,
    kind: str,
    name: str = Form(""),
    user: User = Depends(_editor),
    db: Session = Depends(get_db),
):
    reference.create_item(db, user, kind, name)
    return _section(request, db, user, kind)


@router.post("/{kind}/{item_id}")
def update_item(
    request: Request,
    kind: str,
    item_id: int,
    name: str | None = Form(None),
    is_active: bool | None = Form(None),
    user: User = Depends(_editor),
    db: Session = Depends(get_db),
):
    reference.update_item(db, user, kind, item_id, name=name, is_active=is_active)
    return _section(request, db, user, kind)


@router.post("/{kind}/{item_id}/delete")
def delete_item(
    request: Request,
    kind: str,
    item_id: int,
    user: User = Depends(_editor),
    db: Session = Depends(get_db),
):
    reference.delete_item(db, user, kind, item_id)
    return _section(request, db, user, kind)
