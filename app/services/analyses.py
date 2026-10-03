"""Сохранённые расчёты: снимок результатов, AI-заключение, история."""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.errors import InvalidDataError, NotFoundError
from app.models import Analysis, User
from app.repositories.analyses import AnalysisRepository, PromptTemplateRepository
from app.services import ai_summary, analysis, analytics, charts, ollama, prompts
from app.services.audit import log_action
from app.services.settings import get_org_settings

KINDS = ("dynamics",)
# Для AI ряд длиннее трёх лет укрупняется до кварталов, чтобы промпт оставался компактным
AI_MAX_MONTHS = 36


def build_snapshot(db: Session, user: User, kind: str, params: dict) -> tuple[str, dict]:
    """Выполняет расчёт динамики и возвращает (заголовок, снимок результатов).

    chart — данные диаграммы с выбранным шагом; dynamics, halves и plan_fact — агрегаты
    для AI-анализа (по месяцам, для длинных периодов — по кварталам).
    Отчёт не зависит от последующих загрузок.
    """
    if kind != "dynamics":
        raise InvalidDataError("Тип анализа должен быть dynamics")
    filters = {
        "budget_upload_id": params.get("budget_upload_id"),
        "categories": params.get("categories") or None,
    }
    period = params.get("period")
    chart = analysis.run_fact_budget(
        db, user, period, granularity=params.get("granularity") or "month", **filters
    )
    span = f"{chart['period']['start']}..{chart['period']['end']}"
    dynamics = analysis.run_fact_budget(db, user, span, granularity="month", **filters)
    if len(dynamics["periods"]) > AI_MAX_MONTHS:
        dynamics = analysis.run_fact_budget(db, user, span, granularity="quarter", **filters)
    try:
        plan_fact = analysis.run_plan_fact(
            db, user, span, budget_upload_id=params.get("budget_upload_id")
        )
    except (InvalidDataError, NotFoundError):
        plan_fact = None  # бюджета нет — AI-анализ строится без отклонений от плана
    snapshot = {
        "chart": chart,
        "dynamics": dynamics,
        "halves": analytics.compare_halves(dynamics),
        "plan_fact": plan_fact,
    }
    return f"Динамика расходов: {chart['period']['label']}", snapshot


def save_analysis(db: Session, user: User, kind: str, params: dict) -> Analysis:
    title, snapshot = build_snapshot(db, user, kind, params)
    # Decimal не сериализуется в JSON-колонку
    clean_params = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in params.items()}
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
    try:
        aggregates = ai_summary.build_aggregates(record.result, user.organization.name)
    except ai_summary.OutdatedSnapshotError:
        raise InvalidDataError(
            "Этот анализ сохранён в старом формате. Выполните расчёт заново на странице "
            "«Анализ расходов»"
        ) from None
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
    """Диаграмма отчёта, построенная из сохранённого снимка (а не из текущих данных)."""
    chart = snapshot.get("chart")
    if not chart:
        return {}
    names = [s["category"] for s in (snapshot.get("dynamics") or chart)["series"]]
    names += [s["category"] for s in chart["series"]]
    title = f"Факт и бюджет: {chart['period']['label']}"
    return {"fact_budget": charts.fact_budget_figure(chart, title, charts.colors_for(names))}
