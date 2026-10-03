"""Сохранённые расчёты: снимок результатов, AI-заключение, история."""

from sqlalchemy.orm import Session

from app.errors import InvalidDataError, NotFoundError
from app.models import Analysis, User
from app.repositories.analyses import AnalysisRepository, PromptTemplateRepository
from app.services import ai_summary, analysis, charts, ollama, prompts
from app.services.audit import log_action
from app.services.settings import get_org_settings

KINDS = ("comparison", "plan_fact")


def build_snapshot(db: Session, user: User, kind: str, params: dict) -> tuple[str, dict]:
    """Выполняет расчёт и возвращает (заголовок, снимок результатов).

    Снимок сравнения дополняется план-фактом за второй период (если бюджет загружен)
    и рядом для графика динамики — чтобы отчёт не зависел от последующих загрузок.
    """
    if kind == "comparison":
        comparison = analysis.run_comparison(
            db,
            user,
            params.get("period1"),
            params.get("period2"),
            cost_center_id=params.get("cost_center_id"),
            category=params.get("category"),
            change_types=params.get("change_types") or None,
            sort=params.get("sort") or "delta",
            descending=params.get("descending", True),
        )
        p1, p2 = comparison["params"]["period1"], comparison["params"]["period2"]
        span = f"{min(p1['start'], p2['start'])}..{max(p1['end'], p2['end'])}"
        granularity = params.get("granularity") or "month"
        series = analysis.run_series(db, user, span, granularity, params.get("cost_center_id"))
        try:
            plan_fact = analysis.run_plan_fact(
                db,
                user,
                params.get("period2"),
                budget_upload_id=params.get("budget_upload_id"),
                cost_center_id=params.get("cost_center_id"),
            )
        except (InvalidDataError, NotFoundError):
            plan_fact = None  # бюджета нет — отчёт строится без план-факта
        title = f"Сравнение: {p1['label']} → {p2['label']}"
        return title, {"comparison": comparison, "plan_fact": plan_fact, "series": series}
    if kind == "plan_fact":
        plan_fact = analysis.run_plan_fact(
            db,
            user,
            params.get("period"),
            budget_upload_id=params.get("budget_upload_id"),
            by_cost_center=bool(params.get("by_cost_center")),
            cost_center_id=params.get("cost_center_id"),
            threshold_pct=params.get("threshold_pct"),
        )
        title = f"План-факт: {plan_fact['params']['period']['label']}"
        return title, {"comparison": None, "plan_fact": plan_fact, "series": None}
    raise InvalidDataError("Тип анализа должен быть comparison или plan_fact")


def save_analysis(db: Session, user: User, kind: str, params: dict) -> Analysis:
    title, snapshot = build_snapshot(db, user, kind, params)
    clean_params = {
        k: (str(v) if k == "threshold_pct" and v is not None else v) for k, v in params.items()
    }
    record = AnalysisRepository(db, user.org_id).add(
        Analysis(kind=kind, title=title, params=clean_params, result=snapshot, author_id=user.id)
    )
    log_action(db, user, "create", "analysis", record.id, {"title": title})
    db.commit()
    return record


def get_analysis(db: Session, user: User, analysis_id: int) -> Analysis:
    record = AnalysisRepository(db, user.org_id).get(analysis_id)
    if record is None:
        raise NotFoundError("Анализ не найден")
    return record


def build_prompt(db: Session, user: User, record: Analysis, template_id: int | None) -> tuple:
    """Возвращает (шаблон, готовый промпт). В промпт попадают только агрегаты."""
    templates = prompts.list_templates(db, user.org_id, only_active=True)
    if template_id is None:
        if not templates:
            raise InvalidDataError("Нет ни одного активного шаблона промпта")
        template = templates[0]
    else:
        template = PromptTemplateRepository(db, user.org_id).get(template_id)
        if template is None or not template.is_active:
            raise NotFoundError("Шаблон промпта не найден")
    aggregates = ai_summary.build_aggregates(record.result, user.organization.name)
    return template, ai_summary.render_prompt(template.text, aggregates)


def run_ai(db: Session, user: User, analysis_id: int, template_id: int | None = None) -> Analysis:
    """Запрашивает AI-заключение у Ollama и сохраняет его в анализе."""
    record = get_analysis(db, user, analysis_id)
    template, prompt = build_prompt(db, user, record, template_id)
    settings = get_org_settings(db, user.org_id)
    db.commit()  # не держим транзакцию открытой, пока модель думает
    try:
        text = ollama.get_client(settings).generate(prompt)
    except ollama.OllamaError as exc:
        log_action(db, user, "ai_analysis_failed", "analysis", record.id, {"error": exc.message})
        db.commit()
        raise
    record.ai_text = text
    record.prompt_template_id = template.id
    details = {"template": template.name, "model": settings.ollama_model}
    log_action(db, user, "ai_analysis", "analysis", record.id, details)
    db.commit()
    return record


def snapshot_figures(snapshot: dict) -> dict:
    """Диаграммы отчёта, построенные из сохранённого снимка (а не из текущих данных)."""
    figures = {}
    comparison, plan_fact = snapshot.get("comparison"), snapshot.get("plan_fact")
    names = [r["category"] for r in (comparison or {}).get("all_rows", [])]
    names += [r["category"] for r in (plan_fact or {}).get("rows", [])]
    colors = charts.colors_for(names)
    if comparison:
        for key, period in (("pie1", "period1"), ("pie2", "period2")):
            shares = comparison[f"shares_p{key[-1]}"]
            figures[key] = charts.pie_figure(shares, comparison["params"][period]["label"], colors)
        if snapshot.get("series"):
            series = snapshot["series"]
            title = f"Расходы: {series['period']['label']}"
            figures["stacked"] = charts.stacked_bar_figure(series, title, colors)
    if plan_fact:
        title = f"План-факт: {plan_fact['params']['period']['label']}"
        figures["plan_fact"] = charts.plan_fact_figure(plan_fact["rows"], title)
    return figures
