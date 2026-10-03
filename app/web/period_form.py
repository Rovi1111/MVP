"""Поля выбора периода на формах: детализация (день/месяц/квартал/год/диапазон) + значения."""

from datetime import date, timedelta

from starlette.datastructures import QueryParams

from app.services.periods import MONTH_NAMES, bucket_start

MODES = {
    "day": "День",
    "month": "Месяц",
    "quarter": "Квартал",
    "year": "Год",
    "range": "Произвольный диапазон",
}


def _previous(start: date, mode: str) -> date:
    """Начало предыдущего дня/месяца/квартала/года."""
    return bucket_start(start - timedelta(days=1), mode)


def _fields(prefix: str, day: date, end: date | None = None) -> dict[str, str]:
    return {
        f"{prefix}_day": day.isoformat(),
        f"{prefix}_year": str(day.year),
        f"{prefix}_month": str(day.month),
        f"{prefix}_quarter": str((day.month - 1) // 3 + 1),
        f"{prefix}_from": day.isoformat(),
        f"{prefix}_to": (end or day).isoformat(),
    }


def defaults(bounds: dict, prefixes: tuple[str, ...], mode: str = "month") -> dict[str, str]:
    """Значения по умолчанию: последний период с данными и предыдущие перед ним."""
    last = date.fromisoformat(bounds["fact_to"]) if bounds.get("fact_to") else date.today()
    values = {"mode": mode}
    current = bucket_start(last, mode)
    quarter = (last.month - 1) // 3 + 1
    for prefix in reversed(prefixes):
        values |= _fields(prefix, current, last if prefix == prefixes[-1] else None)
        # квартал отсчитывается своей цепочкой: иначе соседние месяцы дают один и тот же квартал
        values[f"{prefix}_quarter"] = str(quarter)
        current = _previous(current, mode)
        quarter = quarter - 1 or 4
    return values


def years(bounds: dict) -> list[int]:
    this_year = date.today().year
    first = date.fromisoformat(bounds["fact_from"]).year if bounds.get("fact_from") else this_year
    last = date.fromisoformat(bounds["fact_to"]).year if bounds.get("fact_to") else this_year
    return list(range(min(first, this_year) - 1, max(last, this_year) + 2))


def compose(params: QueryParams | dict, prefix: str) -> str:
    """Собирает строку периода (как в API) из полей формы."""
    mode = params.get("mode", "month")
    get = lambda name: (params.get(f"{prefix}_{name}") or "").strip()  # noqa: E731
    if mode == "day":
        return get("day")
    if mode == "quarter":
        return f"{get('year')}-Q{get('quarter')}"
    if mode == "year":
        return get("year")
    if mode == "range":
        return f"{get('from')}..{get('to')}"
    return f"{get('year')}-{get('month').zfill(2)}"


CONTEXT = {"modes": MODES, "month_names": MONTH_NAMES}
