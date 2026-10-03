"""Unit-тесты чистых расчётов: сравнение периодов, план-факт, ряды."""

from datetime import date
from decimal import Decimal as D

import pytest

from app.services.analytics import (
    ChangeType,
    EmptyPeriodsError,
    classify_change,
    compare_periods,
    filter_comparison,
    pct,
    plan_fact,
    series_by_period,
    shares,
    sort_rows,
)


def by_category(result):
    return {row.category: row for row in result.rows}


# ---------- сравнение ----------


def test_all_change_types():
    result = compare_periods(
        [("Рост", D("100")), ("Снижение", D("200")), ("Исчезла", D("50")), ("Ровно", D("70"))],
        [("Рост", D("150")), ("Снижение", D("120")), ("Новая", D("30")), ("Ровно", D("70"))],
    )
    rows = by_category(result)
    assert {name: row.change_type for name, row in rows.items()} == {
        "Рост": ChangeType.INCREASE,
        "Снижение": ChangeType.DECREASE,
        "Исчезла": ChangeType.REMOVED,
        "Новая": ChangeType.NEW,
        "Ровно": ChangeType.NO_CHANGE,
    }
    assert (rows["Рост"].delta, rows["Рост"].pct_change) == (D("50"), D("50.0"))
    assert (rows["Снижение"].delta, rows["Снижение"].pct_change) == (D("-80"), D("-40.0"))
    assert (rows["Исчезла"].amount_p2, rows["Исчезла"].pct_change) == (D("0"), D("-100.0"))
    assert (rows["Ровно"].delta, rows["Ровно"].pct_change) == (D("0"), D("0.0"))


def test_new_category_has_no_percent():
    row = by_category(compare_periods([], [("Новая", D("30"))]))["Новая"]
    assert row.amount_p1 == 0 and row.delta == D("30")
    assert row.pct_change is None  # без деления на ноль
    assert row.change_type == ChangeType.NEW


def test_totals_and_total_percent():
    result = compare_periods([("A", D("100")), ("B", D("100"))], [("A", D("250"))])
    assert (result.total_p1, result.total_p2, result.total_delta) == (D("200"), D("250"), D("50"))
    assert result.total_pct == D("25.0")


def test_total_percent_is_none_when_first_period_empty():
    result = compare_periods([], [("A", D("10"))])
    assert result.total_p1 == 0 and result.total_pct is None


def test_duplicate_rows_are_summed():
    result = compare_periods(
        [("A", D("10.10")), ("A", D("0.20")), ("A", D("5"))], [("A", D("1")), ("A", D("2"))]
    )
    row = result.rows[0]
    assert len(result.rows) == 1
    assert (row.amount_p1, row.amount_p2, row.delta) == (D("15.30"), D("3"), D("-12.30"))


def test_default_sort_is_delta_descending():
    result = compare_periods(
        [("A", D("100")), ("B", D("100")), ("C", D("100")), ("D", D("100"))],
        [("A", D("90")), ("B", D("300")), ("C", D("100")), ("D", D("150"))],
    )
    assert [r.category for r in result.rows] == ["B", "D", "C", "A"]
    assert [r.delta for r in result.rows] == sorted((r.delta for r in result.rows), reverse=True)


def test_both_periods_empty_is_error():
    with pytest.raises(EmptyPeriodsError):
        compare_periods([], [])
    with pytest.raises(EmptyPeriodsError):
        compare_periods(iter(()), iter(()))


def test_one_empty_period_is_not_error():
    assert [r.change_type for r in compare_periods([("A", D("5"))], []).rows] == [
        ChangeType.REMOVED
    ]
    assert [r.change_type for r in compare_periods([], [("A", D("5"))]).rows] == [ChangeType.NEW]


def test_zero_amounts():
    result = compare_periods([("A", D("0")), ("B", D("0"))], [("A", D("0")), ("B", D("10"))])
    rows = by_category(result)
    assert rows["A"].change_type == ChangeType.NO_CHANGE and rows["A"].pct_change is None
    assert rows["B"].change_type == ChangeType.NEW  # 0 в первом периоде = категории не было
    assert result.total_p1 == 0 and result.total_pct is None


def test_rows_that_cancel_out_to_zero_count_as_absent():
    result = compare_periods([("A", D("100")), ("A", D("-100"))], [("A", D("40"))])
    assert result.rows[0].change_type == ChangeType.NEW


