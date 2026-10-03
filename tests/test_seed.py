from app import cli, seed
from app.models import Organization, User
from app.permissions import Role
from tests.conftest import ApiClient


def test_seed_creates_org_users_and_two_years_of_data(app, session_factory, db, capsys):
    assert cli.main(["seed"], session_factory) == 0
    assert "DEFAULT_PASSWORD" in capsys.readouterr().out
    assert [o.name for o in db.query(Organization)] == ["Демо-компания"]
    assert db.query(User).count() == 3

    demo = seed.DEMO_ORGS[0]
    for role in Role:  # по одному пользователю каждой роли, вход работает
        client = ApiClient(app)
        assert client.login(f"demo_{role.value}", seed.DEFAULT_PASSWORD).status_code == 200
    assert {c["name"] for c in client.get("/api/categories").json()} == set(demo.items)
    assert len(client.get("/api/cost-centers").json()) == 2
    bounds = client.get("/api/analytics/bounds").json()
    assert (bounds["fact_from"], bounds["fact_to"]) == ("2024-01-05", "2025-12-25")

    chart = client.get("/api/charts/fact-budget", params={"period": "2024..2025"}).json()
    by_name = {t["name"]: t["y"] for t in chart["data"]}
    budget = by_name.pop("Бюджет")
    assert len(budget) == 24 and len(set(budget)) > 12  # бюджет меняется от месяца к месяцу
    expected = [sum(demo.budget(c, i) for c in demo.items) for i in range(24)]
    assert budget == expected
    fact_january = sum(amounts[0] for amounts in by_name.values())
    assert fact_january == sum(demo.fact(c, 0) for c in demo.items)  # разбивка не теряет копейки
    assert by_name["Связь и ПО"][:12] == [0.0] * 12 and by_name["Связь и ПО"][12] > 0  # появилась
    assert by_name["Командировки"][20] > 0 and by_name["Командировки"][21:] == [0.0] * 3  # исчезла

    # В динамике есть все виды изменений между годами и превышения бюджета
    years = {"period1": "2024", "period2": "2025"}
    comparison = client.get("/api/analytics/comparison", params=years).json()
    assert {"increase", "decrease", "new"} <= {row["change_type"] for row in comparison["rows"]}
    plan_fact = client.get("/api/analytics/plan-fact", params={"period": "2025"}).json()
    assert any(row["overspend"] and row["significant"] for row in plan_fact["rows"])
    assert any(not row["overspend"] and row["significant"] for row in plan_fact["rows"])

    days = client.get("/api/analytics/series", params={"period": "2025-01", "granularity": "day"})
    assert len(days.json()["periods"]) == 3


def test_seed_is_idempotent(session_factory, db, capsys):
    assert cli.main(["seed", "--password", "another-password"], session_factory) == 0
    assert cli.main(["seed"], session_factory) == 0
    assert capsys.readouterr().out.count("уже существует") == 1
    assert db.query(Organization).count() == 1
