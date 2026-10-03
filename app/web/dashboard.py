"""Дашборд: сравнение периодов и план-факт с диаграммами."""

from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from starlette.datastructures import QueryParams

from app.db import get_db
from app.deps import require
from app.errors import AppError, InvalidDataError
from app.models import User
from app.permissions import Permission
from app.repositories.reference import CategoryRepository, CostCenterRepository
from app.services import analysis, charts, dashboards, prompts
from app.services.analytics import ChangeType
from app.services.periods import GRANULARITIES, parse_range
from app.services.settings import get_org_settings
from app.web import period_form
from app.web.common import LABELS, can, render

router = APIRouter()
_viewer = require(Permission.ANALYTICS_VIEW)


def _int(params: QueryParams, name: str) -> int | None:
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


def _chart_filter(params: QueryParams) -> dashboards.ChartFilter:
    return dashboards.ChartFilter(
        [c for c in params.getlist("chart_categories") if c],
        _decimal(params, "amount_min", "Сумма от"),
        _decimal(params, "amount_max", "Сумма до"),
    )


def read_comparison_params(params) -> dict:
    """Параметры сравнения из полей формы (общие для расчёта и сохранения анализа)."""
    granularity = params.get("granularity") or "month"
    return {
        "period1": period_form.compose(params, "p1"),
        "period2": period_form.compose(params, "p2"),
        "cost_center_id": _int(params, "cost_center_id"),
        "category": params.get("category") or None,
        "change_types": params.getlist("change_type") or None,
        "sort": params.get("sort") or "delta",
        "descending": params.get("order", "desc") != "asc",
        "granularity": granularity if granularity in GRANULARITIES else "month",
    }


def read_plan_fact_params(params) -> dict:
    return {
        "period": period_form.compose(params, "p"),
        "budget_upload_id": _int(params, "budget_upload_id"),
        "by_cost_center": params.get("by_cost_center") == "on",
        "cost_center_id": _int(params, "cost_center_id"),
        "threshold_pct": _decimal(params, "threshold_pct", "Порог"),
    }


def ai_context(db: Session, user: User, kind: str) -> dict | None:
    """Данные панели AI-анализа; None — если у пользователя нет права."""
    if not can(user, Permission.AI_RUN):
        return None
    return {
        "kind": kind,
        "templates": prompts.list_templates(db, user.org_id, only_active=True),
        "auto": get_org_settings(db, user.org_id).ai_auto_run,
    }


def _chart(figure, name: str, query: dict) -> dict:
    """Данные для шаблона: фигура Plotly и ссылка на PNG с теми же параметрами."""
    clean = {k: v for k, v in query.items() if v not in (None, "", [])}
    return {
        "figure": charts.figure_json(figure),
        "png_url": f"/api/charts/{name}?{urlencode(clean | {'format': 'png'}, doseq=True)}",
    }


def _form_context(db: Session, user: User, prefixes: tuple[str, ...]) -> dict:
    bounds = analysis.data_bounds(db, user)
    return {
        **period_form.CONTEXT,
        "bounds": bounds,
        "years": period_form.years(bounds),
        "values": period_form.defaults(bounds, prefixes),
        "categories": CategoryRepository(db, user.org_id).list(),
        "cost_centers": CostCenterRepository(db, user.org_id).list(),
    }


@router.get("/dashboard")
def dashboard_page(request: Request, user: User = Depends(_viewer), db: Session = Depends(get_db)):
    context = _form_context(db, user, ("p1", "p2")) | {
        "change_types": {t.value: LABELS[t.value] for t in ChangeType},
    }
    return render(request, "dashboard.html", context, user)


@router.get("/dashboard/result")
def dashboard_result(
    request: Request, user: User = Depends(_viewer), db: Session = Depends(get_db)
):
    params = request.query_params
    try:
        query = read_comparison_params(params)
        period1, period2, cost_center_id = (
            query["period1"],
            query["period2"],
            query["cost_center_id"],
        )
        granularity = query.pop("granularity")
        result = analysis.run_comparison(
            db, user, query.pop("period1"), query.pop("period2"), **query
        )
        chart_filter = _chart_filter(params)
        common = {
            "cost_center_id": cost_center_id,
            "categories": chart_filter.categories,
            "amount_min": chart_filter.amount_min,
            "amount_max": chart_filter.amount_max,
        }
        pies = [
            _chart(
                dashboards.pie_chart(db, user, period, cost_center_id, chart_filter),
                "pie",
                common | {"period": period},
            )
            for period in (period1, period2)
        ]
        # Общий график — от начала раннего периода до конца позднего
        ranges = [parse_range(period1), parse_range(period2)]
        span = f"{min(r.start for r in ranges)}..{max(r.end for r in ranges)}"
        stacked = _chart(
            dashboards.stacked_chart(db, user, span, granularity, cost_center_id, chart_filter),
            "stacked",
            common | {"period": span, "granularity": granularity},
        )
    except AppError as exc:
        return render(request, "partials/alert.html", {"message": exc.message}, user)
    context = {
        "result": result,
        "pies": pies,
        "stacked": stacked,
        "ai": ai_context(db, user, "comparison"),
    }
    return render(request, "partials/comparison_result.html", context, user)


@router.get("/plan-fact")
def plan_fact_page(request: Request, user: User = Depends(_viewer), db: Session = Depends(get_db)):
    context = _form_context(db, user, ("p",))
    return render(request, "plan_fact.html", context, user)


@router.get("/plan-fact/result")
def plan_fact_result(
    request: Request, user: User = Depends(_viewer), db: Session = Depends(get_db)
):
    params = request.query_params
    try:
        query = read_plan_fact_params(params)
        period, cost_center_id, budget_upload_id = (
            query["period"],
            query["cost_center_id"],
            query["budget_upload_id"],
        )
        result = analysis.run_plan_fact(db, user, query.pop("period"), **query)
        chart_filter = _chart_filter(params)
        chart = _chart(
            dashboards.plan_fact_chart(
                db, user, period, budget_upload_id, cost_center_id, chart_filter
            ),
            "plan-fact",
            {
                "period": period,
                "budget_upload_id": budget_upload_id,
                "cost_center_id": cost_center_id,
                "categories": chart_filter.categories,
                "amount_min": chart_filter.amount_min,
                "amount_max": chart_filter.amount_max,
            },
        )
    except AppError as exc:
        return render(request, "partials/alert.html", {"message": exc.message}, user)
    return render(
        request, "partials/plan_fact_result.html", {"result": result, "chart": chart}, user
    )
