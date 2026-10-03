"""Импорт факта и бюджета: валидация → предпросмотр → сопоставление статей → запись.

Источник данных (файл, ручной ввод, будущие API-коннекторы) скрыт за DataSource.
"""

import calendar
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.datasources import DataSource, RawRow
from app.errors import ConflictError, InvalidDataError, NotFoundError, PermissionDeniedError
from app.models import (
    BudgetLine,
    ExpenseRecord,
    Grain,
    Upload,
    UploadKind,
    UploadStatus,
    User,
)
from app.permissions import Permission, has_permission
from app.repositories.data import BudgetRepository, ExpenseRepository, UploadRepository
from app.repositories.reference import CategoryRepository, CostCenterRepository
from app.services import reference
from app.services.audit import log_action
from app.services.parsing import AmountError, clean_name, normalize_name, parse_amount
from app.services.periods import PeriodError, parse_period

PREVIEW_ROWS = 20
MANUAL = "manual"
_OPEN_STATUSES = (UploadStatus.PREVIEW, UploadStatus.PENDING_MAPPING)


@dataclass(frozen=True)
class RowError:
    row: int
    column: str
    problem: str


@dataclass(frozen=True)
class ParsedRow:
    date: date
    grain: str
    category: str
    cost_center: str | None
    amount: Decimal

    def to_json(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "grain": self.grain,
            "category": self.category,
            "cost_center": self.cost_center,
            "amount": str(self.amount),
        }

    @classmethod
    def from_json(cls, data: Mapping) -> "ParsedRow":
        return cls(
            date=date.fromisoformat(data["date"]),
            grain=data["grain"],
            category=data["category"],
            cost_center=data["cost_center"],
            amount=Decimal(data["amount"]),
        )


class ImportValidationError(InvalidDataError):
    """В данных есть ошибки; ничего не записано."""

    def __init__(self, errors: list[RowError]):
        super().__init__(f"В данных найдены ошибки ({len(errors)}). Ничего не записано")
        self.errors = [{"row": e.row, "column": e.column, "problem": e.problem} for e in errors]


# ---------- чистые функции ----------


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def validate_rows(raw_rows: Iterable[RawRow], kind: str) -> tuple[list[ParsedRow], list[RowError]]:
    """Проверяет строки источника. Возвращает разобранные строки и список ошибок."""
    rows: list[ParsedRow] = []
    errors: list[RowError] = []
    for raw in raw_rows:
        problems: list[RowError] = []

        period = None
        if _blank(raw.period):
            problems.append(RowError(raw.row, "Период", "Обязательное поле не заполнено"))
        else:
            try:
                period = parse_period(raw.period)
            except PeriodError as exc:
                problems.append(RowError(raw.row, "Период", str(exc)))

        if _blank(raw.category):
            problems.append(RowError(raw.row, "Статья", "Обязательное поле не заполнено"))
        elif not isinstance(raw.category, str):
            problems.append(RowError(raw.row, "Статья", f"Ожидается текст, а не «{raw.category}»"))
        elif len(clean_name(raw.category)) > 200:
            problems.append(RowError(raw.row, "Статья", "Название длиннее 200 символов"))

        amount = None
        if _blank(raw.amount):
            problems.append(RowError(raw.row, "Сумма", "Обязательное поле не заполнено"))
        else:
            try:
                amount = parse_amount(raw.amount)
            except AmountError as exc:
                problems.append(RowError(raw.row, "Сумма", str(exc)))
            else:
                if kind == UploadKind.BUDGET and amount < 0:
                    problems.append(RowError(raw.row, "Сумма", "План не может быть отрицательным"))

        cost_center = None if _blank(raw.cost_center) else clean_name(raw.cost_center)
        if cost_center and len(cost_center) > 200:
            problems.append(RowError(raw.row, "ЦФО", "Название длиннее 200 символов"))

        if problems:
            errors.extend(problems)
        else:
            rows.append(
                ParsedRow(period.date, period.grain, clean_name(raw.category), cost_center, amount)
            )
    return rows, errors