@pytest.mark.parametrize(
    ("p1", "p2", "expected", "expected_pct"),
    [
        ("-100", "-50", ChangeType.INCREASE, "50.0"),  # сторно уменьшилось
        ("-50", "-100", ChangeType.DECREASE, "-100.0"),
        ("-50", "0", ChangeType.INCREASE, "100.0"),
        ("0", "-20", ChangeType.DECREASE, None),
        ("-10", "30", ChangeType.INCREASE, "400.0"),
    ],
)
def test_negative_amounts(p1, p2, expected, expected_pct):
    row = compare_periods([("A", D(p1))], [("A", D(p2))]).rows[0]
    assert row.change_type == expected
    assert row.pct_change == (D(expected_pct) if expected_pct else None)


def test_kopecks_are_exact():
    result = compare_periods([("A", D("0.10")), ("A", D("0.20"))], [("A", D("0.30"))])
    assert result.rows[0].delta == 0 and result.rows[0].change_type == ChangeType.NO_CHANGE


def test_percent_rounding_half_up():
    assert pct(D("1"), D("3")) == D("33.3")
    assert pct(D("2"), D("3")) == D("66.7")
    assert pct(D("0.125"), D("100")) == D("0.1")
    assert pct(D("0.15"), D("100")) == D("0.2")
    assert pct(D("5"), D("0")) is None


def test_classify_change_boundaries():
    assert classify_change(D("0"), D("0.01")) == ChangeType.NEW
    assert classify_change(D("0.01"), D("0")) == ChangeType.REMOVED
    assert classify_change(D("0"), D("0")) == ChangeType.NO_CHANGE
    assert classify_change(D("1.00"), D("1.0")) == ChangeType.NO_CHANGE


def test_sort_rows_by_every_key_and_none_last():
    result = compare_periods(
        [("Б", D("100")), ("а", D("10"))], [("Б", D("50")), ("а", D("40")), ("В", D("5"))]
    )
    assert [r.category for r in sort_rows(result.rows, "category", False)] == ["а", "Б", "В"]
    assert [r.category for r in sort_rows(result.rows, "amount_p2", True)] == ["Б", "а", "В"]
    assert [r.category for r in sort_rows(result.rows, "delta", False)] == ["Б", "В", "а"]
    # у новой категории процент н/д — она в конце при любом направлении
    assert [r.category for r in sort_rows(result.rows, "pct_change", True)] == ["а", "Б", "В"]
    assert [r.category for r in sort_rows(result.rows, "pct_change", False)] == ["Б", "а", "В"]
    with pytest.raises(ValueError):
        sort_rows(result.rows, "nope")
    assert sort_rows([], "delta") == []


def test_filter_by_name_and_type():
    result = compare_periods(
        [("Сухой корм", D("10")), ("Влажный корм", D("10")), ("Лакомства", D("5"))],
        [("Сухой корм", D("20")), ("Влажный корм", D("5")), ("Ёлки", D("1"))],
    )
    assert {r.category for r in filter_comparison(result.rows, "КОРМ")} == {
        "Сухой корм",
        "Влажный корм",
    }
    assert [r.category for r in filter_comparison(result.rows, "елки")] == ["Ёлки"]
    assert {r.category for r in filter_comparison(result.rows, None, ["new", "removed"])} == {
        "Ёлки", "Лакомства",
    }  # fmt: skip
    assert [r.category for r in filter_comparison(result.rows, "корм", ["increase"])] == [
        "Сухой корм"
    ]
    assert len(filter_comparison(result.rows)) == 4
    with pytest.raises(ValueError):
        filter_comparison(result.rows, None, ["unknown"])


def test_comparison_to_dict_is_json_ready():
    data = compare_periods([("A", D("100.10"))], [("B", D("5"))]).to_dict()
    assert data["total_p1"] == 100.1 and data["total_pct"] == -95.0
    new = next(r for r in data["rows"] if r["category"] == "B")
    assert new == {
        "category": "B", "amount_p1": 0.0, "amount_p2": 5.0, "delta": 5.0,
        "pct_change": None, "change_type": "new",
    }  # fmt: skip


# ---------- план-факт ----------


def test_plan_fact_basic_and_overspend():
    result = plan_fact(
        [("Аренда", None, D("100")), ("ФОТ", None, D("200")), ("Реклама", None, D("50"))],
        [("Аренда", None, D("100")), ("ФОТ", None, D("230")), ("Реклама", None, D("46"))],
        threshold_pct=10,
    )
    rows = {r.category: r for r in result.rows}
    assert (rows["ФОТ"].deviation, rows["ФОТ"].deviation_pct) == (D("30"), D("15.0"))
    assert rows["ФОТ"].overspend and rows["ФОТ"].significant
    assert (rows["Реклама"].deviation, rows["Реклама"].deviation_pct) == (D("-4"), D("-8.0"))
    assert not rows["Реклама"].overspend and not rows["Реклама"].significant
    assert rows["Аренда"].deviation == 0 and not rows["Аренда"].overspend
    assert [r.category for r in result.rows] == [
        "ФОТ",
        "Аренда",
        "Реклама",
    ]  # по убыванию отклонения
    assert (result.total_plan, result.total_fact, result.total_deviation) == (
        D("350"),
        D("376"),
        D("26"),
    )
    assert result.total_deviation_pct == D("7.4")


