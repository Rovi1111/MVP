import html
import json
import re
from datetime import date
from decimal import Decimal as D

import pytest

from app.services import charts
from app.services.analytics import compare_halves, fact_budget_series, filter_totals
from app.services.periods import PeriodRange, bucket_starts, whole_buckets
from app.web.dashboard import presets
from tests.helpers import load

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
FACT = [
    ("15.11.2024", "Аренда", 90, "Офис"),
    ("15.01.2025", "Аренда", 100, "Офис"),
    ("2025-01", "Реклама", 40, "Офис"),
    ("10.02.2025", "Аренда", 180, "Офис"),
    ("11.02.2025", "Лицензии", 25, "Склад"),
]
BUDGET = [
    ("2024-11", "Аренда", 100),
    ("2025-01", "Аренда", 80),
    ("2025-01", "Реклама", 60),
    ("2025-02", "Аренда", 150),
]
FORM = {"date_from": "2024-11-01", "date_to": "2025-02-28", "step": "month"}


@pytest.fixture
def client(client_for):
    client = client_for("a_admin")
    load(client, "fact", FACT)
    load(client, "budget", BUDGET)
    return client


def embedded_figure(page: str) -> dict:
    """Фигура Plotly, встроенная в страницу в атрибут data-figure."""
    raw = re.search(r'data-figure="([^"]*)"', page).group(1)
    return json.loads(html.unescape(raw))


def traces(figure_json: dict) -> dict:
    return {t["name"]: t["y"] for t in figure_json["data"]}


# ---------- чистые функции ----------


def test_filter_totals():
    totals = {"Аренда": D("100"), "Реклама": D("40"), "ФОТ": D("500")}
    assert filter_totals(totals) == totals
    assert set(filter_totals(totals, ["аренда", "ФОТ"])) == {"Аренда", "ФОТ"}
    assert set(filter_totals(totals, None, D("40"), D("100"))) == {"Аренда", "Реклама"}
    assert filter_totals(totals, ["Аренда"], D("200")) == {}


def test_bucket_starts_and_whole_buckets():
    assert bucket_starts(date(2024, 11, 15), date(2025, 2, 1), "month") == [
        date(2024, 11, 1),
        date(2024, 12, 1),
        date(2025, 1, 1),
        date(2025, 2, 1),
    ]
    assert bucket_starts(date(2024, 11, 15), date(2025, 2, 1), "quarter") == [
        date(2024, 10, 1),
        date(2025, 1, 1),
    ]
    assert bucket_starts(date(2024, 11, 15), date(2025, 2, 1), "year") == [
        date(2024, 1, 1),
        date(2025, 1, 1),
    ]
    assert len(bucket_starts(date(2024, 2, 27), date(2024, 3, 2), "day")) == 5  # високосный год

    period = PeriodRange(date(2024, 11, 15), date(2025, 2, 1), "x")
    assert (whole_buckets(period, "month").start, whole_buckets(period, "month").end) == (
        date(2024, 11, 1),
        date(2025, 2, 28),
    )
    assert whole_buckets(period, "quarter").end == date(2025, 3, 31)
    assert whole_buckets(period, "year").start == date(2024, 1, 1)
    assert whole_buckets(period, "day") is period


def test_fact_budget_series_by_month():
    fact = [
        (date(2025, 1, 15), "A", D("30")),
        (date(2025, 1, 20), "B", D("10")),
        (date(2025, 3, 3), "B", D("5")),
        (date(2025, 6, 1), "A", D("999")),  # вне периода
    ]
    budget = [(date(2025, 1, 1), "month", D("50")), (date(2025, 2, 1), "month", D("20.5"))]
    data = fact_budget_series(fact, budget, date(2025, 1, 1), date(2025, 3, 31))
    assert data["periods"] == [
        "январь 2025",
        "февраль 2025",
        "март 2025",
    ]  # месяц без факта остаётся
    assert data["totals"] == [40.0, 0.0, 5.0]
    assert data["series"][0] == {
        "category": "A",
        "amounts": [30.0, 0.0, 0.0],
        "shares": [75.0, None, 0.0],
    }
    assert data["series"][1]["amounts"] == [10.0, 0.0, 5.0]
    assert data["budget"] == [50.0, 20.5, 0.0]


