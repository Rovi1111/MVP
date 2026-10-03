"""Подготовка данных для AI-анализа: только агрегаты, без сырых строк (чистые функции)."""

from decimal import Decimal
from string import Formatter

TOP_N = 5
PLAN_FACT_LIMIT = 10
STEP_NAMES = {"day": "день", "month": "месяц", "quarter": "квартал", "year": "год"}
PLACEHOLDERS: dict[str, str] = {
    "organization": "название организации",
    "period": "анализируемый период",
    "totals": "итоги за период: факт, бюджет, среднее, максимум и минимум",
    "dynamics": "факт и бюджет по месяцам (или кварталам)",
    "period1": "первая половина периода",
    "period2": "вторая половина периода",
    "top_increases": f"до {TOP_N} статей с наибольшим ростом (вторая половина к первой)",
    "top_decreases": f"до {TOP_N} статей с наибольшим снижением",
    "new_categories": "статьи, появившиеся во второй половине периода",
    "removed_categories": "статьи, исчезнувшие во второй половине периода",
    "plan_fact": "существенные отклонения факта от бюджета по статьям",
    "data": "все перечисленные данные одним блоком",
}
_DATA_PLACEHOLDERS = set(PLACEHOLDERS) - {"organization", "period", "period1", "period2"}
_NOTHING = "нет"


class OutdatedSnapshotError(ValueError):
    """Снимок сохранён в старом формате (сравнение двух периодов)."""


def money(value) -> str:
    return f"{Decimal(str(value)):,.2f}".replace(",", " ").replace(".", ",")


def percent(value) -> str:
    if value is None:
        return "н/д"
    return f"{Decimal(str(value)):+.1f} %".replace(".", ",")


def _lines(items: list[str]) -> str:
    return "\n".join(f"— {item}" for item in items) if items else _NOTHING


def _deviation(fact: float, budget: float) -> str:
    delta = fact - budget
    share = percent(delta / budget * 100) if budget else "н/д"
    return f"{money(delta)} ({share})"


def _totals_text(dynamics: dict) -> str:
    totals, labels = dynamics["totals"], dynamics["periods"]
    step = STEP_NAMES.get(dynamics.get("granularity", "month"), "шаг")
    fact = sum(totals)
    parts = [f"Период: {dynamics['period']['label']}, шагов ({step}): {len(totals)}."]
    if dynamics.get("categories"):
        parts.append(f"Только статьи: {', '.join(dynamics['categories'])}.")
    parts.append(f"Факт всего: {money(fact)}.")
    if dynamics.get("budget") is not None:
        budget = sum(dynamics["budget"])
        parts.append(
            f"Бюджет всего: {money(budget)}, отклонение факта: {_deviation(fact, budget)}."
        )
    else:
        parts.append("Бюджет не загружен.")
    if totals:
        highest, lowest = (
            max(range(len(totals)), key=totals.__getitem__),
            min(range(len(totals)), key=totals.__getitem__),
        )
        parts.append(
            f"В среднем за {step}: {money(fact / len(totals))}. "
            f"Максимум: {labels[highest]} — {money(totals[highest])}. "
            f"Минимум: {labels[lowest]} — {money(totals[lowest])}."
        )
    return " ".join(parts)


def _dynamics_text(dynamics: dict) -> str:
    budget = dynamics.get("budget")
    lines = []
    for index, label in enumerate(dynamics["periods"]):
        line = f"{label}: факт {money(dynamics['totals'][index])}"
        if budget is not None:
            line += f", бюджет {money(budget[index])}, отклонение " + _deviation(
                dynamics["totals"][index], budget[index]
            )
        lines.append(line)
    return _lines(lines)


def _change_line(row: dict) -> str:
    return (
        f"{row['category']}: {money(row['amount_p1'])} → {money(row['amount_p2'])} "
        f"({money(row['delta'])}, {percent(row['pct_change'])})"
    )


def _plan_fact_text(plan_fact: dict | None, categories: list[str]) -> str:
    if plan_fact is None:
        return "данных о бюджете нет"
    rows = plan_fact["rows"]
    if categories:
        rows = [r for r in rows if r["category"] in categories]
    significant = sorted((r for r in rows if r["significant"]), key=lambda r: -abs(r["deviation"]))
    header = f"Порог существенности: {plan_fact['threshold_pct']:g} %."
    if not significant:
        return f"{header} Существенных отклонений по статьям нет."
    lines = []
    for row in significant[:PLAN_FACT_LIMIT]:
        verdict = "перерасход" if row["overspend"] else "экономия"
        lines.append(
            f"{row['category']}: план {money(row['plan'])}, факт {money(row['fact'])}, отклонение "
            f"{money(row['deviation'])} ({percent(row['deviation_pct'])}) — {verdict}"
        )
    return f"{header} За весь период:\n{_lines(lines)}"


