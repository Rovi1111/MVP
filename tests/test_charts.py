from decimal import Decimal as D

import pytest

from app.services import charts
from app.services.analytics import filter_totals
from tests.helpers import load

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
FACT = [
    ("15.01.2025", "Аренда", 100, "Офис"),
    ("2025-01", "Реклама", 40, "Офис"),
    ("10.02.2025", "Аренда", 180, "Офис"),
    ("11.02.2025", "Лицензии", 25, "Склад"),
]


@pytest.fixture
def client(client_for):
    client = client_for("a_admin")
    load(client, "fact", FACT)
    load(client, "budget", [("2025-01", "Аренда", 80), ("2025-01", "Реклама", 60)])
    return client


def test_filter_totals():
    totals = {"Аренда": D("100"), "Реклама": D("40"), "ФОТ": D("500")}
    assert filter_totals(totals) == totals
    assert set(filter_totals(totals, ["аренда", "ФОТ"])) == {"Аренда", "ФОТ"}
    assert set(filter_totals(totals, None, D("40"), D("100"))) == {"Аренда", "Реклама"}
    assert filter_totals(totals, ["Аренда"], D("200")) == {}


def test_pie_figure_and_no_data():
    shares = [
        {"category": "A", "amount": 75.0, "share": 75.0},
        {"category": "B", "amount": 25.0, "share": 25.0},
    ]
    figure = charts.pie_figure(shares, "январь 2025")
    assert figure.data[0].type == "pie" and figure.data[0].textinfo == "percent"
    assert list(figure.data[0].labels) == ["A", "B"]
    empty = charts.pie_figure([], "январь 2025")
    assert not empty.data and empty.layout.annotations[0].text == "Нет данных"


def test_colors_are_stable_between_charts():
    assert charts.colors_for(["Б", "А"]) == charts.colors_for(["А", "Б", "А"])


def test_stacked_bar_has_share_in_hover():
    series = {
        "periods": ["январь 2025", "февраль 2025"],
        "series": [{"category": "A", "amounts": [30.0, 0.0], "shares": [75.0, 0.0]}],
    }
    figure = charts.stacked_bar_figure(series, "t")
    assert figure.layout.barmode == "relative"
    assert "Доля" in figure.data[0].hovertemplate and list(figure.data[0].customdata) == [75.0, 0.0]
    assert not charts.stacked_bar_figure({"periods": [], "series": []}, "t").data


def test_plan_fact_figure_marks_overspend():
    rows = [
        {"category": "A", "plan": 100.0, "fact": 150.0, "overspend": True, "significant": True},
        {"category": "B", "plan": 100.0, "fact": 90.0, "overspend": False, "significant": False},
    ]
    figure = charts.plan_fact_figure(rows, "t")
    assert [trace.name for trace in figure.data] == ["План", "Факт"]
    assert list(figure.data[1].marker.color) == [charts.OVERSPEND_COLOR, charts.FACT_COLOR]


def test_png_export():
    png = charts.figure_png(charts.no_data_figure("t"), width=300, height=200, scale=1)
    assert png.startswith(PNG_SIGNATURE)


def test_chart_api_json(client):
    pie = client.get("/api/charts/pie", params={"period": "2025-01"}).json()
    assert pie["data"][0]["labels"] == ["Аренда", "Реклама"]
    filtered = client.get(
        "/api/charts/pie", params={"period": "2025-01", "categories": ["Реклама"]}
    ).json()
    assert filtered["data"][0]["labels"] == ["Реклама"]
    ranged = client.get("/api/charts/pie", params={"period": "2025-01", "amount_min": 50}).json()
    assert ranged["data"][0]["labels"] == ["Аренда"]
    empty = client.get("/api/charts/pie", params={"period": "2030-01"}).json()
    assert empty["data"] == [] and empty["layout"]["annotations"][0]["text"] == "Нет данных"

    stacked = client.get(
        "/api/charts/stacked", params={"period": "2025", "granularity": "month"}
    ).json()
    assert stacked["data"][0]["x"] == ["январь 2025", "февраль 2025"]
    plan_fact = client.get("/api/charts/plan-fact", params={"period": "2025-01"}).json()
    assert [t["name"] for t in plan_fact["data"]] == ["План", "Факт"]
    assert client.get("/api/charts/unknown", params={"period": "2025-01"}).status_code == 404


def test_chart_api_png_download_is_audited(client):
    response = client.get("/api/charts/pie", params={"period": "2025-01", "format": "png"})
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert response.content.startswith(PNG_SIGNATURE)
    assert "attachment" in response.headers["content-disposition"]


def test_dashboard_pages(client):
    page = client.get("/web/dashboard")
    assert page.status_code == 200 and "Сравнение периодов" in page.text
    assert 'value="2" selected' in page.text  # по умолчанию — последний месяц с данными

    params = {
        "mode": "month",
        "p1_year": "2025",
        "p1_month": "1",
        "p2_year": "2025",
        "p2_month": "2",
    }
    result = client.get("/web/dashboard/result", params=params)
    assert result.status_code == 200
    for text in (
        "Новая",
        "Исчезнувшая",
        "change-new",
        "change-removed",
        "Скачать PNG",
        "pie-2",
        "stacked",
    ):
        assert text in result.text
    assert "/api/charts/pie?period=2025-01&amp;format=png" in result.text

    only_new = client.get("/web/dashboard/result", params=params | {"change_type": "new"})
    assert "Лицензии" in only_new.text and "Показано категорий: 1 из 3" in only_new.text

    empty = client.get(
        "/web/dashboard/result", params=params | {"p1_year": "2019", "p2_year": "2019"}
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


def test_plan_fact_pages(client):
    assert client.get("/web/plan-fact").status_code == 200
    params = {"mode": "month", "p_year": "2025", "p_month": "1"}
    result = client.get("/web/plan-fact/result", params=params)
    assert "Перерасход" in result.text and 'class="overspend"' in result.text
    assert "plan-fact-chart" in result.text
    by_cc = client.get("/web/plan-fact/result", params=params | {"by_cost_center": "on"})
    assert "<th>ЦФО</th>" in by_cc.text
    bad = client.get("/web/plan-fact/result", params=params | {"threshold_pct": "много"})
    assert "ожидается число" in bad.text


def test_plotly_asset_served(client):
    response = client.get("/assets/plotly.min.js")
    assert response.status_code == 200 and "javascript" in response.headers["content-type"]


def test_default_periods_differ_in_every_mode():
    from app.web import period_form

    values = period_form.defaults({"fact_to": "2025-06-25"}, ("p1", "p2"))
    assert (values["p1_month"], values["p2_month"]) == ("5", "6")
    assert (values["p1_quarter"], values["p2_quarter"]) == ("1", "2")
    assert values["p2_to"] == "2025-06-25"
    january = period_form.defaults({"fact_to": "2025-01-10"}, ("p1", "p2"))
    assert (january["p1_month"], january["p1_year"], january["p1_quarter"]) == ("12", "2024", "4")
