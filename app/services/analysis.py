"""Аналитика поверх БД: загружает данные организации и вызывает чистые расчёты."""

from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy.orm import Session

from app.errors import InvalidDataError, NotFoundError
from app.models import UploadKind, UploadStatus, User
from app.repositories.data import BudgetRepository, DataRow, ExpenseRepository, UploadRepository
from app.repositories.reference import CostCenterRepository
from app.services import analytics
from app.services.periods import (
    GRANULARITIES,
    PeriodError,
    PeriodRange,
    grain_end,
    parse_range,
    whole_buckets,
    whole_months,
)
from app.services.settings import get_org_settings

MAX_DAY_BUCKETS = 400


def parse_period_arg(text: str | None, title: str) -> PeriodRange:
    """Разбирает период из параметров запроса; ошибка — с названием поля."""
    try:
        return parse_range(text)
    except PeriodError as exc:
        raise InvalidDataError(f"{title}: {exc}") from None


def _period_dict(period: PeriodRange) -> dict:
    return {"start": period.start.isoformat(), "end": period.end.isoformat(), "label": period.label}


def _cost_center(db: Session, user: User, cost_center_id: int | None) -> str | None:
    if cost_center_id is None:
        return None
    item = CostCenterRepository(db, user.org_id).get(cost_center_id)
    if item is None:
        raise NotFoundError("ЦФО не найден")
    return item.name


def _coarse_warning(rows: Iterable[DataRow], period: PeriodRange, what: str) -> str | None:
    """Предупреждение, если запись за месяц/квартал попала в период лишь частично."""
    if any(grain_end(row.date, row.grain) > period.end for row in rows):
        return (
            f"{what} за «{period.label}» содержит суммы, введённые за месяц или квартал целиком; "
            "период покрывает их не полностью, поэтому сравнение может быть неточным"
        )
    return None


def run_comparison(
    db: Session,
    user: User,
    period1: str,
    period2: str,
    *,
    cost_center_id: int | None = None,
    category: str | None = None,
    change_types: list[str] | None = None,
    sort: str = "delta",
    descending: bool = True,
) -> dict:
    """Сравнение двух периодов по категориям с фильтрами и сортировкой."""
    p1, p2 = parse_period_arg(period1, "Период 1"), parse_period_arg(period2, "Период 2")
    cost_center = _cost_center(db, user, cost_center_id)
    if sort not in analytics.COMPARISON_SORT_KEYS:
        raise InvalidDataError(
            f"Сортировка возможна по: {', '.join(analytics.COMPARISON_SORT_KEYS)}"
        )

    expenses = ExpenseRepository(db, user.org_id)
    rows1 = expenses.rows(p1.start, p1.end, cost_center_id)
    rows2 = expenses.rows(p2.start, p2.end, cost_center_id)
    try:
        result = analytics.compare_periods(
            ((r.category, r.amount) for r in rows1), ((r.category, r.amount) for r in rows2)
        )
        filtered = analytics.filter_comparison(result.rows, category, change_types)
    except analytics.EmptyPeriodsError:
        raise InvalidDataError(
            f"Нет данных ни за «{p1.label}», ни за «{p2.label}». "
            "Загрузите факт или выберите другие периоды"
        ) from None
    except ValueError:
        raise InvalidDataError("Неизвестный тип изменения в фильтре") from None
    filtered = analytics.sort_rows(filtered, sort, descending)

    data = result.to_dict()
    data["all_rows"] = data["rows"]  # полные данные: для диаграмм и AI-анализа
    data["rows"] = [row.to_dict() for row in filtered]
    data["filtered"] = len(filtered) != len(result.rows)
    warnings = [
        _coarse_warning(rows1, p1, "Факт"),
        _coarse_warning(rows2, p2, "Факт"),
    ]
    return {
        "kind": "comparison",
        "params": {
            "period1": _period_dict(p1),
            "period2": _period_dict(p2),
            "cost_center_id": cost_center_id,
            "cost_center": cost_center,
            "category": category or "",
            "change_types": change_types or [],
            "sort": sort,
            "descending": descending,
        },
        "warnings": [w for w in dict.fromkeys(warnings) if w],
        **data,
    }


def _budget_version(db: Session, user: User, upload_id: int | None):
    uploads = UploadRepository(db, user.org_id)
    if upload_id is None:
        versions = uploads.budget_versions()
        if not versions:
            raise InvalidDataError("Бюджет ещё не загружен — загрузите файл бюджета")
        return versions[0]
    upload = uploads.get(upload_id)
    if upload is None or upload.kind != UploadKind.BUDGET or upload.status != UploadStatus.ACTIVE:
        raise NotFoundError("Версия бюджета не найдена")
    return upload


