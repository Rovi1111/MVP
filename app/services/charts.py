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
    "#b8860b", "#d1589b", "#5f7285", "#8cb33c", "#1f3a5f", "#f2b632",
]  # fmt: skip
PLAN_COLOR, FACT_COLOR, OVERSPEND_COLOR = "#9aa7b8", "#2456c6", "#c9404d"
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


def pie_figure(shares: list[dict], title: str, colors: dict[str, str] | None = None) -> go.Figure:
    """Круговая диаграмма долей категорий; shares — результат analytics.shares()."""
    if not shares:
        return no_data_figure(title)
    labels = [item["category"] for item in shares]
    colors = colors or colors_for(labels)
    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=[item["amount"] for item in shares],
            marker={"colors": [colors.get(name) for name in labels]},
            textinfo="percent",
            sort=False,
            hovertemplate="%{label}<br>%{value:,.2f} ₽<br>%{percent}<extra></extra>",
        )
    )
    return _layout(fig, title)


def stacked_bar_figure(series: dict, title: str, colors: dict[str, str] | None = None) -> go.Figure:
    """Stacked bar по периодам; series — результат analytics.series_by_period()."""
    if not series["periods"]:
        return no_data_figure(title)
    colors = colors or colors_for(s["category"] for s in series["series"])
    fig = go.Figure()
    for item in series["series"]:
        fig.add_bar(
            name=item["category"],
            x=series["periods"],
            y=item["amounts"],
            customdata=item["shares"],
            marker_color=colors.get(item["category"]),
            hovertemplate=(
                "%{fullData.name}<br>%{x}<br>%{y:,.2f} ₽<br>Доля: %{customdata:.1f}%<extra></extra>"
            ),
        )
    fig.update_xaxes(type="category")
    fig.update_yaxes(gridcolor="#e6e9ee", tickformat=",.0f")
    return _layout(fig, title, barmode="relative")


def plan_fact_figure(rows: list[dict], title: str) -> go.Figure:
    """План и факт по категориям; перерасход сверх порога выделен цветом."""
    totals: dict[str, dict] = {}
    for row in rows:
        item = totals.setdefault(row["category"], {"plan": 0.0, "fact": 0.0, "alert": False})
        item["plan"] += row["plan"]
        item["fact"] += row["fact"]
        item["alert"] = item["alert"] or (row["overspend"] and row["significant"])
    if not totals:
        return no_data_figure(title)
    names = sorted(totals, key=lambda n: -max(totals[n]["plan"], totals[n]["fact"]))
    hover = "%{x}<br>%{fullData.name}: %{y:,.2f} ₽<extra></extra>"
    fig = go.Figure()
    fig.add_bar(
        name="План", x=names, y=[totals[n]["plan"] for n in names],
        marker_color=PLAN_COLOR, hovertemplate=hover,
    )  # fmt: skip
    fig.add_bar(
        name="Факт", x=names, y=[totals[n]["fact"] for n in names],
        marker_color=[OVERSPEND_COLOR if totals[n]["alert"] else FACT_COLOR for n in names],
        hovertemplate=hover,
    )  # fmt: skip
    fig.update_yaxes(gridcolor="#e6e9ee", tickformat=",.0f")
    return _layout(fig, title, barmode="group")


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
