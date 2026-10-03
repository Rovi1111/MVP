"""Расчёты: сравнение периодов, план-факт, ряды для графиков.

Только чистые функции: на вход — уже загруженные строки, на выход — результат.
Работа с БД вынесена в app/services/analysis.py.
"""

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from app.services.parsing import normalize_name
from app.services.periods import bucket_label, bucket_start, bucket_starts

ZERO = Decimal("0")
_PCT = Decimal("0.1")


class ChangeType(StrEnum):
    INCREASE = "increase"
    DECREASE = "decrease"
    NEW = "new"
    REMOVED = "removed"
    NO_CHANGE = "no_change"


class EmptyPeriodsError(ValueError):
    """В обоих сравниваемых периодах нет данных."""


def pct(delta: Decimal, base: Decimal) -> Decimal | None:
    """Изменение в процентах от базы; None, если база нулевая (деление на ноль)."""
    if base == 0:
        return None
    return (delta / abs(base) * 100).quantize(_PCT, rounding=ROUND_HALF_UP)


def _jsonable(data: dict) -> dict:
    """Decimal → float для JSON; суммы с двумя знаками переносятся без потерь."""
    return {k: float(v) if isinstance(v, Decimal) else v for k, v in data.items()}


def sum_by_category(rows: Iterable[tuple[str, Decimal]]) -> dict[str, Decimal]:
    """Суммирует строки (категория, сумма); дубли одной категории складываются."""
    totals: dict[str, Decimal] = {}
    for category, amount in rows:
        totals[category] = totals.get(category, ZERO) + Decimal(amount)
    return totals


# ---------- сравнение двух периодов ----------


@dataclass(frozen=True)
class ComparisonRow:
    category: str
    amount_p1: Decimal
    amount_p2: Decimal
    delta: Decimal
    pct_change: Decimal | None
    change_type: ChangeType

    def to_dict(self) -> dict:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class Comparison:
    rows: list[ComparisonRow]
    total_p1: Decimal
    total_p2: Decimal
    total_delta: Decimal
    total_pct: Decimal | None

    def to_dict(self) -> dict:
        totals = _jsonable(
            {
                "total_p1": self.total_p1,
                "total_p2": self.total_p2,
                "total_delta": self.total_delta,
                "total_pct": self.total_pct,
            }
        )
        return {"rows": [row.to_dict() for row in self.rows], **totals}


def classify_change(amount_p1: Decimal, amount_p2: Decimal) -> ChangeType:
    if amount_p1 == 0 and amount_p2 > 0:
        return ChangeType.NEW
    if amount_p1 > 0 and amount_p2 == 0:
        return ChangeType.REMOVED
    if amount_p2 > amount_p1:
        return ChangeType.INCREASE
    if amount_p2 < amount_p1:
        return ChangeType.DECREASE
    return ChangeType.NO_CHANGE


def compare_periods(
    rows_p1: Iterable[tuple[str, Decimal]], rows_p2: Iterable[tuple[str, Decimal]]
) -> Comparison:
    """Сравнивает два периода по категориям.

    rows_*: строки (категория, сумма), возможно с повторами категорий.
    Строки отсортированы по убыванию delta. Если данных нет в обоих периодах —
    EmptyPeriodsError.
    """
    rows_p1, rows_p2 = list(rows_p1), list(rows_p2)
    if not rows_p1 and not rows_p2:
        raise EmptyPeriodsError("В обоих периодах нет данных")
    first, second = sum_by_category(rows_p1), sum_by_category(rows_p2)

    rows = []
    for category in first.keys() | second.keys():
        amount_p1, amount_p2 = first.get(category, ZERO), second.get(category, ZERO)
        delta = amount_p2 - amount_p1
        rows.append(
            ComparisonRow(
                category=category,
                amount_p1=amount_p1,
                amount_p2=amount_p2,
                delta=delta,
                pct_change=pct(delta, amount_p1),
                change_type=classify_change(amount_p1, amount_p2),
            )
        )
    total_p1, total_p2 = sum(first.values(), ZERO), sum(second.values(), ZERO)
    return Comparison(
        rows=sort_rows(rows, "delta", descending=True),
        total_p1=total_p1,
        total_p2=total_p2,
        total_delta=total_p2 - total_p1,
        total_pct=pct(total_p2 - total_p1, total_p1),
    )


COMPARISON_SORT_KEYS = ("delta", "amount_p1", "amount_p2", "pct_change", "category")


