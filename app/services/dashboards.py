"""Диаграммы дашборда: данные организации → фигуры Plotly."""

from dataclasses import dataclass, field
from decimal import Decimal

import plotly.graph_objects as go
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import User
from app.repositories.data import ExpenseRepository
from app.repositories.reference import CategoryRepository
from app.services import analysis, analytics, charts
from app.services.periods import GRANULARITIES


@dataclass
class ChartFilter:
    """Отбор данных для диаграмм: категории и диапазон сумм."""

    categories: list[str] = field(default_factory=list)
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None

    def apply(self, totals: dict[str, Decimal]) -> dict[str, Decimal]:
        return analytics.filter_totals(
            totals, self.categories or None, self.amount_min, self.amount_max
        )


def _colors(db: Session, user: User) -> dict[str, str]:
    return charts.colors_for(c.name for c in CategoryRepository(db, user.org_id).list())


def pie_chart(
    db: Session,
    user: User,
    period: str,
    cost_center_id: int | None = None,
    chart_filter: ChartFilter | None = None,
) -> go.Figure:
    """Распределение расходов по категориям за период."""
    selected = analysis.parse_period_arg(period, "Период")
    rows = ExpenseRepository(db, user.org_id).rows(selected.start, selected.end, cost_center_id)
    totals = analytics.sum_by_category((r.category, r.amount) for r in rows)
    totals = (chart_filter or ChartFilter()).apply(totals)
    return charts.pie_figure(analytics.shares(totals), selected.label, _colors(db, user))


def stacked_chart(
    db: Session,
    user: User,
    period: str,
    granularity: str = "month",
    cost_center_id: int | None = None,
    chart_filter: ChartFilter | None = None,
) -> go.Figure:
    """Расходы по периодам с разбивкой по категориям."""
    selected = analysis.parse_period_arg(period, "Период")
    if granularity not in GRANULARITIES:
        granularity = "month"
    rows = ExpenseRepository(db, user.org_id).rows(selected.start, selected.end, cost_center_id)
    totals = analytics.sum_by_category((r.category, r.amount) for r in rows)
    keep = (chart_filter or ChartFilter()).apply(totals).keys()
    series = analytics.series_by_period(
        ((r.date, r.category, r.amount) for r in rows if r.category in keep), granularity
    )
    return charts.stacked_bar_figure(series, f"Расходы: {selected.label}", _colors(db, user))


def plan_fact_chart(
    db: Session,
    user: User,
    period: str,
    budget_upload_id: int | None = None,
    cost_center_id: int | None = None,
    chart_filter: ChartFilter | None = None,
) -> go.Figure:
    result = analysis.run_plan_fact(
        db, user, period, budget_upload_id=budget_upload_id, cost_center_id=cost_center_id
    )
    facts = {row["category"]: Decimal(str(row["fact"])) for row in result["rows"]}
    keep = (chart_filter or ChartFilter()).apply(facts).keys()
    rows = [row for row in result["rows"] if row["category"] in keep]
    return charts.plan_fact_figure(rows, f"План-факт: {result['params']['period']['label']}")


CHARTS = {"pie": pie_chart, "stacked": stacked_chart, "plan-fact": plan_fact_chart}


def build_chart(db: Session, user: User, name: str, **params) -> go.Figure:
    try:
        builder = CHARTS[name]
    except KeyError:
        raise NotFoundError("Неизвестная диаграмма") from None
    return builder(db, user, **params)
