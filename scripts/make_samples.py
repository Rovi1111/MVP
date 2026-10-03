"""Генерирует тестовые файлы для загрузки в папку samples/.

Запуск: python scripts/make_samples.py
Данные вымышленные и детерминированные (фиксированное зерно), период — 2024–2025 годы:
два года факта по дням с ростом, сезонностью, появившейся и исчезнувшей статьями.
"""

import calendar
import csv
import random
from datetime import date
from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).resolve().parent.parent / "samples"
# 24 месяца: январь 2024 — декабрь 2025
MONTHS = [(year, month) for year in (2024, 2025) for month in range(1, 13)]
COST_CENTERS = ("Офис", "Склад", "Продажи")
# Сезонность: коэффициент к месячной сумме (пик в конце года, спад летом)
SEASON = (0.95, 0.92, 1.0, 1.0, 1.02, 0.95, 0.9, 0.9, 1.0, 1.08, 1.12, 1.3)
FLAT = (1.0,) * 12

# категория → (база в месяц, рост за год, сезонность, платежей в месяц,
#             первый и последний месяц по счёту от января 2024)
FACT = {
    "Аренда": (400_000, 0.05, FLAT, 1, 0, 23),
    "Зарплата": (1_700_000, 0.10, FLAT, 2, 0, 23),
    "Закупки товара": (2_200_000, 0.22, SEASON, 9, 0, 23),
    "Маркетинг": (320_000, -0.25, SEASON, 5, 0, 23),
    "Логистика": (300_000, 0.30, SEASON, 7, 0, 23),
    "Командировки": (110_000, -0.10, FLAT, 3, 0, 20),  # исчезают с октября 2025
    "Связь и ПО": (140_000, 0.08, FLAT, 2, 12, 23),  # появляются с января 2025
}
# категория → месячный план на 2024 и 2025 годы
BUDGET = {
    "Аренда": (400_000, 420_000),
    "Зарплата": (1_750_000, 1_900_000),
    "Закупки товара": (2_400_000, 2_700_000),
    "Маркетинг": (300_000, 280_000),
    "Логистика": (320_000, 380_000),
    "Командировки": (100_000, 80_000),
    "Связь и ПО": (0, 130_000),
}
HEADERS = ["Период", "Статья", "Сумма", "ЦФО"]


def monthly_total(category: str, index: int) -> int:
    """Сумма категории за месяц с номером index (0 — январь 2024), округлённая до тысяч."""
    base, growth, season, _, first, last = FACT[category]
    if not first <= index <= last:
        return 0
    month = MONTHS[index][1]
    return round(base * (1 + growth) ** (index / 12) * season[month - 1], -3)


def fact_rows() -> list[tuple]:
    """Платежи по дням: месячная сумма делится на случайные части без потери копеек."""
    rng = random.Random(42)
    rows = []
    for category, (*_, payments, _first, _last) in FACT.items():
        for index, (year, month) in enumerate(MONTHS):
            total = monthly_total(category, index)
            if not total:
                continue
            weights = [rng.uniform(0.5, 1.5) for _ in range(payments)]
            kopecks = [int(total * 100 * w / sum(weights)) for w in weights]
            kopecks[-1] += total * 100 - sum(kopecks)
            days = sorted(rng.sample(range(1, calendar.monthrange(year, month)[1] + 1), payments))
            for day, amount in zip(days, kopecks, strict=True):
                center = (
                    "Офис" if category in ("Аренда", "Связь и ПО") else rng.choice(COST_CENTERS)
                )
                rows.append((date(year, month, day), category, amount / 100, center))
    return sorted(rows)


def budget_rows() -> list[tuple]:
    return [
        (f"{year}-{month:02}", category, plan[year - 2024], "")
        for category, plan in BUDGET.items()
        for year, month in MONTHS
        if plan[year - 2024]
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
    save_xlsx("01_fact_2024_2025.xlsx", fact)
    save_xlsx("02_budget_2024_2025.xlsx", budget_rows())

    # Исправленный декабрь: загрузка заменит факт за этот месяц (проверка версий)
    december = [r for r in fact if (r[0].year, r[0].month) == (2025, 12)]
    december.append((date(2025, 12, 29), "Премии", 450_000, "Офис"))  # новая статья → сопоставление
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