@pytest.mark.parametrize(
    ("granularity", "periods", "totals", "budget"),
    [
        ("quarter", ["4 кв. 2024", "1 кв. 2025"], [10.0, 35.0], [100.0, 60.0]),
        ("year", ["2024 год", "2025 год"], [10.0, 35.0], [100.0, 60.0]),
    ],
)
def test_fact_budget_series_coarse_steps(granularity, periods, totals, budget):
    fact = [
        (date(2024, 12, 31), "A", D("10")),
        (date(2025, 1, 1), "A", D("30")),
        (date(2025, 3, 5), "B", D("5")),
    ]
    plan = [(date(2024, 10, 1), "quarter", D("100")), (date(2025, 2, 1), "month", D("60"))]
    data = fact_budget_series(fact, plan, date(2024, 10, 1), date(2025, 3, 31), granularity)
    assert (data["periods"], data["totals"], data["budget"]) == (periods, totals, budget)


def test_fact_budget_series_by_day_has_no_budget():
    fact = [(date(2025, 1, 1), "A", D("1")), (date(2025, 1, 3), "A", D("2"))]
    data = fact_budget_series(
        fact, [(date(2025, 1, 1), "month", D("50"))], date(2025, 1, 1), date(2025, 1, 3), "day"
    )
    assert data["periods"] == ["01.01.2025", "02.01.2025", "03.01.2025"]
    assert data["totals"] == [1.0, 0.0, 2.0] and data["budget"] is None


def test_quarter_budget_is_spread_over_months():
    assert fact_budget_series([], None, date(2025, 1, 1), date(2025, 2, 28))["budget"] is None
    quarterly = [(date(2025, 1, 1), "quarter", D("300")), (date(2025, 4, 1), "quarter", D("90"))]
    data = fact_budget_series([], quarterly, date(2025, 2, 1), date(2025, 4, 30))
    assert data["budget"] == [100.0, 100.0, 30.0]  # январь вне периода отброшен


def test_compare_halves():
    series = {
        "periods": ["янв", "фев", "мар", "апр", "май"],
        "series": [
            {"category": "Рост", "amounts": [10.0, 10.0, 99.0, 20.0, 20.0]},
            {"category": "Новая", "amounts": [0.0, 0.0, 0.0, 0.0, 7.0]},
            {"category": "Ушла", "amounts": [5.0, 0.0, 0.0, 0.0, 0.0]},
        ],
    }
    halves = compare_halves(series)
    assert (halves["label_p1"], halves["label_p2"]) == (
        "янв — фев",
        "апр — май",
    )  # средний месяц пропущен
    rows = {r["category"]: r for r in halves["rows"]}
    assert (rows["Рост"]["amount_p1"], rows["Рост"]["amount_p2"], rows["Рост"]["pct_change"]) == (
        20.0,
        40.0,
        100.0,
    )
    assert rows["Новая"]["change_type"] == "new" and rows["Ушла"]["change_type"] == "removed"
    assert compare_halves({"periods": ["янв"], "series": series["series"]}) is None
    assert compare_halves({"periods": ["янв", "фев"], "series": []}) is None


def test_fact_budget_figure():
    data = {
        "periods": ["январь 2025", "февраль 2025"],
        "totals": [40.0, 5.0],
        "series": [{"category": "A", "amounts": [40.0, 5.0], "shares": [100.0, 100.0]}],
        "budget": [50.0, 20.0],
    }
    figure = charts.fact_budget_figure(data, "t")
    assert figure.layout.barmode == "relative"
    assert [(t.type, t.name) for t in figure.data] == [("bar", "A"), ("scatter", "Бюджет")]
    assert "Доля" in figure.data[0].hovertemplate and list(figure.data[1].y) == [50.0, 20.0]
    assert [t.type for t in charts.fact_budget_figure(data | {"budget": None}, "t").data] == ["bar"]
    empty = charts.fact_budget_figure(
        {"periods": ["я"], "totals": [0.0], "series": [], "budget": None}, "t"
    )
    assert not empty.data and empty.layout.annotations[0].text == "Нет данных"


def test_colors_are_stable_between_charts():
    assert charts.colors_for(["Б", "А"]) == charts.colors_for(["А", "Б", "А"])


def test_png_export():
    png = charts.figure_png(charts.no_data_figure("t"), width=300, height=200, scale=1)
    assert png.startswith(PNG_SIGNATURE)


