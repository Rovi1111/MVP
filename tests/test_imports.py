from datetime import date
from decimal import Decimal

from app.datasources import RawRow
from app.models import BudgetLine, CategoryAlias, ExpenseRecord, Upload
from app.services.imports import ParsedRow, aggregate_rows, covered_months, validate_rows
from tests.helpers import load, upload_file


def active_fact(db):
    db.expire_all()
    return db.query(ExpenseRecord).filter_by(is_active=True).all()


# ---------- чистые функции ----------


def test_validate_rows_collects_all_problems():
    rows, errors = validate_rows(
        [
            RawRow(2, "2025-01", "Аренда", "100"),
            RawRow(3, "когда-то", "", "много"),
            RawRow(4, None, 15, None),
        ],
        "fact",
    )
    assert len(rows) == 1
    assert {(e.row, e.column) for e in errors} == {
        (3, "Период"), (3, "Статья"), (3, "Сумма"), (4, "Период"), (4, "Статья"), (4, "Сумма"),
    }  # fmt: skip


def test_budget_rejects_negative_but_fact_allows():
    raw = [RawRow(2, "2025-01", "Возврат", "-100")]
    assert validate_rows(raw, "fact")[1] == []
    assert validate_rows(raw, "budget")[1][0].problem == "План не может быть отрицательным"


def test_aggregate_rows_sums_duplicates():
    d = date(2025, 1, 1)
    rows = aggregate_rows(
        [
            ParsedRow(d, "month", "Аренда", None, Decimal("100.10")),
            ParsedRow(d, "month", " аренда", None, Decimal("0.20")),
            ParsedRow(d, "month", "Аренда", "Офис", Decimal("5")),
            ParsedRow(date(2025, 1, 2), "day", "Аренда", None, Decimal("1")),
        ]
    )
    assert [(r.cost_center, r.amount) for r in rows] == [
        (None, Decimal("100.30")), ("Офис", Decimal("5")), (None, Decimal("1")),
    ]  # fmt: skip


def test_covered_months_quarter_spans_three():
    rows = [
        ParsedRow(date(2024, 10, 1), "quarter", "A", None, Decimal(1)),
        ParsedRow(date(2025, 2, 14), "day", "A", None, Decimal(1)),
    ]
    assert covered_months(rows) == [
        (date(2024, 10, 1), date(2024, 10, 31)),
        (date(2024, 11, 1), date(2024, 11, 30)),
        (date(2024, 12, 1), date(2024, 12, 31)),
        (date(2025, 2, 1), date(2025, 2, 28)),
    ]


# ---------- сценарии через API ----------


def test_validation_errors_table_and_nothing_written(client_for, db):
    client = client_for("a_admin")
    response = upload_file(client, "fact", [("2025-01", "Аренда", 100), ("мусор", "", "x")])
    assert response.status_code == 422
    body = response.json()
    assert {"row": 3, "column": "Сумма", "problem": "Сумма должна быть числом: «x»"} in body[
        "errors"
    ]
    assert len(body["errors"]) == 3
    assert db.query(Upload).count() == 0 and db.query(ExpenseRecord).count() == 0


def test_preview_then_confirm_with_mapping(client_for, db):
    client = client_for("a_admin")
    rows = [
        ("15.01.2025", "Аренда", 100, "Офис"),
        ("15.01.2025", "Аренда", 50, "Офис"),
        ("2025-02", "ФОТ", 10),
    ]
    preview = upload_file(client, "fact", rows).json()
    assert preview["status"] == "preview" and preview["version"] is None
    assert (preview["source_rows"], preview["row_count"], preview["total"]) == (3, 2, 160.0)
    assert preview["unmatched"] == ["Аренда", "ФОТ"] and preview["new_cost_centers"] == ["Офис"]
    assert db.query(ExpenseRecord).count() == 0  # до подтверждения ничего не записано

    pending = client.post(f"/api/uploads/{preview['id']}/confirm").json()
    assert pending["status"] == "pending_mapping"
    assert db.query(ExpenseRecord).count() == 0

    category = client.post("/api/categories", json={"name": "Зарплата"}).json()
    mapping = {"ФОТ": {"category_id": category["id"]}, "Аренда": {"new_name": "Аренда офиса"}}
    done = client.post(f"/api/uploads/{preview['id']}/mapping", json={"mapping": mapping}).json()
    assert done["status"] == "active" and done["version"] == 1

    records = active_fact(db)
    assert sorted((r.category.name, r.amount, r.grain) for r in records) == [
        ("Аренда офиса", Decimal("150.00"), "day"), ("Зарплата", Decimal("10.00"), "month"),
    ]  # fmt: skip
    assert records[0].cost_center.name == "Офис"
    assert {a.alias for a in db.query(CategoryAlias)} == {"аренда", "фот"}

    # Сопоставление запомнено: следующая загрузка проходит без вопросов
    again = upload_file(client, "fact", [("2025-03", "фот", 7), ("2025-03", "АРЕНДА", 1)]).json()
    assert again["unmatched"] == []
    assert client.post(f"/api/uploads/{again['id']}/confirm").json()["status"] == "active"


