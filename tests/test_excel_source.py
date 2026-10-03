from datetime import datetime

import pytest

from app.datasources import ExcelSource, ManualSource, SourceError
from app.services.excel_templates import build_template
from app.services.imports import validate_rows
from tests.helpers import xlsx_bytes


def test_xlsx_basic():
    content = xlsx_bytes(
        [(datetime(2025, 1, 15), "Аренда", 1000.5, "Офис"), ("2025-02", "ФОТ", 5, None)]
    )
    rows = ExcelSource(content, "f.xlsx").fetch()
    assert [r.row for r in rows] == [2, 3]
    assert rows[0].period == datetime(2025, 1, 15) and rows[0].amount == 1000.5
    assert rows[1].cost_center is None


def test_xlsx_column_synonyms_and_order():
    content = xlsx_bytes(
        [(500, "IT", "2025-01", "Сеть")], headers=["Amount", "Department", " DATE ", "Category"]
    )
    row = ExcelSource(content, "f.xlsx").fetch()[0]
    assert (row.period, row.category, row.amount, row.cost_center) == ("2025-01", "Сеть", 500, "IT")


def test_xlsx_skips_empty_rows_keeps_numbers():
    content = xlsx_bytes(
        [("2025-01", "A", 1, None), (None, None, None, None), ("2025-01", "B", 2, None)]
    )
    assert [r.row for r in ExcelSource(content, "f.xlsx").fetch()] == [2, 4]


def test_missing_required_columns():
    content = xlsx_bytes([("2025-01", 5)], headers=["Период", "Что-то"])
    with pytest.raises(SourceError) as exc:
        ExcelSource(content, "f.xlsx").fetch()
    assert "Статья" in exc.value.message and "Сумма" in exc.value.message


@pytest.mark.parametrize(
    ("text", "encoding"),
    [
        ("Период;Статья;Сумма;ЦФО\n01.2025;Аренда;1 234,56;Офис\n", "cp1251"),
        ('Период,Статья,Сумма\n2025-01,Аренда,"1 234,56"\n', "utf-8-sig"),
        ("Период\tСтатья\tСумма\n2025-01\tАренда\t1234,56\n", "utf-8"),
    ],
)
def test_csv_encoding_and_delimiter(text, encoding):
    rows, errors = validate_rows(ExcelSource(text.encode(encoding), "f.csv").fetch(), "fact")
    assert not errors
    assert rows[0].category == "Аренда" and str(rows[0].amount) == "1234.56"


@pytest.mark.parametrize(
    ("content", "name", "fragment"),
    [
        (b"", "f.xlsx", "пуст"),
        (b"not excel", "f.xlsx", "Не удалось прочитать"),
        (b"data", "f.pdf", "XLSX, XLS и CSV"),
        (xlsx_bytes([]), "f.xlsx", "не содержит строк"),
    ],
)
def test_unreadable_files(content, name, fragment):
    with pytest.raises(SourceError) as exc:
        ExcelSource(content, name).fetch()
    assert fragment in exc.value.message


@pytest.mark.parametrize("kind", ["fact", "budget"])
def test_template_is_loadable(kind):
    rows, errors = validate_rows(ExcelSource(build_template(kind), "t.xlsx").fetch(), kind)
    assert not errors and len(rows) == 2


def test_manual_source():
    rows = ManualSource([{"period": "2025-01", "category": "A", "amount": 1}, {}]).fetch()
    assert len(rows) == 1 and rows[0].row == 1
    with pytest.raises(SourceError):
        ManualSource([]).fetch()
    with pytest.raises(SourceError):
        ManualSource(["x"]).fetch()
