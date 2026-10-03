"""Скачиваемые шаблоны Excel для факта и бюджета."""

import io
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Font

from app.models import UploadKind

HEADERS = ["Период", "Статья", "Сумма", "ЦФО"]
_EXAMPLES = {
    UploadKind.FACT: [
        (date(2025, 1, 15), "Аренда", 120000, "Офис"),
        (date(2025, 1, 20), "Реклама", 35500.50, ""),
    ],
    UploadKind.BUDGET: [
        ("2025-01", "Аренда", 120000, "Офис"),
        ("2025-01", "Реклама", 40000, ""),
    ],
}
_NOTES = [
    "Период: дата (15.01.2025), месяц (2025-01, янв 2025) или квартал (2025-Q1, 1 кв 2025).",
    "Статья: название статьи расходов. Сумма: число. ЦФО: необязательно.",
    "Строки с одинаковыми периодом, статьёй и ЦФО суммируются. Этот лист при загрузке не читается.",
]


def build_template(kind: str) -> bytes:
    kind = UploadKind(kind)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Факт" if kind == UploadKind.FACT else "Бюджет"
    sheet.append(HEADERS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in _EXAMPLES[kind]:
        sheet.append(list(row))
    for column, width in zip("ABCD", (14, 32, 16, 20), strict=True):
        sheet.column_dimensions[column].width = width
    for cell in sheet["A"][1:]:
        if isinstance(cell.value, date):
            cell.number_format = "DD.MM.YYYY"
    notes = workbook.create_sheet("Справка")
    for note in _NOTES:
        notes.append([note])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