def test_presets():
    bounds = {"fact_from": "2024-03-10", "fact_to": "2025-06-25"}
    items = {p["label"]: (p["start"], p["end"]) for p in presets(bounds, today=date(2026, 10, 3))}
    assert items == {
        "12 месяцев": ("2024-07-01", "2025-06-30"),  # от последнего месяца с данными
        "24 месяца": ("2023-07-01", "2025-06-30"),
        "Текущий год": ("2026-01-01", "2026-12-31"),
        "Прошлый год": ("2025-01-01", "2025-12-31"),
        "Все данные": ("2024-03-01", "2025-06-30"),
    }
    no_data = [
        p["label"] for p in presets({"fact_from": None, "fact_to": None}, today=date(2026, 1, 5))
    ]
    assert "Все данные" not in no_data and no_data[0] == "12 месяцев"


# ---------- API ----------


def test_chart_api_steps(client):
    params = {"period": "2024-11..2025-02"}
    monthly = client.get("/api/charts/fact-budget", params=params).json()
    assert traces(monthly) == {
        "Аренда": [90.0, 0.0, 100.0, 180.0],
        "Реклама": [0.0, 0.0, 40.0, 0.0],
        "Лицензии": [0.0, 0.0, 0.0, 25.0],
        "Бюджет": [100.0, 0.0, 140.0, 150.0],
    }
    assert monthly["data"][0]["x"] == ["ноябрь 2024", "декабрь 2024", "январь 2025", "февраль 2025"]
    assert monthly["data"][-1]["type"] == "scatter"

    quarterly = client.get(
        "/api/charts/fact-budget", params=params | {"granularity": "quarter"}
    ).json()
    assert quarterly["data"][0]["x"] == ["4 кв. 2024", "1 кв. 2025"]
    assert traces(quarterly)["Бюджет"] == [100.0, 290.0] and traces(quarterly)["Аренда"] == [
        90.0,
        280.0,
    ]

    yearly = client.get("/api/charts/fact-budget", params=params | {"granularity": "year"}).json()
    assert traces(yearly)["Аренда"] == [90.0, 280.0]

    daily = client.get(
        "/api/charts/fact-budget", params={"period": "2025-02-09..2025-02-12", "granularity": "day"}
    ).json()
    assert traces(daily) == {"Аренда": [0.0, 180.0, 0.0, 0.0], "Лицензии": [0.0, 0.0, 25.0, 0.0]}

    too_long = client.get(
        "/api/charts/fact-budget", params={"period": "2023..2025", "granularity": "day"}
    )
    assert too_long.status_code == 422 and "не больше" in too_long.json()["detail"]
    assert (
        client.get("/api/charts/fact-budget", params=params | {"granularity": "week"}).status_code
        == 422
    )


def test_chart_api_filters(client):
    only = client.get(
        "/api/charts/fact-budget", params={"period": "2025-01", "categories": ["Реклама"]}
    ).json()
    assert traces(only) == {"Реклама": [40.0], "Бюджет": [60.0]}
    ranged = client.get(
        "/api/charts/fact-budget", params={"period": "2025-01", "amount_min": 50}
    ).json()
    assert [t["name"] for t in ranged["data"]] == ["Аренда", "Бюджет"]
    centers = {c["name"]: c["id"] for c in client.get("/api/cost-centers").json()}
    warehouse = client.get(
        "/api/charts/fact-budget", params={"period": "2025-02", "cost_center_id": centers["Склад"]}
    ).json()
    assert traces(warehouse) == {"Лицензии": [25.0], "Бюджет": [0.0]}
    empty = client.get("/api/charts/fact-budget", params={"period": "2030-01"}).json()
    assert empty["data"] == [] and empty["layout"]["annotations"][0]["text"] == "Нет данных"
    for removed in ("pie", "stacked", "plan-fact"):
        assert client.get(f"/api/charts/{removed}", params={"period": "2025-01"}).status_code == 404


def test_chart_budget_version_and_no_budget(client, client_for):
    load(client, "budget", [("2025-01", "Аренда", 500)])
    latest = client.get("/api/charts/fact-budget", params={"period": "2025-01"}).json()
    assert latest["data"][-1]["y"] == [500.0]
    first = client.get("/api/analytics/bounds").json()["budget_versions"][-1]["upload_id"]
    old = client.get(
        "/api/charts/fact-budget", params={"period": "2025-01", "budget_upload_id": first}
    ).json()
    assert old["data"][-1]["y"] == [140.0]

    other = client_for("b_admin")
    load(other, "fact", [("2025-01", "Аренда", 10)])
    no_budget = other.get("/api/charts/fact-budget", params={"period": "2025-01"}).json()
    assert [t["type"] for t in no_budget["data"]] == ["bar"]  # бюджета нет — только факт


