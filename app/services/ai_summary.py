"""Подготовка данных для AI-анализа: только агрегаты, без сырых строк (чистые функции)."""

from decimal import Decimal
from string import Formatter

TOP_N = 5
PLAN_FACT_LIMIT = 10
PLACEHOLDERS: dict[str, str] = {
    "organization": "название организации",
    "period1": "первый период (или период план-факта)",
    "period2": "второй период",
    "totals": "итоги по периодам и общее изменение",
    "top_increases": f"до {TOP_N} крупнейших ростов",
    "top_decreases": f"до {TOP_N} крупнейших снижений",
    "new_categories": "новые категории",
    "removed_categories": "исчезнувшие категории",
    "plan_fact": "итоги план-факта и существенные отклонения",
    "data": "все перечисленные данные одним блоком",
}
_DATA_PLACEHOLDERS = set(PLACEHOLDERS) - {"organization", "period1", "period2"}
_NOTHING = "нет"


def money(value) -> str:
    return f"{Decimal(str(value)):,.2f}".replace(",", " ").replace(".", ",")


def percent(value) -> str:
    if value is None:
        return "н/д"
    return f"{Decimal(str(value)):+.1f} %".replace(".", ",")


def _lines(items: list[str]) -> str:
    return "\n".join(f"— {item}" for item in items) if items else _NOTHING


def _change_line(row: dict) -> str:
    return (
        f"{row['category']}: {money(row['amount_p1'])} → {money(row['amount_p2'])} "
        f"({money(row['delta'])}, {percent(row['pct_change'])})"
    )


def _plan_fact_text(plan_fact: dict | None) -> str:
    if plan_fact is None:
        return "данных о бюджете нет"
    header = (
        f"Период: {plan_fact['params']['period']['label']}. "
        f"План {money(plan_fact['total_plan'])}, факт {money(plan_fact['total_fact'])}, "
        f"отклонение {money(plan_fact['total_deviation'])} "
        f"({percent(plan_fact['total_deviation_pct'])}). "
        f"Порог существенности: {plan_fact['threshold_pct']:g} %."
    )
    significant = sorted(
        (r for r in plan_fact["rows"] if r["significant"]), key=lambda r: -abs(r["deviation"])
    )[:PLAN_FACT_LIMIT]
    if not significant:
        return f"{header}\nСущественных отклонений нет."
    lines = []
    for row in significant:
        name = row["category"] + (f" [{row['cost_center']}]" if row.get("cost_center") else "")
        verdict = "перерасход" if row["overspend"] else "экономия"
        lines.append(
            f"{name}: план {money(row['plan'])}, факт {money(row['fact'])}, отклонение "
            f"{money(row['deviation'])} ({percent(row['deviation_pct'])}) — {verdict}"
        )
    return f"{header}\nСущественные отклонения:\n{_lines(lines)}"


def build_aggregates(snapshot: dict, organization: str) -> dict[str, str]:
    """Значения плейсхолдеров промпта из снимка расчёта.

    snapshot: {"comparison": {...} | None, "plan_fact": {...} | None}.
    В результат попадают только итоги и топ-списки — не отдельные операции.
    """
    comparison, plan_fact = snapshot.get("comparison"), snapshot.get("plan_fact")
    values = {"organization": organization, "plan_fact": _plan_fact_text(plan_fact)}
    if comparison is None:
        label = plan_fact["params"]["period"]["label"] if plan_fact else _NOTHING
        only_plan_fact = "не рассчитывалось (анализ только план-факта)"
        values |= {
            "period1": label,
            "period2": label,
            "totals": only_plan_fact,
            "top_increases": only_plan_fact,
            "top_decreases": only_plan_fact,
            "new_categories": only_plan_fact,
            "removed_categories": only_plan_fact,
        }
    else:
        rows = comparison.get("all_rows") or comparison["rows"]
        params = comparison["params"]

        def of_type(change_type: str, reverse: bool) -> list[dict]:
            found = [r for r in rows if r["change_type"] == change_type]
            return sorted(found, key=lambda r: r["delta"], reverse=reverse)[:TOP_N]

        scope = f" ЦФО: {params['cost_center']}." if params.get("cost_center") else ""
        values |= {
            "period1": params["period1"]["label"],
            "period2": params["period2"]["label"],
            "totals": (
                f"{params['period1']['label']}: {money(comparison['total_p1'])}; "
                f"{params['period2']['label']}: {money(comparison['total_p2'])}; "
                f"изменение: {money(comparison['total_delta'])} "
                f"({percent(comparison['total_pct'])}). Категорий: {len(rows)}.{scope}"
            ),
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
    values["data"] = "\n".join(
        [
            f"Итоги: {values['totals']}",
            f"Крупнейшие росты:\n{values['top_increases']}",
            f"Крупнейшие снижения:\n{values['top_decreases']}",
            f"Новые категории:\n{values['new_categories']}",
            f"Исчезнувшие категории:\n{values['removed_categories']}",
            f"План-факт: {values['plan_fact']}",
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
            "Ты — опытный финансовый аналитик. Подготовь аналитическое заключение о расходах "
            "организации «{organization}» для руководителя.\n\n"
            "Данные (только агрегаты, суммы в рублях):\n{data}\n\n"
            "Структура заключения:\n"
            "1. Общий тренд: динамика совокупных расходов между «{period1}» и «{period2}».\n"
            "2. Крупнейшие росты: статьи, вероятные драйверы, вклад в общее изменение.\n"
            "3. Крупнейшие снижения.\n"
            "4. Новые и исчезнувшие категории: что это означает для структуры затрат.\n"
            "5. Существенные отклонения от бюджета: перерасходы и экономия.\n"
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
            "Ты помогаешь владельцу бизнеса «{organization}» разобраться в расходах. У него нет "
            "финансового образования, поэтому объясняй простыми словами, без терминов.\n\n"
            "Вот цифры (суммы в рублях):\n{data}\n\n"
            "Расскажи по порядку:\n"
            "1. Что в целом произошло с расходами между «{period1}» и «{period2}»: выросли, "
            "снизились, насколько.\n"
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
