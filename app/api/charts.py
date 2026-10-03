import json
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import csrf_protect, require
from app.errors import NotFoundError
from app.models import User
from app.permissions import Permission
from app.repositories.reference import CategoryRepository
from app.services import analysis, charts
from app.services.audit import log_action

router = APIRouter(prefix="/charts", tags=["charts"], dependencies=[Depends(csrf_protect)])
CHART_NAME = "fact-budget"


def build_figure(db: Session, user: User, period: str, **filters):
    """Единственная диаграмма сервиса: динамика факта (с накоплением) и линия бюджета."""
    data = analysis.run_fact_budget(db, user, period, **filters)
    colors = charts.colors_for(c.name for c in CategoryRepository(db, user.org_id).list())
    return charts.fact_budget_figure(data, f"Факт и бюджет: {data['period']['label']}", colors)


@router.get("/{name}")
def chart(
    name: str,
    period: str = Query(
        ..., description="Период, как в /api/analytics; расширяется до целых шагов"
    ),
    format: str = Query("json", pattern="^(json|png)$"),
    granularity: str = Query("month", description="Шаг: day, month, quarter, year"),
    budget_upload_id: int | None = Query(
        None, description="Версия бюджета; по умолчанию последняя"
    ),
    cost_center_id: int | None = None,
    categories: list[str] | None = Query(None, description="Показывать только эти категории"),
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    user: User = Depends(require(Permission.ANALYTICS_VIEW)),
    db: Session = Depends(get_db),
):
    """Диаграмма fact-budget: динамика фактических расходов и линия бюджета.

    format=json — фигура Plotly, format=png — картинка для презентаций.
    """
    if name != CHART_NAME:
        raise NotFoundError("Неизвестная диаграмма")
    figure = build_figure(
        db,
        user,
        period,
        granularity=granularity,
        cost_center_id=cost_center_id,
        budget_upload_id=budget_upload_id,
        categories=categories,
        amount_min=amount_min,
        amount_max=amount_max,
    )
    if format == "json":
        return json.loads(charts.figure_json(figure))
    log_action(
        db, user, "export", "chart", None, {"chart": name, "period": period, "format": "png"}
    )
    db.commit()
    headers = {"Content-Disposition": f'attachment; filename="{name}.png"'}
    return Response(charts.figure_png(figure), media_type="image/png", headers=headers)