def sort_rows(rows: Sequence, key: str = "delta", descending: bool = True) -> list:
    """Сортирует строки результата; пустые значения (н/д) всегда в конце."""
    if not rows:
        return []
    if not hasattr(rows[0], key):
        raise ValueError(f"Неизвестное поле сортировки: {key}")

    def name(row) -> str:
        return normalize_name(row.category)

    if key == "category":
        return sorted(rows, key=name, reverse=descending)
    known = [r for r in rows if getattr(r, key) is not None]
    unknown = [r for r in rows if getattr(r, key) is None]
    # при равных значениях порядок стабилен — по названию
    known.sort(key=name)
    known.sort(key=lambda r: getattr(r, key), reverse=descending)
    return known + sorted(unknown, key=name)


def filter_comparison(
    rows: Iterable[ComparisonRow],
    category: str | None = None,
    change_types: Iterable[str] | None = None,
) -> list[ComparisonRow]:
    """Фильтр по части названия категории и по типам изменения."""
    needle = normalize_name(category) if category else ""
    types = {ChangeType(t) for t in change_types} if change_types else None
    return [
        row
        for row in rows
        if (not needle or needle in normalize_name(row.category))
        and (types is None or row.change_type in types)
    ]


# ---------- план-факт ----------


@dataclass(frozen=True)
class PlanFactRow:
    category: str
    cost_center: str | None
    plan: Decimal
    fact: Decimal
    deviation: Decimal  # факт − план; положительное значение — перерасход
    deviation_pct: Decimal | None
    overspend: bool
    significant: bool  # отклонение больше порога

    def to_dict(self) -> dict:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class PlanFact:
    rows: list[PlanFactRow]
    total_plan: Decimal
    total_fact: Decimal
    total_deviation: Decimal
    total_deviation_pct: Decimal | None
    threshold_pct: Decimal

    def to_dict(self) -> dict:
        totals = _jsonable(
            {
                "total_plan": self.total_plan,
                "total_fact": self.total_fact,
                "total_deviation": self.total_deviation,
                "total_deviation_pct": self.total_deviation_pct,
                "threshold_pct": self.threshold_pct,
            }
        )
        return {"rows": [row.to_dict() for row in self.rows], **totals}


def plan_fact(
    plan_rows: Iterable[tuple[str, str | None, Decimal]],
    fact_rows: Iterable[tuple[str, str | None, Decimal]],
    threshold_pct: Decimal | float = 10,
    by_cost_center: bool = False,
) -> PlanFact:
    """Сравнивает факт с планом по категориям (и ЦФО, если by_cost_center).

    Строки: (категория, ЦФО или None, сумма). Отклонение = факт − план.
    При нулевом плане процент не считается (None); если при этом факт ненулевой,
    отклонение считается существенным.
    """
    threshold = Decimal(str(threshold_pct))

    def collect(rows) -> dict[tuple[str, str | None], Decimal]:
        totals: dict[tuple[str, str | None], Decimal] = {}
        for category, cost_center, amount in rows:
            key = (category, cost_center if by_cost_center else None)
            totals[key] = totals.get(key, ZERO) + Decimal(amount)
        return totals

    plans, facts = collect(plan_rows), collect(fact_rows)
    rows = []
    for key in plans.keys() | facts.keys():
        plan, fact = plans.get(key, ZERO), facts.get(key, ZERO)
        deviation = fact - plan
        deviation_pct = pct(deviation, plan)
        if deviation_pct is None:
            significant = deviation != 0
        else:
            significant = abs(deviation_pct) > threshold
        rows.append(
            PlanFactRow(
                category=key[0],
                cost_center=key[1],
                plan=plan,
                fact=fact,
                deviation=deviation,
                deviation_pct=deviation_pct,
                overspend=deviation > 0,
                significant=significant,
            )
        )
    rows.sort(key=lambda r: (-r.deviation, normalize_name(r.category), r.cost_center or ""))
    total_plan, total_fact = sum(plans.values(), ZERO), sum(facts.values(), ZERO)
    return PlanFact(
        rows=rows,
        total_plan=total_plan,
        total_fact=total_fact,
        total_deviation=total_fact - total_plan,
        total_deviation_pct=pct(total_fact - total_plan, total_plan),
        threshold_pct=threshold,
    )


# ---------- ряды для графиков ----------


def filter_totals(
    totals: dict[str, Decimal],
    categories: Iterable[str] | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
) -> dict[str, Decimal]:
    """Отбор данных для диаграмм: по списку категорий и диапазону сумм (включительно)."""
    wanted = {normalize_name(c) for c in categories} if categories else None
    return {
        name: amount
        for name, amount in totals.items()
        if (wanted is None or normalize_name(name) in wanted)
        and (amount_min is None or amount >= amount_min)
        and (amount_max is None or amount <= amount_max)
    }