def aggregate_rows(rows: Iterable[ParsedRow]) -> list[ParsedRow]:
    """Суммирует строки с одинаковыми днём, статьёй и ЦФО."""
    merged: dict[tuple, ParsedRow] = {}
    for row in rows:
        key = (
            row.date,
            row.grain,
            normalize_name(row.category),
            normalize_name(row.cost_center) if row.cost_center else None,
        )
        if key in merged:
            first = merged[key]
            merged[key] = ParsedRow(
                first.date, first.grain, first.category, first.cost_center,
                first.amount + row.amount,
            )  # fmt: skip
        else:
            merged[key] = row
    return sorted(merged.values(), key=lambda r: (r.date, r.category, r.cost_center or ""))


def _month_range(day: date, months: int = 1) -> tuple[date, date]:
    start = day.replace(day=1)
    end_index = start.month - 1 + months - 1
    end_year, end_month = start.year + end_index // 12, end_index % 12 + 1
    return start, date(end_year, end_month, calendar.monthrange(end_year, end_month)[1])


def covered_months(rows: Iterable[ParsedRow]) -> list[tuple[date, date]]:
    """Календарные месяцы, которые затрагивают строки (квартальная строка — три месяца)."""
    months: set[tuple[date, date]] = set()
    for row in rows:
        if row.grain == Grain.QUARTER:
            for offset in range(3):
                months.add(_month_range(_month_range(row.date, offset + 1)[1]))
        else:
            months.add(_month_range(row.date))
    return sorted(months)


# ---------- операции с загрузками ----------


def _rows_of(upload: Upload) -> list[ParsedRow]:
    return [ParsedRow.from_json(item) for item in (upload.payload or {}).get("rows", [])]


def _get_upload(db: Session, user: User, upload_id: int) -> Upload:
    upload = UploadRepository(db, user.org_id).get(upload_id)
    if upload is None:
        raise NotFoundError("Загрузка не найдена")
    return upload


def check_kind(kind: str) -> str:
    try:
        return UploadKind(kind).value
    except ValueError:
        raise InvalidDataError("Тип данных должен быть fact или budget") from None


def _check_source_permission(user: User, source_code: str) -> None:
    needed = Permission.DATA_MANUAL if source_code == MANUAL else Permission.DATA_UPLOAD
    if not has_permission(user.role, needed):
        raise PermissionDeniedError("Недостаточно прав для этого действия")


def create_preview(db: Session, user: User, kind: str, source: DataSource) -> Upload:
    """Читает источник и сохраняет черновик загрузки. При ошибках ничего не пишет."""
    kind = check_kind(kind)
    _check_source_permission(user, source.code)
    rows, errors = validate_rows(source.fetch(), kind)
    if errors:
        raise ImportValidationError(errors)
    source_rows = len(rows)
    rows = aggregate_rows(rows)
    upload = UploadRepository(db, user.org_id).add(
        Upload(
            kind=kind,
            source=source.code,
            file_name=source.label[:255],
            uploaded_by=user.id,
            status=UploadStatus.PREVIEW,
            row_count=len(rows),
            total=sum((r.amount for r in rows), Decimal("0")),
            payload={"source_rows": source_rows, "rows": [r.to_json() for r in rows]},
        )
    )
    db.commit()
    return upload


