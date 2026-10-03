import json

from tests.helpers import xlsx_bytes


def test_data_pages_render(client_for):
    client = client_for("a_admin")
    page = client.get("/web/data")
    assert page.status_code == 200
    for text in ("Файл факта", "Файл бюджета", "Ручной ввод", "/api/templates/fact"):
        assert text in page.text
    assert client.get("/web/uploads").status_code == 200
    assert "Справочники" in client.get("/web/reference").text


def test_web_file_flow_preview_mapping_confirm(client_for):
    client = client_for("a_admin")
    files = {"file": ("fact.xlsx", xlsx_bytes([("15.01.2025", "Аренда", "1 000,50", "Офис")]))}
    preview = client.post("/web/uploads/fact/file", files=files)
    assert preview.status_code == 200
    assert "Сопоставление статей" in preview.text and "1 000,50" in preview.text

    upload_id = client.get("/api/uploads").json()[0]["id"]
    done = client.post(
        f"/web/uploads/{upload_id}/mapping",
        data={"name": "Аренда", "target": "new", "new_name": "Аренда"},
    )
    assert "Данные записаны" in done.text
    assert "Записана" in client.get("/web/uploads").text
    assert client.get(f"/web/uploads/{upload_id}").status_code == 200


def test_web_validation_errors_table(client_for):
    client = client_for("a_admin")
    files = {"file": ("fact.xlsx", xlsx_bytes([("нет", "Аренда", "abc")]))}
    response = client.post("/web/uploads/fact/file", files=files)
    assert response.status_code == 422
    assert "Период не распознан" in response.text and "Сумма должна быть числом" in response.text


def test_web_manual_form_and_json(client_for):
    client = client_for("a_employee")
    form = client.post(
        "/web/uploads/manual/form",
        data={"kind": "fact", "period": ["2025-01", ""], "category": ["A", ""],
              "amount": ["10", ""], "cost_center": ["", ""]},
    )  # fmt: skip
    assert form.status_code == 200 and "Отправить на сопоставление" in form.text

    bad = client.post("/web/uploads/manual/json", data={"payload": "{oops"})
    assert bad.status_code == 422 and "Некорректный JSON" in bad.text
    payload = json.dumps(
        {"kind": "budget", "rows": [{"period": "2025-01", "category": "A", "amount": 5}]}
    )
    assert "Бюджет" in client.post("/web/uploads/manual/json", data={"payload": payload}).text


def test_reference_web_crud_via_htmx(client_for):
    client = client_for("a_manager")
    section = client.post("/web/reference/category", data={"name": "Аренда"})
    assert section.status_code == 200 and 'value="Аренда"' in section.text
    duplicate = client.post(
        "/web/reference/category", data={"name": "аренда"}, headers={"HX-Request": "true"}
    )
    assert duplicate.status_code == 409 and duplicate.headers["HX-Retarget"] == "#flash"
