"""Страница анализа: динамика расходов за длительный период на одной диаграмме."""

from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from starlette.datastructures import QueryParams

from app.api.charts import CHART_NAME, figure_for
from app.db import get_db
from app.deps import require
from app.errors import AppError, InvalidDataError
from app.models import User
from app.permissions import Permission
from app.repositories.reference import CategoryRepository
from app.services import analysis, analytics, charts, prompts
from app.services.periods import GRANULARITIES, month_end
from app.services.settings import get_org_settings
from app.web.common import can, render

router = APIRouter()
_viewer = require(Permission.ANALYTICS_VIEW)
STEPS = {"day": "Дни", "month": "Месяцы", "quarter": "Кварталы", "year": "Годы"}
DEFAULT_PRESET = "12 месяцев"


def read_int(params: QueryParams, name: str) -> int | None:
    value = (params.get(name) or "").strip()
    return int(value) if value.isdigit() else None


def _months_back(day: date, months: int) -> date:
    """Первое число месяца, отстоящего на months месяцев назад."""
    index = day.year * 12 + day.month - 1 - months
    return date(index // 12, index % 12 + 1, 1)


def presets(bounds: dict, today: date | None = None) -> list[dict]:
    """Быстрые периоды. «N месяцев» отсчитываются от последнего месяца с данными."""
    today = today or date.today()
    last = date.fromisoformat(bounds["fact_to"]) if bounds.get("fact_to") else today
    end = month_end(last)
    items = [
        ("12 месяцев", _months_back(end, 11), end),
        ("24 месяца", _months_back(end, 23), end),
        ("Текущий год", date(today.year, 1, 1), date(today.year, 12, 31)),
        ("Прошлый год", date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)),
    ]
    if bounds.get("fact_from"):
        items.append(("Все данные", date.fromisoformat(bounds["fact_from"]).replace(day=1), end))
    return [
        {"label": label, "start": start.isoformat(), "end": finish.isoformat()}
        for label, start, finish in items
    ]


def read_params(params) -> dict:
    """Параметры анализа из полей формы (общие для диаграммы и сохранения анализа)."""
    start, end = (params.get("date_from") or "").strip(), (params.get("date_to") or "").strip()
    if not start or not end:
        raise InvalidDataError("Укажите начало и конец периода")
    step = params.get("step") or "month"
    return {
        "period": f"{start}..{end}",
        "granularity": step if step in GRANULARITIES else "month",
        "budget_upload_id": read_int(params, "budget_upload_id"),
        "categories": [c for c in params.getlist("categories") if c],
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
    options = presets(bounds)
    context = {
        "bounds": bounds,
        "presets": options,
        "selected": next(p for p in options if p["label"] == DEFAULT_PRESET),
        "steps": STEPS,
        "categories": CategoryRepository(db, user.org_id).list(),
    }
    return render(request, "dashboard.html", context, user)


@router.get("/dashboard/result")
def dashboard_result(
    request: Request, user: User = Depends(_viewer), db: Session = Depends(get_db)
):
    try:
        query = read_params(request.query_params)
        data = analysis.run_fact_budget(db, user, **query)
        figure = figure_for(db, user, data)
    except AppError as exc:
        return render(request, "partials/alert.html", {"message": exc.message}, user)
    link = {k: v for k, v in query.items() if v not in (None, "", [])} | {"format": "png"}
    context = {
        "chart": {
            "figure": charts.figure_json(figure),
            "png_url": f"/api/charts/{CHART_NAME}?{urlencode(link, doseq=True)}",
        },
        "kpi": analytics.summarize(data),
        "no_budget_by_day": query["granularity"] == "day",
        "ai": ai_context(db, user),
    }
    return render(request, "partials/dynamics_result.html", context, user)