def test_fact_file_replaces_same_months_manual_adds(client_for, db):
    client = client_for("a_admin")
    load(client, "fact", [("10.01.2025", "A", 100), ("10.02.2025", "A", 200)])
    second = upload_file(client, "fact", [("20.01.2025", "A", 150)]).json()
    assert second["replaces"] == {"months": ["01.2025"], "records": 1}
    client.post(f"/api/uploads/{second['id']}/confirm")
    assert sorted((r.date, r.amount) for r in active_fact(db)) == [
        (date(2025, 1, 20), Decimal("150.00")), (date(2025, 2, 10), Decimal("200.00")),
    ]  # fmt: skip
    assert db.query(ExpenseRecord).count() == 3  # старая версия осталась в истории

    manual = client.post(
        "/api/uploads/manual",
        json={"kind": "fact", "rows": [{"period": "25.01.2025", "category": "A", "amount": "1,5"}]},
    ).json()
    assert manual["replaces"] is None
    client.post(f"/api/uploads/{manual['id']}/confirm")
    assert sum(r.amount for r in active_fact(db)) == Decimal("351.50")

    # Третий файл за февраль полностью вытесняет первую загрузку
    load(client, "fact", [("2025-02", "A", 1)])
    statuses = {u.version: u.status for u in db.query(Upload)}
    assert statuses == {1: "superseded", 2: "active", 3: "active", 4: "active"}


def test_budget_versions_and_manual_copy(client_for, db):
    client = client_for("a_admin")
    v1 = load(client, "budget", [("2025-01", "A", 100), ("2025-02", "A", 100)])
    v2 = load(client, "budget", [("2025-01", "A", 120)])
    assert (v1["version"], v2["version"]) == (1, 2)
    assert db.query(BudgetLine).filter_by(upload_id=v1["id"]).count() == 2  # версии не смешиваются

    manual = client.post(
        "/api/uploads/manual",
        json={"kind": "budget", "rows": [{"period": "2025-03", "category": "A", "amount": 30}]},
    ).json()
    v3 = client.post(f"/api/uploads/{manual['id']}/confirm").json()
    assert v3["version"] == 3 and v3["total"] == 150.0
    lines = db.query(BudgetLine).filter_by(upload_id=v3["id"]).all()
    assert sorted(line.amount for line in lines) == [Decimal("30.00"), Decimal("120.00")]


def test_employee_upload_waits_for_manager_mapping(client_for, db):
    employee, manager = client_for("a_employee"), client_for("a_manager")
    preview = upload_file(employee, "fact", [("2025-01", "Новая статья", 10)]).json()
    pending = employee.post(f"/api/uploads/{preview['id']}/confirm").json()
    assert pending["status"] == "pending_mapping"
    mapping = {"mapping": {"Новая статья": {}}}
    assert employee.post(f"/api/uploads/{preview['id']}/mapping", json=mapping).status_code == 403
    assert db.query(ExpenseRecord).count() == 0

    assert (
        manager.post(f"/api/uploads/{preview['id']}/mapping", json=mapping).json()["status"]
        == "active"
    )
    assert len(active_fact(db)) == 1


def test_cancel_preview_and_active(client_for, db):
    admin, employee = client_for("a_admin"), client_for("a_employee")
    preview = upload_file(admin, "fact", [("2025-01", "A", 10)]).json()
    assert admin.post(f"/api/uploads/{preview['id']}/cancel").json()["status"] == "cancelled"
    assert admin.post(f"/api/uploads/{preview['id']}/confirm").status_code == 409

    info = load(admin, "fact", [("2025-01", "A", 10)])
    assert employee.post(f"/api/uploads/{info['id']}/cancel").status_code == 403
    assert admin.post(f"/api/uploads/{info['id']}/cancel").json()["status"] == "cancelled"
    assert active_fact(db) == []


def test_uploads_isolated_between_orgs(client_for):
    a, b = client_for("a_admin"), client_for("b_admin")
    info = load(a, "fact", [("2025-01", "Секретная статья", 10)])
    assert b.get("/api/uploads").json() == []
    assert b.get(f"/api/uploads/{info['id']}").status_code == 404
    assert b.post(f"/api/uploads/{info['id']}/cancel").status_code == 404
    assert b.get("/api/categories").json() == []
    # Категория организации А не подходит для сопоставления в организации Б
    category_a = a.get("/api/categories").json()[0]
    preview = upload_file(b, "fact", [("2025-01", "X", 1)]).json()
    b.post(f"/api/uploads/{preview['id']}/confirm")
    mapping = {"mapping": {"X": {"category_id": category_a["id"]}}}
    assert b.post(f"/api/uploads/{preview['id']}/mapping", json=mapping).status_code == 404


def test_manual_input_validation(client_for):
    client = client_for("a_employee")
    response = client.post(
        "/api/uploads/manual",
        json={"kind": "fact", "rows": [{"period": "2025-13", "category": "A"}]},
    )
    assert response.status_code == 422
    assert {e["column"] for e in response.json()["errors"]} == {"Период", "Сумма"}
    assert client.post("/api/uploads/manual", json={"kind": "other", "rows": []}).status_code == 422