def series_by_period(rows: Iterable[tuple[date, str, Decimal]], granularity: str = "month") -> dict:
    """Суммы по категориям в разрезе дней/месяцев/кварталов/лет для stacked bar.

    rows: (дата, категория, сумма). Возвращает подписи периодов, для каждой категории —
    ряд сумм и ряд долей в итоге периода (в процентах).
    """
    buckets: dict[date, dict[str, Decimal]] = {}
    for day, category, amount in rows:
        bucket = buckets.setdefault(bucket_start(day, granularity), {})
        bucket[category] = bucket.get(category, ZERO) + Decimal(amount)

    starts = sorted(buckets)
    totals = [sum(buckets[s].values(), ZERO) for s in starts]
    overall = sum_by_category((c, a) for b in buckets.values() for c, a in b.items())
    categories = sorted(overall, key=lambda c: (-overall[c], c))
    series = []
    for category in categories:
        amounts = [buckets[s].get(category, ZERO) for s in starts]
        series.append(
            {
                "category": category,
                "amounts": [float(a) for a in amounts],
                "shares": [
                    float(pct(a, t)) if t != 0 else None
                    for a, t in zip(amounts, totals, strict=True)
                ],
            }
        )
    return {
        "granularity": granularity,
        "periods": [bucket_label(s, granularity) for s in starts],
        "starts": [s.isoformat() for s in starts],
        "totals": [float(t) for t in totals],
        "series": series,
    }


def fact_budget_series(
    fact_rows: Iterable[tuple[date, str, Decimal]],
    budget_rows: Iterable[tuple[date, str, Decimal]] | None,
    start: date,
    end: date,
    granularity: str = "month",
) -> dict:
    """Данные диаграммы динамики: факт по шагам с разбивкой по категориям и линия бюджета.

    fact_rows: (дата, категория, сумма). budget_rows: (дата, детализация, сумма) или None,
    если бюджета нет. Шаг — день, месяц, квартал или год. В ось попадают все шаги периода,
    даже без данных. Квартальная строка бюджета сначала делится поровну на три месяца.
    По дням бюджет не показывается: он задаётся не детальнее месяца.
    """
    starts = bucket_starts(start, end, granularity)
    index = {bucket: i for i, bucket in enumerate(starts)}
    by_category: dict[str, list[Decimal]] = {}
    for day, category, amount in fact_rows:
        position = index.get(bucket_start(day, granularity))
        if position is not None and start <= day <= end:
            by_category.setdefault(category, [ZERO] * len(starts))[position] += Decimal(amount)
    totals = [
        sum((amounts[i] for amounts in by_category.values()), ZERO) for i in range(len(starts))
    ]

    budget = None
    if budget_rows is not None and granularity != "day":
        budget = [ZERO] * len(starts)
        for day, grain, amount in budget_rows:
            months = 3 if grain == "quarter" else 1
            first = bucket_start(day, "month")
            for offset in range(months):
                shifted = first.month - 1 + offset
                month = date(first.year + shifted // 12, shifted % 12 + 1, 1)
                position = index.get(bucket_start(month, granularity))
                if position is not None and start <= month <= end:
                    budget[position] += Decimal(amount) / months

    categories = sorted(by_category, key=lambda c: (-sum(by_category[c], ZERO), c))
    return {
        "granularity": granularity,
        "periods": [bucket_label(bucket, granularity) for bucket in starts],
        "starts": [bucket.isoformat() for bucket in starts],
        "totals": [float(total) for total in totals],
        "series": [
            {
                "category": category,
                "amounts": [float(a) for a in by_category[category]],
                "shares": [
                    float(pct(a, t)) if t != 0 else None
                    for a, t in zip(by_category[category], totals, strict=True)
                ],
            }
            for category in categories
        ],
        "budget": None if budget is None else [round(float(b), 2) for b in budget],
    }


def compare_halves(series: dict) -> dict | None:
    """Сравнивает первую и вторую половины ряда динамики по категориям.

    series — результат fact_budget_series(). При нечётном числе шагов средний шаг
    не учитывается, чтобы половины были равной длины. None — если шагов меньше двух
    или данных нет.
    """
    count = len(series["periods"])
    half = count // 2
    if half == 0 or not series["series"]:
        return None
    first = [(s["category"], Decimal(str(sum(s["amounts"][:half])))) for s in series["series"]]
    second = [
        (s["category"], Decimal(str(sum(s["amounts"][count - half :])))) for s in series["series"]
    ]
    result = compare_periods(first, second).to_dict()

    def label(start: int, stop: int) -> str:
        names = series["periods"][start:stop]
        return names[0] if len(names) == 1 else f"{names[0]} — {names[-1]}"

    return {**result, "label_p1": label(0, half), "label_p2": label(count - half, count)}
