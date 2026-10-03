import json
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import csrf_protect, require
from app.models import User
from app.permissions import Permission
from app.services import charts, dashboards
from app.services.audit import log_action

router = APIRouter(prefix="/charts", tags=["charts"], dependencies=[Depends(csrf_protect)])


@router.get("/{name}")
def chart(
    name: str,
    period: str = Query(..., description="Период, как в /api/analytics"),
    format: str = Query("json", pattern="^(json|png)$"),
    granularity: str = Query("month", description="Только для stacked: day, month, quarter, year"),
    budget_upload_id: int | None = Query(None, description="Только для plan-fact"),
    cost_center_id: int | None = None,
    categories: list[str] | None = Query(None, description="Показывать только эти категории"),
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    user: User = Depends(require(Permission.ANALYTICS_VIEW)),
    db: Session = Depends(get_db),
):
    """Диаграмма: pie (доли категорий), stacked (по периодам), plan-fact.

    format=json — фигура Plotly, format=png — картинка для презентаций.
    """
    params: dict = {
        "period": period,
        "cost_center_id": cost_center_id,
        "chart_filter": dashboards.ChartFilter(categories or [], amount_min, amount_max),
    }
    if name == "stacked":
        params["granularity"] = granularity
    if name == "plan-fact":
        params["budget_upload_id"] = budget_upload_id
    figure = dashboards.build_chart(db, user, name, **params)
    if format == "json":
        return json.loads(charts.figure_json(figure))
    log_action(
        db, user, "export", "chart", None, {"chart": name, "period": period, "format": "png"}
    )
    db.commit()
    headers = {"Content-Disposition": f'attachment; filename="{name}.png"'}
    return Response(charts.figure_png(figure), media_type="image/png", headers=headers)
