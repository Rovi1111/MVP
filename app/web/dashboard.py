"""Страница анализа: сравнение периодов и диаграмма «факт и бюджет»."""

from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from starlette.datastructures import QueryParams

from app.api.charts import CHART_NAME, build_figure
from app.db import get_db
from app.deps import require
from app.errors import AppError, InvalidDataError
from app.models import User
from app.permissions import Permission
from app.repositories.reference import CategoryRepository, CostCenterRepository
from app.services import analysis, charts, prompts
from app.services.analytics import ChangeType
from app.services.periods import parse_range
from app.services.settings import get_org_settings
from app.web import period_form
from app.web.common import LABELS, can, render

router = APIRouter()
_viewer = require(Permission.ANALYTICS_VIEW)


def read_int(params: QueryParams, name: str) -> int | None:
    value = (params.get(name) or "").strip()
    return int(value) if value.isdigit() else None


def _decimal(params: QueryParams, name: str, title: str) -> Decimal | None:
    value = (params.get(name) or "").strip().replace(" ", "").replace(",", ".")
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        raise InvalidDataError(f"{title}: ожидается число") from None


def read_comparison_params(params) -> dict:
    """Параметры анализа из полей формы (общие для расчёта и сохранения анализа)."""
    return {
        "period1": period_form.compose(params, "p1"),
        "period2": period_form.compose(params, "p2"),
        "cost_center_id": read_int(params, "cost_center_id"),
        "category": params.get("category") or None,
        "change_types": params.getlist("change_type") or None,
        "sort": params.get("sort") or "delta",
        "descending": params.get("order", "desc") != "asc",
        "budget_upload_id": read_int(params, "budget_upload_id"),
        "chart_categories": [c for c in params.getlist("chart_categories") if c],
        "amount_min": _decimal(params, "amount_min", "Сумма от"),
        "amount_max": _decimal(params, "amount_max", "Сумма до"),
    }


def ai_context(db: Session, user: User) -> dict | None:
    """Данные панели AI-анализа; None — если у пользователя нет права."""
    if not can(user, Permission.AI_RUN):
        return None
    return {
        "templates": prompts.list_templates(db, user.org_id, only_active=True),
        "auto": get_org_settings(db, user.org_id).ai_auto_run,
    }


@router.get("/dashboard")
def dashboard_page(request: Request, user: User = Depends(_viewer), db: Session = Depends(get_db)):
    bounds = analysis.data_bounds(db, user)
    context = {
        **period_form.CONTEXT,
        "bounds": bounds,
        "years": period_form.years(bounds),
        "values": period_form.defaults(bounds, ("p1", "p2")),
        "categories": CategoryRepository(db, user.org_id).list(),
        "cost_centers": CostCenterRepository(db, user.org_id).list(),
        "change_types": {t.value: LABELS[t.value] for t in ChangeType},
    }
    return render(request, "dashboard.html", context, user)


@router.get("/dashboard/result")
def dashboard_result(
    request: Request, user: User = Depends(_viewer), db: Session = Depends(get_db)
):
    try:
        query = read_comparison_params(request.query_params)
        result = analysis.run_comparison(
            db,
            user,
            query["period1"],
            query["period2"],
            cost_center_id=query["cost_center_id"],
            category=query["category"],
            change_types=query["change_types"],
            sort=query["sort"],
            descending=query["descending"],
        )
        # Диаграмма — от начала раннего периода до конца позднего
        ranges = [parse_range(query["period1"]), parse_range(query["period2"])]
        span = f"{min(r.start for r in ranges)}..{max(r.end for r in ranges)}"
        filters = {
            "cost_center_id": query["cost_center_id"],
            "budget_upload_id": query["budget_upload_id"],
            "categories": query["chart_categories"],
            "amount_min": query["amount_min"],
            "amount_max": query["amount_max"],
        }
        figure = build_figure(db, user, span, **filters)
    except AppError as exc:
        return render(request, "partials/alert.html", {"message": exc.message}, user)
    link = {k: v for k, v in filters.items() if v not in (None, "", [])}
    link |= {"period": span, "format": "png"}
    context = {
        "result": result,
        "chart": {
            "figure": charts.figure_json(figure),
            "png_url": f"/api/charts/{CHART_NAME}?{urlencode(link, doseq=True)}",
        },
        "ai": ai_context(db, user),
    }
    return render(request, "partials/comparison_result.html", context, user)
