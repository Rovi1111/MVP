from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import csrf_protect, require
from app.models import User
from app.permissions import Permission
from app.services import analysis

router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(csrf_protect)])
_viewer = require(Permission.ANALYTICS_VIEW)
_PERIOD_DOC = (
    "День 2025-01-15, месяц 2025-01, квартал 2025-Q1, год 2025 или диапазон 2025-01-10..2025-02-20"
)


@router.get("/comparison")
def comparison(
    period1: str = Query(..., description=_PERIOD_DOC),
    period2: str = Query(..., description=_PERIOD_DOC),
    cost_center_id: int | None = None,
    category: str | None = Query(None, description="Часть названия категории"),
    change_type: list[str] | None = Query(
        None, description="increase, decrease, new, removed, no_change"
    ),
    sort: str = "delta",
    order: str = Query("desc", pattern="^(asc|desc)$"),
    user: User = Depends(_viewer),
    db: Session = Depends(get_db),
):
    return analysis.run_comparison(
        db,
        user,
        period1,
        period2,
        cost_center_id=cost_center_id,
        category=category,
        change_types=change_type,
        sort=sort,
        descending=order == "desc",
    )


@router.get("/plan-fact")
def plan_fact(
    period: str = Query(..., description=_PERIOD_DOC),
    budget_upload_id: int | None = Query(
        None, description="Версия бюджета; по умолчанию последняя"
    ),
    by_cost_center: bool = False,
    cost_center_id: int | None = None,
    threshold_pct: Decimal | None = Query(
        None, ge=0, description="Порог существенного отклонения, %"
    ),
    user: User = Depends(_viewer),
    db: Session = Depends(get_db),
):
    return analysis.run_plan_fact(
        db,
        user,
        period,
        budget_upload_id=budget_upload_id,
        by_cost_center=by_cost_center,
        cost_center_id=cost_center_id,
        threshold_pct=threshold_pct,
    )


@router.get("/series")
def series(
    period: str = Query(..., description=_PERIOD_DOC),
    granularity: str = Query("month", description="day, month, quarter, year"),
    cost_center_id: int | None = None,
    user: User = Depends(_viewer),
    db: Session = Depends(get_db),
):
    return analysis.run_series(db, user, period, granularity, cost_center_id)


@router.get("/bounds")
def bounds(user: User = Depends(_viewer), db: Session = Depends(get_db)):
    return analysis.data_bounds(db, user)
