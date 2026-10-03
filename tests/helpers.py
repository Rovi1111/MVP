"""Вспомогательные функции тестов: файлы-образцы и типовые шаги."""

import io

from openpyxl import Workbook

HEADERS = ["Период", "Статья", "Сумма", "ЦФО"]


def xlsx_bytes(rows, headers=HEADERS) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(list(headers))
    for row in rows:
        sheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def upload_file(client, kind: str, rows, name: str = "data.xlsx", headers=HEADERS):
    files = {"file": (name, xlsx_bytes(rows, headers))}
    return client.post(f"/api/uploads/{kind}/file", files=files)


def load(client, kind: str, rows, name: str = "data.xlsx") -> dict:
    """Загружает файл и подтверждает; все статьи создаются как новые категории."""
    preview = upload_file(client, kind, rows, name)
    assert preview.status_code == 201, preview.text
    info = client.post(f"/api/uploads/{preview.json()['id']}/confirm").json()
    if info["status"] == "pending_mapping":
        mapping = {name: {} for name in info["unmatched"]}
        response = client.post(f"/api/uploads/{info['id']}/mapping", json={"mapping": mapping})
        assert response.status_code == 200, response.text
        info = response.json()
    assert info["status"] == "active", info
    return info