def test_plan_fact_threshold_is_strict_and_configurable():
    plan, fact = [("A", None, D("100"))], [("A", None, D("110"))]
    assert (
        not plan_fact(plan, fact, threshold_pct=10).rows[0].significant
    )  # ровно порог — не превышение
    assert plan_fact(plan, fact, threshold_pct=D("9.9")).rows[0].significant
    assert plan_fact(plan, fact, threshold_pct=0).rows[0].significant
    saving = plan_fact(plan, [("A", None, D("50"))], threshold_pct=10).rows[0]
    assert saving.significant and not saving.overspend  # существенная экономия — не перерасход


def test_plan_fact_zero_plan():
    result = plan_fact([("A", None, D("0"))], [("A", None, D("10")), ("Б", None, D("5"))])
    for row in result.rows:
        assert row.plan == 0 and row.deviation_pct is None
        assert row.overspend and row.significant
    assert result.total_deviation_pct is None
    idle = plan_fact([("A", None, D("0"))], [("A", None, D("0"))]).rows[0]
    assert not idle.overspend and not idle.significant


def test_plan_fact_missing_fact():
    row = plan_fact([("A", None, D("100"))], []).rows[0]
    assert (row.fact, row.deviation, row.deviation_pct) == (D("0"), D("-100"), D("-100.0"))
    assert not row.overspend and row.significant


def test_plan_fact_duplicates_and_cost_centers():
    plan = [("A", "Офис", D("100")), ("A", "Склад", D("50")), ("A", "Офис", D("10"))]
    fact = [("A", "Офис", D("130")), ("A", None, D("5"))]
    merged = plan_fact(plan, fact)
    assert len(merged.rows) == 1
    assert (merged.rows[0].plan, merged.rows[0].fact, merged.rows[0].cost_center) == (
        D("160"),
        D("135"),
        None,
    )

    split = {r.cost_center: r for r in plan_fact(plan, fact, by_cost_center=True).rows}
    assert set(split) == {"Офис", "Склад", None}
    assert (split["Офис"].plan, split["Офис"].fact, split["Офис"].overspend) == (
        D("110"),
        D("130"),
        True,
    )
    assert (split["Склад"].fact, split[None].plan) == (D("0"), D("0"))


def test_plan_fact_empty():
    result = plan_fact([], [])
    assert result.rows == [] and result.total_plan == 0 and result.total_deviation_pct is None


# ---------- ряды для графиков ----------


def test_shares():
    assert shares({"A": D("75"), "B": D("25"), "C": D("0")}) == [
        {"category": "A", "amount": 75.0, "share": 75.0},
        {"category": "B", "amount": 25.0, "share": 25.0},
    ]
    assert shares({}) == []
    assert shares({"A": D("0"), "B": D("0")}) == []  # все суммы нулевые — «нет данных»
    assert shares({"A": D("-5")}) == []


@pytest.mark.parametrize(
    ("granularity", "periods"),
    [
        ("day", ["15.01.2025", "20.01.2025", "03.02.2025", "01.04.2025"]),
        ("month", ["январь 2025", "февраль 2025", "апрель 2025"]),
        ("quarter", ["1 кв. 2025", "2 кв. 2025"]),
        ("year", ["2025 год"]),
    ],
)
def test_series_granularity(granularity, periods):
    rows = [
        (date(2025, 1, 15), "A", D("10")),
        (date(2025, 1, 20), "A", D("5")),
        (date(2025, 2, 3), "B", D("30")),
        (date(2025, 4, 1), "A", D("1")),
    ]
    data = series_by_period(rows, granularity)
    assert data["periods"] == periods
    assert sum(data["totals"]) == 46.0


def test_series_amounts_and_shares():
    rows = [
        (date(2025, 1, 15), "A", D("30")),
        (date(2025, 1, 20), "B", D("10")),
        (date(2025, 2, 3), "B", D("5")),
    ]
    data = series_by_period(rows, "month")
    assert [s["category"] for s in data["series"]] == ["A", "B"]  # по убыванию общей суммы
    assert data["series"][0] == {"category": "A", "amounts": [30.0, 0.0], "shares": [75.0, 0.0]}
    assert data["series"][1]["shares"] == [25.0, 100.0]
    assert series_by_period([], "month")["periods"] == []