def test_chart_api_png_download(client):
    response = client.get("/api/charts/fact-budget", params={"period": "2025-01", "format": "png"})
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert response.content.startswith(PNG_SIGNATURE)
    assert "attachment" in response.headers["content-disposition"]


# ---------- страница ----------


def test_dashboard_page(client):
    page = client.get("/web/dashboard")
    assert page.status_code == 200 and "Анализ расходов" in page.text
    for text in (
        "12 месяцев",
        "24 месяца",
        "Все данные",
        "Шаг диаграммы",
        "Версия бюджета",
        "Статьи расходов",
    ):
        assert text in page.text
    # по умолчанию — последние 12 месяцев с данными
    assert (
        'name="date_from" value="2024-03-01"' in page.text
        and 'name="date_to" value="2025-02-28"' in page.text
    )
    assert 'value="Реклама"' in page.text
    assert "Организация А" not in page.text  # название организации в меню не выводится
    for removed in ("Период 1", "Тип изменения", "ЦФО", "Сравнить"):
        assert removed not in page.text


def test_dashboard_result_is_single_chart(client):
    result = client.get("/web/dashboard/result", params=FORM)
    assert result.status_code == 200
    assert result.text.count('class="chart"') == 1 and "<table" not in result.text
    # карточки с итогами: факт 435, бюджет 390, перерасход 45 (+11,5 %)
    for text in ("Факт за период", "435,00", "390,00", "+45,00", "+11,5", "перерасход"):
        assert text in result.text
    assert "Скачать PNG" in result.text and "Запустить AI-анализ" in result.text
    assert "period=2024-11-01..2025-02-28&amp;granularity=month&amp;format=png" in result.text
    figure = embedded_figure(result.text)
    assert figure["data"][0]["x"][0] == "ноябрь 2024" and "Бюджет" in traces(figure)

    filtered = client.get(
        "/web/dashboard/result", params=FORM | {"categories": ["Реклама", "Лицензии"]}
    )
    assert set(traces(embedded_figure(filtered.text))) == {"Реклама", "Лицензии", "Бюджет"}
    assert "categories=%D0%A0" in filtered.text  # фильтр попадает и в ссылку на PNG
    by_day = client.get("/web/dashboard/result", params=FORM | {"step": "day"})
    assert "По дням бюджет не показывается" in by_day.text
    assert (
        "при шаге «дни» не считается" in by_day.text and "Отклонение от бюджета" not in by_day.text
    )
    empty = client.get(
        "/web/dashboard/result", params={"date_from": "2019-01-01", "date_to": "2019-12-31"}
    )
    assert embedded_figure(empty.text)["layout"]["annotations"][0]["text"] == "Нет данных"
    missing = client.get("/web/dashboard/result", params={"date_from": "", "date_to": ""})
    assert "Укажите начало и конец периода" in missing.text
    reversed_range = client.get(
        "/web/dashboard/result", params={"date_from": "2025-02-01", "date_to": "2025-01-01"}
    )
    assert "Начало периода позже конца" in reversed_range.text


def test_sidebar_navigation_and_removed_pages(client, client_for):
    home = client.get("/web/")
    assert home.status_code == 303 and home.headers["location"] == "/web/dashboard"
    assert client.get("/web/plan-fact").status_code == 404

    page = client.get("/web/dashboard").text
    assert '<aside class="sidebar">' in page and "Главная" not in page and "План-факт" not in page
    assert 'href="/web/dashboard" class="active"' in page
    assert "<aside" not in client_for().get("/web/login").text


def test_empty_states(client_for):
    client = client_for("b_admin")
    dashboard = client.get("/web/dashboard").text
    assert "Данных пока нет" in dashboard and 'href="/web/data">Загрузить данные' in dashboard
    assert 'id="analysis-form"' not in dashboard
    assert "Загрузить первый файл" in client.get("/web/uploads").text
    assert "Сохранённых анализов пока нет" in client.get("/web/analyses").text


def test_branding_and_collapsible_menu(client):
    page = client.get("/web/dashboard").text
    assert (
        'class="logo"' in page and "/static/logo.png?v=" in page and "data-sidebar-toggle" in page
    )
    assert client.get("/static/logo.png").headers["content-type"] == "image/png"


def test_plotly_asset_served(client):
    response = client.get("/assets/plotly.min.js")
    assert response.status_code == 200 and "javascript" in response.headers["content-type"]
