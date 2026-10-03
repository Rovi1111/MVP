from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.datasources import ExcelSource, ManualSource
from app.db import get_db
from app.deps import csrf_protect, get_current_user, require
from app.models import User
from app.permissions import Permission
from app.repositories.data import UploadRepository
from app.schemas import ManualInput, MappingIn, UploadOut
from app.services import imports
from app.services.excel_templates import build_template

router = APIRouter(tags=["uploads"], dependencies=[Depends(csrf_protect)])

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EXAMPLE_JSON = {
    "kind": "fact",
    "rows": [
        {"period": "2025-01-15", "category": "Аренда", "amount": 120000, "cost_center": "Офис"},
        {"period": "янв 2025", "category": "Реклама", "amount": "35 500,50"},
    ],
}


@router.get("/templates/{kind}")
def download_template(kind: str, user: User = Depends(get_current_user)):
    """Шаблон Excel для факта (fact) или бюджета (budget)."""
    kind = imports.check_kind(kind)
    headers = {"Content-Disposition": f'attachment; filename="template_{kind}.xlsx"'}
    return Response(build_template(kind), media_type=XLSX_MIME, headers=headers)


@router.post("/uploads/{kind}/file", status_code=status.HTTP_201_CREATED)
def upload_file(
    kind: str,
    file: UploadFile = File(...),
    user: User = Depends(require(Permission.DATA_UPLOAD)),
    db: Session = Depends(get_db),
):
    """Разбирает файл и возвращает предпросмотр. Данные пишутся после /confirm."""
    source = ExcelSource(file.file.read(), file.filename or "")
    upload = imports.create_preview(db, user, kind, source)
    return imports.describe(db, user, upload)


@router.post("/uploads/manual", status_code=status.HTTP_201_CREATED)
def manual_input(
    data: ManualInput,
    user: User = Depends(require(Permission.DATA_MANUAL)),
    db: Session = Depends(get_db),
):
    """Ручной ввод в формате JSON (пример — GET /api/uploads/manual/example)."""
    source = ManualSource([row.model_dump() for row in data.rows])
    upload = imports.create_preview(db, user, data.kind, source)
    return imports.describe(db, user, upload)


@router.get("/uploads/manual/example")
def manual_example(user: User = Depends(get_current_user)):
    return EXAMPLE_JSON


@router.get("/uploads", response_model=list[UploadOut])
def list_uploads(
    kind: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return UploadRepository(db, user.org_id).history(kind)


@router.get("/uploads/{upload_id}")
def get_upload(
    upload_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return imports.get_description(db, user, upload_id)


@router.post("/uploads/{upload_id}/confirm")
def confirm(upload_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    upload = imports.confirm_upload(db, user, upload_id)
    return imports.describe(db, user, upload)


@router.post("/uploads/{upload_id}/mapping")
def mapping(
    upload_id: int,
    data: MappingIn,
    user: User = Depends(require(Permission.REFERENCE_MANAGE)),
    db: Session = Depends(get_db),
):
    payload = {name: target.model_dump() for name, target in data.mapping.items()}
    upload = imports.apply_mapping(db, user, upload_id, payload)
    return imports.describe(db, user, upload)


@router.post("/uploads/{upload_id}/cancel")
def cancel(upload_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    upload = imports.cancel_upload(db, user, upload_id)
    return imports.describe(db, user, upload)
