"""Разбор периодов из входных данных (чистые функции).

Данные хранятся по дням. Если во входной строке указан месяц или квартал,
запись ставится на первый день периода, а исходная детализация запоминается в grain.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.models import Grain

_MONTH_PREFIXES = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "мая": 5, "мае": 5, "июн": 6,
    "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4}
_EXCEL_EPOCH = date(1899, 12, 30)
_MIN_YEAR, _MAX_YEAR = 1990, 2100

_RE_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T\s].*)?$")
_RE_RU_DATE = re.compile(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})$")
_RE_YEAR_MONTH = re.compile(r"^(\d{4})[-./](\d{1,2})$")
_RE_MONTH_YEAR = re.compile(r"^(\d{1,2})[-./](\d{4})$")
_RE_WORD_YEAR = re.compile(r"^([a-zа-яё]+)\.?[\s,]*(\d{4})$")
_RE_YEAR_WORD = re.compile(r"^(\d{4})[\s,]*([a-zа-яё]+)\.?$")
_RE_YEAR_Q = re.compile(r"^(\d{4})[-\s/]*q([1-4])$")
_RE_Q_YEAR = re.compile(r"^q([1-4])[-\s/]*(\d{4})$")
_RE_KV_YEAR = re.compile(r"^([1-4]|i{1,3}|iv)\s*-?\s*(?:й\s*)?кв(?:артал)?\.?\s*(\d{4})$")
_RE_YEAR_KV = re.compile(r"^(\d{4})[-\s/]*([1-4])\s*кв(?:артал)?\.?$")
_RE_YEAR_SUFFIX = re.compile(r"\s*(?:г\.?|года|год)$")

FORMATS_HINT = (
    "ожидается дата (15.01.2025, 2025-01-15), месяц (2025-01, 01.2025, янв 2025) "
    "или квартал (2025-Q1, 1 кв 2025)"
)


class PeriodError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedPeriod:
    date: date
    grain: Grain


def quarter_start(year: int, quarter: int) -> date:
    return date(year, 3 * quarter - 2, 1)


def _make(year: int, month: int, day: int, grain: Grain, original) -> ParsedPeriod:
    if not _MIN_YEAR <= year <= _MAX_YEAR:
        raise PeriodError(f"Год вне допустимого диапазона: «{original}»")
    try:
        return ParsedPeriod(date(year, month, day), grain)
    except ValueError:
        raise PeriodError(f"Несуществующая дата: «{original}»") from None


def _from_excel_serial(number: float, original) -> ParsedPeriod:
    # Числовая ячейка в колонке периода — порядковый номер дня Excel
    if not 20000 <= number <= 80000:
        raise PeriodError(f"Период не распознан: «{original}» — {FORMATS_HINT}")
    day = _EXCEL_EPOCH + timedelta(days=int(number))
    return _make(day.year, day.month, day.day, Grain.DAY, original)


def parse_period(value) -> ParsedPeriod:
    """Распознаёт период из ячейки файла или поля формы."""
    if isinstance(value, datetime):
        return _make(value.year, value.month, value.day, Grain.DAY, value)
    if isinstance(value, date):
        return _make(value.year, value.month, value.day, Grain.DAY, value)
    if isinstance(value, bool):
        raise PeriodError(f"Период не распознан: «{value}»")
    if isinstance(value, int | float):
        return _from_excel_serial(float(value), value)

    text = _RE_YEAR_SUFFIX.sub("", str(value).strip().lower()).strip()
    if not text:
        raise PeriodError("Период не указан")

    if m := _RE_ISO_DATE.match(text):
        return _make(int(m[1]), int(m[2]), int(m[3]), Grain.DAY, value)
    if m := _RE_RU_DATE.match(text):
        return _make(int(m[3]), int(m[2]), int(m[1]), Grain.DAY, value)
    if m := _RE_YEAR_MONTH.match(text):
        return _make(int(m[1]), int(m[2]), 1, Grain.MONTH, value)
    if m := _RE_MONTH_YEAR.match(text):
        return _make(int(m[2]), int(m[1]), 1, Grain.MONTH, value)
    if m := _RE_YEAR_Q.match(text):
        return _make(int(m[1]), 3 * int(m[2]) - 2, 1, Grain.QUARTER, value)
    if m := _RE_Q_YEAR.match(text):
        return _make(int(m[2]), 3 * int(m[1]) - 2, 1, Grain.QUARTER, value)
    if m := _RE_KV_YEAR.match(text):
        quarter = _ROMAN.get(m[1]) or int(m[1])
        return _make(int(m[2]), 3 * quarter - 2, 1, Grain.QUARTER, value)
    if m := _RE_YEAR_KV.match(text):
        return _make(int(m[1]), 3 * int(m[2]) - 2, 1, Grain.QUARTER, value)
    for pattern, word_group, year_group in ((_RE_WORD_YEAR, 1, 2), (_RE_YEAR_WORD, 2, 1)):
        if (m := pattern.match(text)) and (month := _MONTH_PREFIXES.get(m[word_group][:3])):
            return _make(int(m[year_group]), month, 1, Grain.MONTH, value)
    if re.fullmatch(r"\d{5}(?:\.0+)?", text):
        return _from_excel_serial(float(text), value)
    raise PeriodError(f"Период не распознан: «{value}» — {FORMATS_HINT}")


# ---------- диапазоны для аналитики ----------

MONTH_NAMES = [
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]  # fmt: skip
GRANULARITIES = ("day", "month", "quarter", "year")
RANGE_HINT = (
    "ожидается день (2025-01-15), месяц (2025-01), квартал (2025-Q1), год (2025) "
    "или диапазон через «..» (2025-01-10..2025-02-20)"
)


@dataclass(frozen=True)
class PeriodRange:
    """Период анализа: включительно с start по end."""

    start: date
    end: date
    label: str

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


def month_end(day: date) -> date:
    following = date(day.year + day.month // 12, day.month % 12 + 1, 1)
    return following - timedelta(days=1)


def grain_end(day: date, grain: str) -> date:
    """Последний день периода, который начинается в day и имеет детализацию grain."""
    if grain == Grain.MONTH:
        return month_end(day)
    if grain == Grain.QUARTER:
        return month_end(date(day.year, day.month + 2, 1))
    if grain == "year":
        return date(day.year, 12, 31)
    return day


def bucket_start(day: date, granularity: str) -> date:
    """Начало дня/месяца/квартала/года, в который попадает дата."""
    if granularity == "month":
        return day.replace(day=1)
    if granularity == "quarter":
        return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)
    if granularity == "year":
        return date(day.year, 1, 1)
    return day


def bucket_label(start: date, granularity: str) -> str:
    if granularity == "month":
        return f"{MONTH_NAMES[start.month - 1]} {start.year}"
    if granularity == "quarter":
        return f"{(start.month - 1) // 3 + 1} кв. {start.year}"
    if granularity == "year":
        return f"{start.year} год"
    return start.strftime("%d.%m.%Y")


def _single_range(text: str) -> PeriodRange:
    text = text.strip()
    if re.fullmatch(r"\d{4}", text):
        start = _make(int(text), 1, 1, Grain.DAY, text).date
        return PeriodRange(start, grain_end(start, "year"), bucket_label(start, "year"))
    try:
        parsed = parse_period(text)
    except PeriodError:
        raise PeriodError(f"Период не распознан: «{text}» — {RANGE_HINT}") from None
    return PeriodRange(
        parsed.date, grain_end(parsed.date, parsed.grain), bucket_label(parsed.date, parsed.grain)
    )


def parse_range(text: str | None) -> PeriodRange:
    """Разбирает период анализа: день, месяц, квартал, год или «начало..конец»."""
    if not text or not text.strip():
        raise PeriodError("Период не указан")
    if ".." not in text:
        return _single_range(text)
    left, right = (part.strip() for part in text.split("..", 1))
    start, end = _single_range(left).start, _single_range(right).end
    if start > end:
        raise PeriodError(f"Начало периода позже конца: «{text}»")
    return PeriodRange(start, end, f"{start:%d.%m.%Y} — {end:%d.%m.%Y}")


def whole_months(period: PeriodRange) -> PeriodRange:
    """Расширяет период до границ календарных месяцев."""
    start, end = period.start.replace(day=1), month_end(period.end)
    if (start, end) == (period.start, period.end):
        return period
    return PeriodRange(start, end, f"{start:%d.%m.%Y} — {end:%d.%m.%Y}")