def describe(db: Session, user: User, upload: Upload) -> dict:
    """Сводка по загрузке для предпросмотра и истории."""
    rows = _rows_of(upload)
    is_open = upload.status in _OPEN_STATUSES

    by_category: dict[str, Decimal] = {}
    for row in rows:
        by_category[row.category] = by_category.get(row.category, Decimal("0")) + row.amount

    unmatched: list[str] = []
    new_cost_centers: list[str] = []
    replaces = None
    if is_open:
        resolver = reference.CategoryResolver(db, user.org_id)
        unmatched = sorted(name for name in by_category if resolver.resolve(name) is None)
        known = {normalize_name(c.name) for c in CostCenterRepository(db, user.org_id).list()}
        new_cost_centers = sorted(
            {
                r.cost_center
                for r in rows
                if r.cost_center and normalize_name(r.cost_center) not in known
            }
        )
        if upload.kind == UploadKind.FACT and upload.source != MANUAL:
            months = covered_months(rows)
            replaces = {
                "months": [start.strftime("%m.%Y") for start, _ in months],
                "records": ExpenseRepository(db, user.org_id).count_active_in(months),
            }

    return {
        "id": upload.id,
        "kind": upload.kind,
        "source": upload.source,
        "file_name": upload.file_name,
        "status": upload.status,
        "version": upload.version,
        "created_at": upload.created_at,
        "author": upload.author.login,
        "source_rows": (upload.payload or {}).get("source_rows", len(rows)),
        "row_count": upload.row_count,
        "total": upload.total,
        "date_from": min((r.date for r in rows), default=None),
        "date_to": max((r.date for r in rows), default=None),
        "by_category": [
            {"category": name, "amount": amount}
            for name, amount in sorted(by_category.items(), key=lambda kv: -kv[1])
        ],
        "sample": [r.to_json() for r in rows[:PREVIEW_ROWS]],
        "unmatched": unmatched,
        "new_cost_centers": new_cost_centers,
        "replaces": replaces,
    }


def get_description(db: Session, user: User, upload_id: int) -> dict:
    return describe(db, user, _get_upload(db, user, upload_id))


def confirm_upload(db: Session, user: User, upload_id: int) -> Upload:
    """Подтверждает загрузку: записывает данные или ставит в очередь на сопоставление."""
    upload = _get_upload(db, user, upload_id)
    if upload.status not in _OPEN_STATUSES:
        raise ConflictError("Загрузка уже обработана")
    _check_source_permission(user, upload.source)

    rows = _rows_of(upload)
    resolver = reference.CategoryResolver(db, user.org_id)
    if any(resolver.resolve(row.category) is None for row in rows):
        upload.status = UploadStatus.PENDING_MAPPING
        db.commit()
        return upload
    _activate(db, user, upload, rows, resolver)
    return upload


def apply_mapping(
    db: Session, user: User, upload_id: int, mapping: Mapping[str, Mapping]
) -> Upload:
    """Сопоставляет статьи из файла с категориями и, если всё сопоставлено, пишет данные.

    mapping: {"название из файла": {"category_id": 5} | {"new_name": "Новая категория"}}
    """
    if not has_permission(user.role, Permission.REFERENCE_MANAGE):
        raise PermissionDeniedError("Сопоставлять статьи может руководитель или администратор")
    upload = _get_upload(db, user, upload_id)
    if upload.status not in _OPEN_STATUSES:
        raise ConflictError("Загрузка уже обработана")

    categories = CategoryRepository(db, user.org_id)
    for source_name, target in mapping.items():
        if target.get("category_id"):
            category = categories.get(int(target["category_id"]))
            if category is None:
                raise NotFoundError(f"Категория для статьи «{source_name}» не найдена")
        else:
            new_name = target.get("new_name") or source_name
            category = reference.build_item(db, user.org_id, "category", new_name)
            log_action(db, user, "create", "category", category.id, {"name": category.name})
        if normalize_name(category.name) != normalize_name(source_name):
            reference.build_alias(db, user.org_id, source_name, category.id)
            log_action(
                db, user, "create", "category_alias", None,
                {"alias": source_name, "category": category.name},
            )  # fmt: skip
    db.flush()

    rows = _rows_of(upload)
    resolver = reference.CategoryResolver(db, user.org_id)
    if any(resolver.resolve(row.category) is None for row in rows):
        upload.status = UploadStatus.PENDING_MAPPING
        db.commit()
    else:
        _activate(db, user, upload, rows, resolver)
    return upload


