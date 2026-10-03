"""Аналитика через API: данные из БД, фильтры, права, изоляция."""

import pytest

from tests.helpers import load

FACT = [
    ("15.01.2025", "Аренда", 100, "Офис"),
    ("20.01.2025", "Аренда", 50, "Склад"),
    ("2025-01", "Реклама", 40, "Офис"),
    ("10.02.2025", "Аренда", 180, "Офис"),
    ("11.02.2025", "Лицензии", 25, "Офис"),
]
BUDGET = [
    ("2025-01", "Аренда", 120, "Офис"),
    ("2025-01", "Реклама", 60, "Офис"),
    ("2025-02", "Аренда", 150, "Офис"),
]


@pytest.fixture
def client(client_for):
    client = client_for("a_admin")
    load(client, "fact", FACT)
    load(client, "budget", BUDGET)
    return client


def test_comparison(client):
    data = client.get(
        "/api/analytics/comparison", params={"period1": "2025-01", "period2": "2025-02"}
    ).json()
    assert [(r["category"], r["delta"], r["change_type"]) for r in data["rows"]] == [
        ("Аренда", 30.0, "increase"), ("Лицензии", 25.0, "new"), ("Реклама", -40.0, "removed"),
    ]  # fmt: skip
    assert (data["total_p1"], data["total_p2"], data["total_delta"]) == (190.0, 205.0, 15.0)
    assert data["params"]["period1"]["label"] == "январь 2025"
    assert [s["category"] for s in data["shares_p1"]] == ["Аренда", "Реклама"]
    assert data["warnings"] == []


def test_comparison_filters_and_sort(client):
    base = {"period1": "2025-01", "period2": "2025-02"}
    data = client.get(
        "/api/analytics/comparison", params=base | {"change_type": ["new", "removed"]}
    ).json()
    assert {r["category"] for r in data["rows"]} == {"Лицензии", "Реклама"}
    assert data["filtered"] and len(data["all_rows"]) == 3 and data["total_p1"] == 190.0

    data = client.get("/api/analytics/comparison", params=base | {"category": "аре"}).json()
    assert [r["category"] for r in data["rows"]] == ["Аренда"]

    data = client.get(
        "/api/analytics/comparison", params=base | {"sort": "category", "order": "asc"}
    ).json()
    assert [r["category"] for r in data["rows"]] == ["Аренда", "Лицензии", "Реклама"]

    centers = {c["name"]: c["id"] for c in client.get("/api/cost-centers").json()}
    data = client.get(
        "/api/analytics/comparison", params=base | {"cost_center_id": centers["Склад"]}
    ).json()
    assert [(r["category"], r["change_type"]) for r in data["rows"]] == [("Аренда", "removed")]


def test_comparison_day_ranges_and_coarse_warning(client):
    data = client.get(
        "/api/analytics/comparison",
        params={"period1": "2025-01-15", "period2": "2025-01-16..2025-01-31"},
    ).json()
    assert [(r["category"], r["amount_p1"], r["amount_p2"]) for r in data["rows"]] == [
        ("Аренда", 100.0, 50.0)
    ]
    # «Реклама» введена за январь целиком и стоит на 1-м числе: в диапазон с 15-го не попала
    data = client.get(
        "/api/analytics/comparison",
        params={"period1": "2025-01-01..2025-01-14", "period2": "2025-02"},
    ).json()
    assert len(data["warnings"]) == 1 and "не полностью" in data["warnings"][0]


def test_comparison_errors(client):
    empty = client.get(
        "/api/analytics/comparison", params={"period1": "2020-01", "period2": "2020-02"}
    )
    assert empty.status_code == 422 and "Нет данных" in empty.json()["detail"]
    bad = client.get("/api/analytics/comparison", params={"period1": "вчера", "period2": "2025-02"})
    assert bad.status_code == 422 and "Период 1" in bad.json()["detail"]
    params = {"period1": "2025-01", "period2": "2025-02"}
    assert client.get("/api/analytics/comparison", params=params | {"sort": "x"}).status_code == 422
    assert (
        client.get("/api/analytics/comparison", params=params | {"change_type": "x"}).status_code
        == 422
    )
    assert (
        client.get("/api/analytics/comparison", params=params | {"cost_center_id": 999}).status_code
        == 404
    )