def run_plan_fact(
    db: Session,
    user: User,
    period: str,
    *,
    budget_upload_id: int | None = None,
    by_cost_center: bool = False,
    cost_center_id: int | None = None,
    threshold_pct: Decimal | None = None,
) -> dict:
    """План-факт за период. Версия бюджета — последняя или указанная."""
    requested = parse_period_arg(period, "Период")
    # Бюджет задаётся не детальнее месяца, поэтому считаем по целым месяцам
    used = whole_months(requested)
    cost_center = _cost_center(db, user, cost_center_id)
    version = _budget_version(db, user, budget_upload_id)
    if threshold_pct is None:
        threshold_pct = get_org_settings(db, user.org_id).plan_fact_threshold

    plan_rows = BudgetRepository(db, user.org_id).rows(
        version.id, used.start, used.end, cost_center_id
    )
    fact_rows = ExpenseRepository(db, user.org_id).rows(used.start, used.end, cost_center_id)
    if not plan_rows and not fact_rows:
        raise InvalidDataError(f"За «{used.label}» нет ни плана, ни факта")
    result = analytics.plan_fact(
        ((r.category, r.cost_center, r.amount) for r in plan_rows),
        ((r.category, r.cost_center, r.amount) for r in fact_rows),
        threshold_pct,
        by_cost_center,
    )
    warnings = [
        f"План-факт считается по целым месяцам: {used.label}" if used != requested else None,
        _coarse_warning(plan_rows, used, "Бюджет"),
        _coarse_warning(fact_rows, used, "Факт"),
    ]
    return {
        "kind": "plan_fact",
        "params": {
            "period": _period_dict(used),
            "budget_upload_id": version.id,
            "budget_version": version.version,
            "by_cost_center": by_cost_center,
            "cost_center_id": cost_center_id,
            "cost_center": cost_center,
        },
        "warnings": [w for w in warnings if w],
        **result.to_dict(),
    }


def run_series(
    db: Session,
    user: User,
    period: str,
    granularity: str = "month",
    cost_center_id: int | None = None,
) -> dict:
    """Суммы по категориям в разрезе дней/месяцев/кварталов/лет."""
    if granularity not in GRANULARITIES:
        raise InvalidDataError(f"Детализация: одно из {', '.join(GRANULARITIES)}")
    selected = parse_period_arg(period, "Период")
    _cost_center(db, user, cost_center_id)
    rows = ExpenseRepository(db, user.org_id).rows(selected.start, selected.end, cost_center_id)
    data = analytics.series_by_period(((r.date, r.category, r.amount) for r in rows), granularity)
    return {"period": _period_dict(selected), **data}


def run_fact_budget(
    db: Session,
    user: User,
    period: str,
    *,
    granularity: str = "month",
    cost_center_id: int | None = None,
    budget_upload_id: int | None = None,
    categories: list[str] | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
) -> dict:
    """Динамика расходов: факт по шагам (день/месяц/квартал/год) и линия бюджета.

    Для шага крупнее дня период расширяется до целых шагов. Отбор по категориям и
    диапазону сумм (сумма категории за весь период) применяется и к факту, и к бюджету.
    Если бюджет не загружен, линии нет, а столбцы факта остаются.
    """
    if granularity not in GRANULARITIES:
        raise InvalidDataError(f"Шаг диаграммы: одно из {', '.join(GRANULARITIES)}")
    selected = whole_buckets(parse_period_arg(period, "Период"), granularity)
    if granularity == "day" and (selected.end - selected.start).days >= MAX_DAY_BUCKETS:
        raise InvalidDataError(
            f"По дням можно показать не больше {MAX_DAY_BUCKETS} дней — "
            "сократите период или выберите шаг «Месяцы»"
        )
    _cost_center(db, user, cost_center_id)
    fact = ExpenseRepository(db, user.org_id).rows(selected.start, selected.end, cost_center_id)
    try:
        version = _budget_version(db, user, budget_upload_id)
    except InvalidDataError:
        version = None
    budget = (
        BudgetRepository(db, user.org_id).rows(
            version.id, selected.start, selected.end, cost_center_id
        )
        if version
        else []
    )
    if categories or amount_min is not None or amount_max is not None:
        totals = analytics.sum_by_category((r.category, r.amount) for r in fact)
        totals |= {r.category: totals.get(r.category, Decimal("0")) for r in budget}
        keep = analytics.filter_totals(totals, categories, amount_min, amount_max).keys()
        fact = [r for r in fact if r.category in keep]
        budget = [r for r in budget if r.category in keep]
    data = analytics.fact_budget_series(
        ((r.date, r.category, r.amount) for r in fact),
        ((r.date, r.grain, r.amount) for r in budget) if version else None,
        selected.start,
        selected.end,
        granularity,
    )
    return {
        "period": _period_dict(selected),
        "budget_version": version.version if version else None,
        "categories": sorted(categories) if categories else [],
        **data,
    }


def data_bounds(db: Session, user: User) -> dict:
    """Границы загруженного факта и версии бюджета — для подсказок в формах."""
    start, end = ExpenseRepository(db, user.org_id).date_bounds()
    return {
        "fact_from": start.isoformat() if start else None,
        "fact_to": end.isoformat() if end else None,
        "budget_versions": [
            {"upload_id": u.id, "version": u.version, "file_name": u.file_name}
            for u in UploadRepository(db, user.org_id).budget_versions()
        ],
    }