def cancel_upload(db: Session, user: User, upload_id: int) -> Upload:
    """Отменяет черновик либо снимает с учёта уже записанную загрузку."""
    upload = _get_upload(db, user, upload_id)
    if upload.status in _OPEN_STATUSES:
        _check_source_permission(user, upload.source)
    elif upload.status == UploadStatus.ACTIVE:
        if not has_permission(user.role, Permission.REFERENCE_MANAGE):
            raise PermissionDeniedError(
                "Отменять записанные загрузки может руководитель или администратор"
            )
        if upload.kind == UploadKind.FACT:
            ExpenseRepository(db, user.org_id).deactivate_upload(upload.id)
        log_action(
            db, user, "delete", "upload", upload.id,
            {"kind": upload.kind, "version": upload.version},
        )  # fmt: skip
    else:
        raise ConflictError("Загрузка уже отменена или заменена")
    upload.status = UploadStatus.CANCELLED
    db.commit()
    return upload


def _cost_center_ids(db: Session, org_id: int, rows: list[ParsedRow]) -> dict[str, int]:
    """Возвращает id ЦФО по нормализованному названию; неизвестные ЦФО создаёт."""
    ids = {normalize_name(c.name): c.id for c in CostCenterRepository(db, org_id).list()}
    for row in rows:
        if row.cost_center and normalize_name(row.cost_center) not in ids:
            item = reference.build_item(db, org_id, "cost_center", row.cost_center)
            ids[normalize_name(item.name)] = item.id
    return ids


def _activate(db: Session, user: User, upload: Upload, rows: list[ParsedRow], resolver) -> None:
    org_id = user.org_id
    uploads = UploadRepository(db, org_id)
    cost_centers = _cost_center_ids(db, org_id, rows)
    details: dict = {"kind": upload.kind, "source": upload.source}

    def common(row: ParsedRow) -> dict:
        return {
            "org_id": org_id,
            "upload_id": upload.id,
            "date": row.date,
            "grain": row.grain,
            "category_id": resolver.resolve(row.category),
            "cost_center_id": cost_centers[normalize_name(row.cost_center)]
            if row.cost_center
            else None,
            "amount": row.amount,
        }

    if upload.kind == UploadKind.FACT:
        expenses = ExpenseRepository(db, org_id)
        if upload.source != MANUAL:
            # Файл заменяет факт за свои календарные месяцы; ручной ввод только добавляет
            touched = expenses.deactivate_in(covered_months(rows))
            for other in touched:
                if not expenses.has_active(other):
                    uploads.get(other).status = UploadStatus.SUPERSEDED
            details["superseded_uploads"] = sorted(touched)
        db.add_all(ExpenseRecord(**common(row), source=upload.source) for row in rows)
    else:
        lines = [BudgetLine(**common(row)) for row in rows]
        if upload.source == MANUAL:
            # Версия бюджета — цельный снимок: ручные строки дополняют копию последней версии
            versions = uploads.budget_versions()
            if versions:
                previous = BudgetRepository(db, org_id).for_upload(versions[0].id)
                lines += [
                    BudgetLine(
                        org_id=org_id, upload_id=upload.id, date=p.date, grain=p.grain,
                        category_id=p.category_id, cost_center_id=p.cost_center_id,
                        amount=p.amount,
                    )
                    for p in previous
                ]  # fmt: skip
                details["based_on_version"] = versions[0].version
        db.add_all(lines)
        upload.row_count = len(lines)
        upload.total = sum((line.amount for line in lines), Decimal("0"))

    upload.version = uploads.next_version(upload.kind)
    upload.status = UploadStatus.ACTIVE
    details |= {"version": upload.version, "rows": upload.row_count, "total": str(upload.total)}
    log_action(db, user, "create", "upload", upload.id, details)
    db.commit()
