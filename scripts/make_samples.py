"""Генерирует тестовые файлы для загрузки в папку samples/.

Запуск: python scripts/make_samples.py
Данные вымышленные и детерминированные (фиксированное зерно), период — июль–декабрь 2025.
"""

import calendar
import csv
import random
from datetime import date
from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).resolve().parent.parent / "samples"
YEAR, MONTHS = 2025, range(7, 13)
COST_CENTERS = ("Офис", "Склад", "Продажи")

# категория → (месячная сумма по месяцам июль–декабрь, число платежей в месяц)
FACT = {
    "Аренда": ((400_000,) * 6, 1),
    "Зарплата": ((1_800_000, 1_800_000, 1_850_000, 1_950_000, 1_950_000, 2_100_000), 2),
    "Закупки товара": ((2_400_000, 2_250_000, 2_600_000, 2_900_000, 3_100_000, 3_600_000), 9),
    "Маркетинг": ((300_000, 280_000, 320_000, 220_000, 200_000, 180_000), 5),
    "Логистика": ((350_000, 340_000, 380_000, 420_000, 450_000, 520_000), 7),
    "Командировки": ((120_000, 90_000, 60_000, 0, 0, 0), 3),  # исчезает в 4 квартале
    "Связь и ПО": ((0, 0, 0, 150_000, 150_000, 160_000), 2),  # появляется в 4 квартале
}
BUDGET = {
    "Аренда": (400_000,) * 6,
    "Зарплата": (1_850_000,) * 6,
    "Закупки товара": (2_500_000,) * 3 + (2_800_000,) * 3,
    "Маркетинг": (300_000,) * 6,
    "Логистика": (350_000,) * 3 + (400_000,) * 3,
    "Командировки": (100_000,) * 3 + (50_000,) * 3,
    "Связь и ПО": (0, 0, 0, 120_000, 120_000, 120_000),
}
HEADERS = ["Период", "Статья", "Сумма", "ЦФО"]


def fact_rows() -> list[tuple]:
    """Платежи по дням: месячная сумма делится на случайные части без потери копеек."""
    rng = random.Random(42)
    rows = []
    for category, (monthly, payments) in FACT.items():
        for month, total in zip(MONTHS, monthly, strict=True):
            if not total:
                continue
            weights = [rng.uniform(0.5, 1.5) for _ in range(payments)]
            kopecks = [int(total * 100 * w / sum(weights)) for w in weights]
            kopecks[-1] += total * 100 - sum(kopecks)
            days = sorted(rng.sample(range(1, calendar.monthrange(YEAR, month)[1] + 1), payments))
            for day, amount in zip(days, kopecks, strict=True):
                center = (
                    "Офис" if category in ("Аренда", "Связь и ПО") else rng.choice(COST_CENTERS)
                )
                rows.append((date(YEAR, month, day), category, amount / 100, center))
    return sorted(rows)


def budget_rows() -> list[tuple]:
    return [
        (f"{YEAR}-{month:02}", category, total, "")
        for category, monthly in BUDGET.items()
        for month, total in zip(MONTHS, monthly, strict=True)
        if total
    ]


def save_xlsx(name: str, rows: list[tuple], headers=HEADERS) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(list(row))
    for cell in sheet["A"][1:]:
        if isinstance(cell.value, date):
            cell.number_format = "DD.MM.YYYY"
    for column, width in zip("ABCD", (14, 28, 16, 16), strict=True):
        sheet.column_dimensions[column].width = width
    workbook.save(OUT / name)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    fact = fact_rows()
    save_xlsx("01_fact_2025_h2.xlsx", fact)
    save_xlsx("02_budget_2025_h2.xlsx", budget_rows())

    # Исправленный декабрь: загрузка заменит факт за этот месяц (проверка версий)
    december = [r for r in fact if r[0].month == 12]
    december.append((date(YEAR, 12, 29), "Премии", 450_000, "Офис"))  # новая статья → сопоставление
    save_xlsx("03_fact_december_corrected.xlsx", december)

    # CSV в Windows-1251 с «;», русским форматом сумм и английскими заголовками
    with open(OUT / "04_fact_january_2026.csv", "w", encoding="cp1251", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(["Date", "Category", "Amount", "Department"])
        writer.writerow(["12.01.2026", "Аренда", "400 000,00", "Офис"])
        writer.writerow(["15.01.2026", "Зарплата", "2 000 000,00", "Офис"])
        writer.writerow(["янв 2026", "Логистика", "480 500,50", "Склад"])

    # Файл с ошибками: должен показать таблицу «строка — колонка — проблема»
    save_xlsx(
        "05_fact_with_errors.xlsx",
        [
            ("15.01.2026", "Аренда", 400_000, "Офис"),
            ("когда-нибудь", "Зарплата", 100_000, ""),
            ("16.01.2026", "", 5_000, ""),
            ("17.01.2026", "Маркетинг", "много", ""),
            (None, "Логистика", None, "Склад"),
        ],
    )
    print(f"Создано файлов: {len(list(OUT.iterdir()))} в {OUT.name}/")


if __name__ == "__main__":
    main()
