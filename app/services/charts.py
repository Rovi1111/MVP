"""Графики Plotly: построение фигур и экспорт в PNG (kaleido)."""

import tempfile
import threading
from collections.abc import Iterable
from pathlib import Path

import plotly
import plotly.graph_objects as go
import plotly.io as pio

PALETTE = [
    "#2456c6", "#e8833a", "#2a9d6f", "#c9404d", "#7b5cc4", "#17a2b8",
    "#b8860b", "#d1589b", "#5f7285", "#8cb33c", "#4a78d0", "#f2b632",
]  # fmt: skip
BUDGET_COLOR = "#1c2330"
NO_DATA = "Нет данных"

_kaleido_lock = threading.Lock()
_kaleido_ready = False


def colors_for(categories: Iterable[str]) -> dict[str, str]:
    """Постоянный цвет категории: один и тот же на всех диаграммах отчёта."""
    names = sorted(set(categories))
    return {name: PALETTE[i % len(PALETTE)] for i, name in enumerate(names)}


def _layout(fig: go.Figure, title: str, **extra) -> go.Figure:
    fig.update_layout(
        title={"text": title, "x": 0.5},
        font={"family": "Arial, Helvetica, sans-serif", "size": 13},
        separators=", ",  # русский формат чисел: 1 234,56
        margin={"l": 50, "r": 30, "t": 60, "b": 50},
        paper_bgcolor="white",
        plot_bgcolor="white",
        **extra,
    )
    return fig


def no_data_figure(title: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=NO_DATA, showarrow=False, font={"size": 22, "color": "#6b7482"})
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _layout(fig, title)


def fact_budget_figure(data: dict, title: str, colors: dict[str, str] | None = None) -> go.Figure:
    """Факт по месяцам (столбцы с накоплением по категориям) и линия бюджета.

    data — результат analytics.fact_budget_series().
    """
    has_fact = any(data["totals"])
    has_budget = bool(data.get("budget")) and any(data["budget"])
    if not has_fact and not has_budget:
        return no_data_figure(title)
    colors = colors or colors_for(s["category"] for s in data["series"])
    fig = go.Figure()
    for item in data["series"]:
        fig.add_bar(
            name=item["category"],
            x=data["periods"],
            y=item["amounts"],
            customdata=item["shares"],
            marker_color=colors.get(item["category"]),
            hovertemplate=(
                "%{fullData.name}<br>%{x}<br>%{y:,.2f} ₽<br>Доля: %{customdata:.1f}%<extra></extra>"
            ),
        )
    if data.get("budget") is not None:
        fig.add_scatter(
            name="Бюджет",
            x=data["periods"],
            y=data["budget"],
            mode="lines+markers",
            line={"color": BUDGET_COLOR, "width": 3},
            marker={"size": 8},
            hovertemplate="Бюджет<br>%{x}<br>%{y:,.2f} ₽<extra></extra>",
        )
    fig.update_xaxes(type="category")
    if data.get("granularity", "month") == "month":
        # Короткие подписи оси («янв 2025»), чтобы 24 месяца читались; в подсказке — полные
        short = [f"{name[:3]} {year}" for name, year in (p.rsplit(" ", 1) for p in data["periods"])]
        fig.update_xaxes(tickmode="array", tickvals=data["periods"], ticktext=short)
    fig.update_yaxes(gridcolor="#e6e9ee", tickformat=",.0f", rangemode="tozero")
    return _layout(fig, title, barmode="relative")


def figure_json(fig: go.Figure) -> str:
    return fig.to_json()


def _prepare_kaleido() -> None:
    """kaleido 0.2.1 не запускается, если путь к пакетам содержит пробел
    (например, «Application Support»): его скрипт запуска не экранирует пути.
    Обход — ссылки без пробелов во временном каталоге."""
    global _kaleido_ready
    if _kaleido_ready:
        return
    from kaleido.scopes.base import BaseScope

    executable = Path(BaseScope.executable_path())
    plotlyjs = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
    if " " in str(executable) or " " in str(plotlyjs):
        links = Path(tempfile.gettempdir()) / "expense-tracker-kaleido"
        links.mkdir(exist_ok=True)
        for name, target in (("exec", executable.parent), ("plotly.min.js", plotlyjs)):
            link = links / name
            if link.is_symlink():
                link.unlink()
            link.symlink_to(target)
        BaseScope.executable_path = classmethod(lambda cls: str(links / "exec" / executable.name))
        pio.kaleido.scope.plotlyjs = str(links / "plotly.min.js")
    _kaleido_ready = True


def figure_png(fig: go.Figure, width: int = 1000, height: int = 600, scale: float = 2) -> bytes:
    """PNG для презентаций и PDF. Kaleido — один процесс, поэтому вызовы по очереди."""
    with _kaleido_lock:
        _prepare_kaleido()
        return fig.to_image(format="png", width=width, height=height, scale=scale)
