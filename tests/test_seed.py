from app import cli, seed
from app.models import Organization, User
from app.permissions import Role
from tests.conftest import ApiClient


def test_seed_creates_org_users_and_meaningful_data(app, session_factory, db, capsys):
    assert cli.main(["seed"], session_factory) == 0
    assert "DEFAULT_PASSWORD" in capsys.readouterr().out
    assert [o.name for o in db.query(Organization)] == ["Демо-компания"]
    assert db.query(User).count() == 3

    demo = seed.DEMO_ORGS[0]
    for role in Role:  # по одному пользователю каждой роли, вход работает
        client = ApiClient(app)
        assert client.login(f"demo_{role.value}", seed.DEFAULT_PASSWORD).status_code == 200

    names = {c["name"] for c in client.get("/api/categories").json()}
    assert names == set(demo.fact)

    quarters = {"period1": "2025-Q1", "period2": "2025-Q2"}
    comparison = client.get("/api/analytics/comparison", params=quarters).json()
    assert {row["change_type"] for row in comparison["rows"]} == {
        "increase",
        "decrease",
        "new",
        "removed",
        "no_change",
    }
    expected_q1 = sum(sum(values[:3]) for values in demo.fact.values())
    assert comparison["total_p1"] == expected_q1  # разбивка по дням и ЦФО не теряет копейки

    plan_fact = client.get("/api/analytics/plan-fact", params={"period": "2025-Q2"}).json()
    assert any(row["overspend"] and row["significant"] for row in plan_fact["rows"])

    days = client.get("/api/analytics/series", params={"period": "2025-01", "granularity": "day"})
    assert len(days.json()["periods"]) == 3
    assert len(client.get("/api/cost-centers").json()) == 2

    chart = client.get("/api/charts/fact-budget", params={"period": "2025"}).json()
    assert chart["data"][-1]["name"] == "Бюджет" and len(chart["data"][-1]["x"]) == 12


def test_seed_is_idempotent(session_factory, db, capsys):
    assert cli.main(["seed", "--password", "another-password"], session_factory) == 0
    assert cli.main(["seed"], session_factory) == 0
    assert capsys.readouterr().out.count("уже существует") == 1
    assert db.query(Organization).count() == 1
