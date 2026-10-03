from app import cli, seed
from app.models import Organization, User
from app.permissions import Role
from tests.conftest import ApiClient

EXPECTED_CATEGORIES = {
    "feed": {"Сухой корм", "Влажный корм", "Лакомства", "Ветеринарные диеты"},
    "it": {"Серверы CPU", "RAM", "SSD", "GPU", "Сеть", "Лицензии"},
    "dent": {"Материалы", "Аренда", "Зарплата", "Оборудование", "Реклама"},
}


def test_seed_creates_orgs_users_and_meaningful_data(app, session_factory, db, capsys):
    assert cli.main(["seed"], session_factory) == 0
    assert "DEFAULT_PASSWORD" in capsys.readouterr().out
    assert db.query(Organization).count() == 3
    assert db.query(User).count() == 9

    for demo in seed.DEMO_ORGS:
        for role in Role:  # по одному пользователю каждой роли, вход работает
            client = ApiClient(app)
            assert (
                client.login(f"{demo.prefix}_{role.value}", seed.DEFAULT_PASSWORD).status_code
                == 200
            )

        names = {c["name"] for c in client.get("/api/categories").json()}
        assert EXPECTED_CATEGORIES[demo.prefix] <= names

        quarters = {"period1": "2025-Q1", "period2": "2025-Q2"}
        comparison = client.get("/api/analytics/comparison", params=quarters).json()
        assert {row["change_type"] for row in comparison["rows"]} == {
            "increase", "decrease", "new", "removed", "no_change",
        }  # fmt: skip
        expected_q1 = sum(sum(values[:3]) for values in demo.fact.values())
        assert comparison["total_p1"] == expected_q1  # разбивка по дням и ЦФО не теряет копейки

        plan_fact = client.get("/api/analytics/plan-fact", params={"period": "2025-Q2"}).json()
        assert any(row["overspend"] and row["significant"] for row in plan_fact["rows"])

        days = client.get(
            "/api/analytics/series", params={"period": "2025-01", "granularity": "day"}
        )
        assert len(days.json()["periods"]) == 3
        centers = client.get("/api/cost-centers").json()
        assert len(centers) == 2

    # Организации изолированы: кормов нет у стоматологии
    assert "Сухой корм" not in names


def test_seed_is_idempotent(session_factory, db, capsys):
    assert cli.main(["seed", "--password", "another-password"], session_factory) == 0
    assert cli.main(["seed"], session_factory) == 0
    assert capsys.readouterr().out.count("уже существует") == 3
    assert db.query(Organization).count() == 3