def build_aggregates(snapshot: dict, organization: str) -> dict[str, str]:
    """Значения плейсхолдеров промпта из снимка расчёта.

    snapshot: {"dynamics": ряд по месяцам/кварталам, "halves": сравнение половин периода | None,
    "plan_fact": отклонения от бюджета | None}. В результат попадают только итоги
    и топ-списки — не отдельные операции.
    """
    dynamics = snapshot.get("dynamics")
    if not dynamics:
        raise OutdatedSnapshotError
    halves = snapshot.get("halves")
    values = {
        "organization": organization,
        "period": dynamics["period"]["label"],
        "totals": _totals_text(dynamics),
        "dynamics": _dynamics_text(dynamics),
        "plan_fact": _plan_fact_text(snapshot.get("plan_fact"), dynamics.get("categories") or []),
    }
    if halves is None:
        short = "период слишком короткий для сравнения половин"
        values |= {
            "period1": values["period"],
            "period2": values["period"],
            "top_increases": short,
            "top_decreases": short,
            "new_categories": short,
            "removed_categories": short,
        }
    else:
        rows = halves["rows"]

        def of_type(change_type: str, reverse: bool) -> list[dict]:
            found = [r for r in rows if r["change_type"] == change_type]
            return sorted(found, key=lambda r: r["delta"], reverse=reverse)[:TOP_N]

        values |= {
            "period1": halves["label_p1"],
            "period2": halves["label_p2"],
            "top_increases": _lines([_change_line(r) for r in of_type("increase", True)]),
            "top_decreases": _lines([_change_line(r) for r in of_type("decrease", False)]),
            "new_categories": _lines(
                [f"{r['category']}: {money(r['amount_p2'])}" for r in of_type("new", True)]
            ),
            "removed_categories": _lines(
                [
                    f"{r['category']}: было {money(r['amount_p1'])}"
                    for r in of_type("removed", False)
                ]
            ),
        }
    halves_title = f"«{values['period1']}» → «{values['period2']}»"
    values["data"] = "\n".join(
        [
            f"Итоги: {values['totals']}",
            f"Динамика по периодам:\n{values['dynamics']}",
            f"Рост по статьям ({halves_title}):\n{values['top_increases']}",
            f"Снижение по статьям:\n{values['top_decreases']}",
            f"Появившиеся статьи:\n{values['new_categories']}",
            f"Исчезнувшие статьи:\n{values['removed_categories']}",
            f"Отклонения от бюджета по статьям. {values['plan_fact']}",
        ]
    )
    return values


def template_problems(text: str) -> list[str]:
    """Проверяет шаблон промпта; пустой список — шаблон корректен."""
    try:
        names = {name for _, name, _, _ in Formatter().parse(text) if name is not None}
    except ValueError:
        return ["Непарная фигурная скобка. Чтобы вывести скобку как текст, удвойте её: {{ или }}"]
    problems = []
    unknown = sorted(names - set(PLACEHOLDERS))
    if unknown:
        listed = ", ".join("{" + name + "}" for name in unknown)
        problems.append(f"Неизвестные плейсхолдеры: {listed}")
    if not names & _DATA_PLACEHOLDERS:
        problems.append(
            "Шаблон должен содержать хотя бы один плейсхолдер с данными, например {data}"
        )
    return problems


def render_prompt(template_text: str, aggregates: dict[str, str]) -> str:
    return template_text.format(**aggregates)


DEFAULT_TEMPLATES = [
    {
        "name": "Для финансового аналитика / руководителя",
        "scenario": "analyst",
        "text": (
            "Ты — опытный финансовый аналитик. Подготовь аналитическое заключение о динамике "
            "расходов организации «{organization}» за период «{period}» для руководителя.\n\n"
            "Данные (только агрегаты, суммы в рублях):\n{data}\n\n"
            "Структура заключения:\n"
            "1. Общий тренд: как менялись совокупные расходы от периода к периоду, сезонность, "
            "пики и спады.\n"
            "2. Крупнейшие росты: статьи, вероятные драйверы, вклад в общее изменение.\n"
            "3. Крупнейшие снижения.\n"
            "4. Новые и исчезнувшие статьи: что это означает для структуры затрат.\n"
            "5. Исполнение бюджета: периоды и статьи с существенным перерасходом или экономией.\n"
            "6. Рекомендации: 2–4 практических шага по корректировке бюджета и контролю затрат.\n\n"
            "Используй финансовую терминологию (структура затрат, отклонение от плана, "
            "исполнение бюджета). Опирайся только на приведённые цифры, ничего не выдумывай. "
            "Если данных по разделу нет — так и напиши. Отвечай на русском языке."
        ),
    },
    {
        "name": "Простым языком",
        "scenario": "plain",
        "text": (
            "Ты помогаешь владельцу бизнеса «{organization}» разобраться, как менялись расходы "
            "за период «{period}». У него нет финансового образования, поэтому объясняй простыми "
            "словами, без терминов.\n\n"
            "Вот цифры (суммы в рублях):\n{data}\n\n"
            "Расскажи по порядку:\n"
            "1. Что в целом происходило с расходами: росли, снижались, в какие месяцы были "
            "самые большие и самые маленькие траты.\n"
            "2. На что стали тратить заметно больше.\n"
            "3. На что стали тратить заметно меньше.\n"
            "4. Какие расходы появились впервые и какие исчезли.\n"
            "5. Где потратили больше, чем планировали, и где сэкономили.\n"
            "6. Что стоит сделать: 2–4 простых и конкретных совета.\n\n"
            "Пиши коротко и понятно, опирайся только на эти цифры и ничего не придумывай. "
            "Если чего-то нет в данных — скажи об этом. Отвечай на русском языке."
        ),
    },
]
