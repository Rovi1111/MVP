from datetime import date
from decimal import Decimal as D

import pytest

from app.services import charts
from app.services.analytics import fact_budget_series, filter_totals, month_starts
from app.web import period_form
from tests.helpers import load

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
FACT = [
    ("15.01.2025", "Аренда", 100, "Офис"),
    ("2025-01", "Реклама", 40, "Офис"),
    ("10.02.2025", "Аренда", 180, "Офис"),
    ("11.02.2025", "Лицензии", 25, "Склад"),
]
BUDGET = [("2025-01", "Аренда", 80), ("2025-01", "Реклама", 60), ("2025-02", "Аренда", 150)]
FORM = {"mode": "month", "p1_year": "2025", "p1_month": "1", "p2_year": "2025", "p2_month": "2"}


@pytest.fixture
def client(client_for):
    client = client_for("a_admin")
    load(client, "fact", FACT)
    load(client, "budget", BUDGET)
    return client


# ---------- чистые функции ----------


def test_filter_totals():
    totals = {"Аренда": D("100"), "Реклама": D("40"), "ФОТ": D("500")}
    assert filter_totals(totals) == totals
    assert set(filter_totals(totals, ["аренда", "ФОТ"])) == {"Аренда", "ФОТ"}
    assert set(filter_totals(totals, None, D("40"), D("100"))) == {"Аренда", "Реклама"}
    assert filter_totals(totals, ["Аренда"], D("200")) == {}


def test_month_starts():
    assert month_starts(date(2024, 11, 15), date(2025, 2, 1)) == [
        date(2024, 11, 1),
        date(2024, 12, 1),
        date(2025, 1, 1),
        date(2025, 2, 1),
    ]


def test_fact_budget_series():
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


def test_fact_budget_series_without_budget_and_quarter_budget():
    assert fact_budget_series([], None, date(2025, 1, 1), date(2025, 2, 28))["budget"] is None
    quarterly = [(date(2025, 1, 1), "quarter", D("300")), (date(2025, 4, 1), "quarter", D("90"))]
    data = fact_budget_series([], quarterly, date(2025, 2, 1), date(2025, 4, 30))
    # квартальный бюджет делится на три месяца; январь вне периода отброшен
    assert data["budget"] == [100.0, 100.0, 30.0]


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

    without_budget = charts.fact_budget_figure(data | {"budget": None}, "t")
    assert [t.type for t in without_budget.data] == ["bar"]
    empty = charts.fact_budget_figure(
        {"periods": ["я"], "totals": [0.0], "series": [], "budget": None}, "t"
    )
    assert not empty.data and empty.layout.annotations[0].text == "Нет данных"


def test_colors_are_stable_between_charts():
    assert charts.colors_for(["Б", "А"]) == charts.colors_for(["А", "Б", "А"])


def test_png_export():
    png = charts.figure_png(charts.no_data_figure("t"), width=300, height=200, scale=1)
    assert png.startswith(PNG_SIGNATURE)


def test_default_periods_differ_in_every_mode():
    values = period_form.defaults({"fact_to": "2025-06-25"}, ("p1", "p2"))
    assert (values["p1_month"], values["p2_month"]) == ("5", "6")
    assert (values["p1_quarter"], values["p2_quarter"]) == ("1", "2")
    assert values["p2_to"] == "2025-06-25"
    january = period_form.defaults({"fact_to": "2025-01-10"}, ("p1", "p2"))
    assert (january["p1_month"], january["p1_year"], january["p1_quarter"]) == ("12", "2024", "4")


# ---------- API ----------


def test_chart_api_json(client):
    chart = client.get("/api/charts/fact-budget", params={"period": "2025-01..2025-02"}).json()
    traces = {t["name"]: t for t in chart["data"]}
    assert set(traces) == {"Аренда", "Реклама", "Лицензии", "Бюджет"}
    assert traces["Аренда"]["type"] == "bar" and traces["Аренда"]["y"] == [100.0, 180.0]
    assert traces["Бюджет"]["type"] == "scatter" and traces["Бюджет"]["y"] == [140.0, 150.0]
    assert traces["Бюджет"]["x"] == ["январь 2025", "февраль 2025"]

    only = client.get(
        "/api/charts/fact-budget", params={"period": "2025-01", "categories": ["Реклама"]}
    ).json()
    assert {t["name"]: t["y"] for t in only["data"]} == {"Реклама": [40.0], "Бюджет": [60.0]}
    ranged = client.get(
        "/api/charts/fact-budget", params={"period": "2025-01", "amount_min": 50}
    ).json()
    assert [t["name"] for t in ranged["data"]] == ["Аренда", "Бюджет"]

    centers = {c["name"]: c["id"] for c in client.get("/api/cost-centers").json()}
    warehouse = client.get(
        "/api/charts/fact-budget", params={"period": "2025-02", "cost_center_id": centers["Склад"]}
    ).json()
    assert {t["name"]: t["y"] for t in warehouse["data"]} == {"Лицензии": [25.0], "Бюджет": [0.0]}

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


# ---------- страницы ----------


def test_dashboard_page_and_result(client):
    page = client.get("/web/dashboard")
    assert page.status_code == 200 and "Анализ расходов" in page.text
    assert 'value="2" selected' in page.text  # по умолчанию — последний месяц с данными

    result = client.get("/web/dashboard/result", params=FORM)
    assert result.status_code == 200
    for text in ("Новая", "Исчезнувшая", "change-new", "change-removed", "Скачать PNG"):
        assert text in result.text
    assert result.text.count('class="chart"') == 1  # диаграмма одна
    assert "Факт и бюджет по месяцам" in result.text
    assert "/api/charts/fact-budget?period=2025-01-01..2025-02-28&amp;format=png" in result.text
    assert "Перерасход" not in result.text and "План-факт" not in result.text

    only_new = client.get("/web/dashboard/result", params=FORM | {"change_type": "new"})
    assert "Лицензии" in only_new.text and "Показано категорий: 1 из 3" in only_new.text
    empty = client.get(
        "/web/dashboard/result", params=FORM | {"p1_year": "2019", "p2_year": "2019"}
    )
    assert "Нет данных" in empty.text
    quarter = client.get(
        "/web/dashboard/result",
        params={
            "mode": "quarter",
            "p1_year": "2024",
            "p1_quarter": "4",
            "p2_year": "2025",
            "p2_quarter": "1",
        },
    )
    assert "4 кв. 2024" in quarter.text and "1 кв. 2025" in quarter.text
    bad = client.get("/web/dashboard/result", params=FORM | {"amount_min": "много"})
    assert "ожидается число" in bad.text


def test_sidebar_navigation_and_removed_pages(client, client_for):
    home = client.get("/web/")
    assert home.status_code == 303 and home.headers["location"] == "/web/dashboard"
    assert client.get("/web/plan-fact").status_code == 404

    page = client.get("/web/dashboard").text
    assert '<aside class="sidebar">' in page and "Главная" not in page and "План-факт" not in page
    assert 'href="/web/dashboard" class="active"' in page
    assert "sidebar" not in client_for().get("/web/login").text


def test_plotly_asset_served(client):
    response = client.get("/assets/plotly.min.js")
    assert response.status_code == 200 and "javascript" in response.headers["content-type"]
