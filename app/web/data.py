"""Страницы ввода данных: загрузка файлов, ручной ввод, история загрузок."""

import json

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.uploads import EXAMPLE_JSON
from app.datasources import ExcelSource, ManualSource
from app.db import get_db
from app.deps import get_current_user, require
from app.errors import AppError, InvalidDataError
from app.models import User
from app.permissions import Permission
from app.repositories.data import UploadRepository
from app.repositories.reference import CategoryRepository, CostCenterRepository
from app.services import imports
from app.web.common import render

router = APIRouter()


def _card(request: Request, db: Session, user: User, upload, status_code: int = 200):
    context = {
        "info": imports.describe(db, user, upload),
        "categories": CategoryRepository(db, user.org_id).list(only_active=True),
    }
    return render(request, "partials/upload_card.html", context, user, status_code)


def _preview(request: Request, db: Session, user: User, kind: str, source):
    """Общий путь файла и ручного ввода: предпросмотр либо таблица ошибок."""
    try:
        upload = imports.create_preview(db, user, kind, source)
    except imports.ImportValidationError as exc:
        context = {"message": exc.message, "errors": exc.errors}
        return render(request, "partials/upload_errors.html", context, user, exc.status_code)
    except AppError as exc:
        return render(
            request, "partials/alert.html", {"message": exc.message}, user, exc.status_code
        )
    return _card(request, db, user, upload)


@router.get("/data")
def data_page(
    request: Request,
    user: User = Depends(require(Permission.DATA_MANUAL)),
    db: Session = Depends(get_db),
):
    context = {
        "categories": CategoryRepository(db, user.org_id).list(only_active=True),
        "cost_centers": CostCenterRepository(db, user.org_id).list(only_active=True),
        "example_json": json.dumps(EXAMPLE_JSON, ensure_ascii=False, indent=2),
    }
    return render(request, "data.html", context, user)


@router.post("/uploads/{kind}/file")
def upload_file(
    request: Request,
    kind: str,
    file: UploadFile = File(...),
    user: User = Depends(require(Permission.DATA_UPLOAD)),
    db: Session = Depends(get_db),
):
    return _preview(request, db, user, kind, ExcelSource(file.file.read(), file.filename or ""))


@router.post("/uploads/manual/form")
def manual_form(
    request: Request,
    kind: str = Form(...),
    period: list[str] = Form(default=[]),
    category: list[str] = Form(default=[]),
    amount: list[str] = Form(default=[]),
    cost_center: list[str] = Form(default=[]),
    user: User = Depends(require(Permission.DATA_MANUAL)),
    db: Session = Depends(get_db),
):
    rows = [
        {"period": p, "category": c, "amount": a, "cost_center": cc}
        for p, c, a, cc in zip(period, category, amount, cost_center, strict=False)
    ]
    return _preview(request, db, user, kind, ManualSource(rows))


@router.post("/uploads/manual/json")
def manual_json(
    request: Request,
    payload: str = Form(""),
    user: User = Depends(require(Permission.DATA_MANUAL)),
    db: Session = Depends(get_db),
):
    try:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise InvalidDataError(
                f"Некорректный JSON: строка {exc.lineno}, позиция {exc.colno} — {exc.msg}"
            ) from None
        if not isinstance(data, dict) or "kind" not in data or "rows" not in data:
            raise InvalidDataError("Ожидается объект с полями kind и rows (см. пример)")
    except AppError as exc:
        return render(
            request, "partials/alert.html", {"message": exc.message}, user, exc.status_code
        )
    return _preview(request, db, user, str(data["kind"]), ManualSource(data["rows"]))


@router.post("/uploads/{upload_id}/confirm")
def confirm(
    request: Request,
    upload_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _card(request, db, user, imports.confirm_upload(db, user, upload_id))


@router.post("/uploads/{upload_id}/mapping")
async def mapping(
    request: Request,
    upload_id: int,
    user: User = Depends(require(Permission.REFERENCE_MANAGE)),
    db: Session = Depends(get_db),
):
    form = await request.form()
    names, targets, new_names = (form.getlist(k) for k in ("name", "target", "new_name"))
    payload = {
        name: {"category_id": int(target)} if target.isdigit() else {"new_name": new_name}
        for name, target, new_name in zip(names, targets, new_names, strict=False)
    }
    return _card(request, db, user, imports.apply_mapping(db, user, upload_id, payload))


@router.post("/uploads/{upload_id}/cancel")
def cancel(
    request: Request,
    upload_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _card(request, db, user, imports.cancel_upload(db, user, upload_id))


@router.get("/uploads")
def uploads_page(
    request: Request,
    user: User = Depends(require(Permission.ANALYTICS_VIEW)),
    db: Session = Depends(get_db),
):
    context = {"uploads": UploadRepository(db, user.org_id).history()}
    return render(request, "uploads.html", context, user)


@router.get("/uploads/{upload_id}")
def upload_page(
    request: Request,
    upload_id: int,
    user: User = Depends(require(Permission.ANALYTICS_VIEW)),
    db: Session = Depends(get_db),
):
    context = {
        "info": imports.get_description(db, user, upload_id),
        "categories": CategoryRepository(db, user.org_id).list(only_active=True),
    }
    return render(request, "upload_detail.html", context, user)
