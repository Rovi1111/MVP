from tests.helpers import load


def test_category_crud(client_for):
    client = client_for("a_manager")
    created = client.post("/api/categories", json={"name": "  Аренда   офиса "})
    assert created.status_code == 201 and created.json()["name"] == "Аренда офиса"
    item_id = created.json()["id"]
    assert client.post("/api/categories", json={"name": "аренда офиса"}).status_code == 409
    renamed = client.patch(
        f"/api/categories/{item_id}", json={"name": "Аренда", "is_active": False}
    )
    assert renamed.json() == {"id": item_id, "name": "Аренда", "is_active": False}
    assert client.delete(f"/api/categories/{item_id}").status_code == 204
    assert client.get("/api/categories").json() == []
    assert client.delete(f"/api/categories/{item_id}").status_code == 404


def test_used_category_cannot_be_deleted(client_for):
    client = client_for("a_admin")
    load(client, "fact", [("2025-01", "Аренда", 10, "Офис")])
    category = client.get("/api/categories").json()[0]
    cost_center = client.get("/api/cost-centers").json()[0]
    assert client.delete(f"/api/categories/{category['id']}").status_code == 409
    assert client.delete(f"/api/cost-centers/{cost_center['id']}").status_code == 409


def test_employee_cannot_edit_reference(client_for):
    manager, employee = client_for("a_manager"), client_for("a_employee")
    item = manager.post("/api/cost-centers", json={"name": "Офис"}).json()
    assert employee.get("/api/cost-centers").status_code == 200  # чтение нужно для ввода данных
    assert employee.post("/api/categories", json={"name": "X"}).status_code == 403
    assert employee.patch(f"/api/cost-centers/{item['id']}", json={"name": "Y"}).status_code == 403
    assert employee.delete(f"/api/cost-centers/{item['id']}").status_code == 403
    assert employee.get("/api/category-aliases").status_code == 403
    assert employee.get("/web/reference").status_code == 403


def test_reference_isolated_between_orgs(client_for):
    a, b = client_for("a_admin"), client_for("b_admin")
    item = a.post("/api/categories", json={"name": "Аренда"}).json()
    assert (
        b.post("/api/categories", json={"name": "Аренда"}).status_code == 201
    )  # своё пространство имён
    assert b.patch(f"/api/categories/{item['id']}", json={"name": "Взлом"}).status_code == 404
    assert b.delete(f"/api/categories/{item['id']}").status_code == 404


def test_alias_list_and_delete(client_for):
    client = client_for("a_admin")
    category = client.post("/api/categories", json={"name": "Зарплата"}).json()
    preview = client.post(
        "/api/uploads/manual",
        json={"kind": "fact", "rows": [{"period": "2025-01", "category": "ФОТ", "amount": 1}]},
    ).json()
    client.post(f"/api/uploads/{preview['id']}/confirm")
    client.post(
        f"/api/uploads/{preview['id']}/mapping",
        json={"mapping": {"ФОТ": {"category_id": category["id"]}}},
    )
    aliases = client.get("/api/category-aliases").json()
    assert [(a["alias"], a["category"]) for a in aliases] == [("фот", "Зарплата")]
    assert client.delete(f"/api/category-aliases/{aliases[0]['id']}").status_code == 204
    assert client.get("/api/category-aliases").json() == []