def test_plan_fact(client):
    data = client.get("/api/analytics/plan-fact", params={"period": "2025-01"}).json()
    rows = {r["category"]: r for r in data["rows"]}
    assert (rows["Аренда"]["plan"], rows["Аренда"]["fact"], rows["Аренда"]["deviation_pct"]) == (
        120.0,
        150.0,
        25.0,
    )
    assert rows["Аренда"]["overspend"] and rows["Аренда"]["significant"]
    assert rows["Реклама"]["deviation"] == -20.0 and not rows["Реклама"]["overspend"]
    assert data["params"]["budget_version"] == 1 and data["threshold_pct"] == 10.0

    by_cc = client.get(
        "/api/analytics/plan-fact", params={"period": "2025-01", "by_cost_center": True}
    ).json()
    keyed = {(r["category"], r["cost_center"]): r for r in by_cc["rows"]}
    assert (
        keyed[("Аренда", "Склад")]["plan"] == 0.0
        and keyed[("Аренда", "Склад")]["deviation_pct"] is None
    )
    assert keyed[("Аренда", "Офис")]["deviation"] == -20.0

    relaxed = client.get(
        "/api/analytics/plan-fact", params={"period": "2025-01", "threshold_pct": 50}
    ).json()
    assert not any(r["significant"] for r in relaxed["rows"] if r["category"] == "Аренда")


def test_plan_fact_versions_and_month_snapping(client):
    v2 = load(client, "budget", [("2025-01", "Аренда", 200)])
    latest = client.get("/api/analytics/plan-fact", params={"period": "2025-01"}).json()
    assert latest["params"]["budget_version"] == 2 and latest["total_plan"] == 200.0
    first_id = client.get("/api/analytics/bounds").json()["budget_versions"][-1]["upload_id"]
    old = client.get(
        "/api/analytics/plan-fact", params={"period": "2025-01", "budget_upload_id": first_id}
    ).json()
    assert old["params"]["budget_version"] == 1 and old["total_plan"] == 180.0

    snapped = client.get(
        "/api/analytics/plan-fact", params={"period": "2025-01-10..2025-01-20"}
    ).json()
    assert (
        snapped["params"]["period"]["start"] == "2025-01-01"
        and "целым месяцам" in snapped["warnings"][0]
    )

    fact_upload = client.get("/api/uploads", params={"kind": "fact"}).json()[0]["id"]
    wrong = client.get(
        "/api/analytics/plan-fact", params={"period": "2025-01", "budget_upload_id": fact_upload}
    )
    assert wrong.status_code == 404
    assert v2["version"] == 2


def test_plan_fact_without_budget(client_for):
    client = client_for("b_admin")
    response = client.get("/api/analytics/plan-fact", params={"period": "2025-01"})
    assert response.status_code == 422 and "Бюджет ещё не загружен" in response.json()["detail"]


def test_series(client):
    data = client.get(
        "/api/analytics/series", params={"period": "2025", "granularity": "month"}
    ).json()
    assert data["periods"] == ["январь 2025", "февраль 2025"] and data["totals"] == [190.0, 205.0]
    days = client.get(
        "/api/analytics/series", params={"period": "2025-01", "granularity": "day"}
    ).json()
    assert days["periods"] == ["01.01.2025", "15.01.2025", "20.01.2025"]
    assert (
        client.get(
            "/api/analytics/series", params={"period": "2025", "granularity": "week"}
        ).status_code
        == 422
    )


def test_analytics_isolated_and_requires_login(client, client_for):
    other = client_for("b_admin")
    params = {"period1": "2025-01", "period2": "2025-02"}
    assert (
        other.get("/api/analytics/comparison", params=params).status_code == 422
    )  # у Б данных нет
    assert other.get("/api/analytics/bounds").json() == {
        "fact_from": None,
        "fact_to": None,
        "budget_versions": [],
    }
    assert client_for().get("/api/analytics/comparison", params=params).status_code == 401
    assert (
        client_for("a_employee").get("/api/analytics/comparison", params=params).status_code == 200
    )
