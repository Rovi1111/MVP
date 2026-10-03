"""Сохранённые расчёты: снимок результатов, AI-заключение, история."""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.errors import InvalidDataError, NotFoundError
from app.models import Analysis, User
from app.repositories.analyses import AnalysisRepository, PromptTemplateRepository
from app.services import ai_summary, analysis, charts, ollama, prompts
from app.services.audit import log_action
from app.services.settings import get_org_settings

KINDS = ("comparison",)


def build_snapshot(db: Session, user: User, kind: str, params: dict) -> tuple[str, dict]:
    """Выполняет расчёт и возвращает (заголовок, снимок результатов).

    В снимок входят сравнение периодов, данные диаграммы «факт и бюджет» и — только
    для AI-анализа — отклонения от бюджета за второй период (если бюджет загружен).
    Отчёт не зависит от последующих загрузок.
    """
    if kind != "comparison":
        raise InvalidDataError("Тип анализа должен быть comparison")
    cost_center_id = params.get("cost_center_id")
    comparison = analysis.run_comparison(
        db,
        user,
        params.get("period1"),
        params.get("period2"),
        cost_center_id=cost_center_id,
        category=params.get("category"),
        change_types=params.get("change_types") or None,
        sort=params.get("sort") or "delta",
        descending=params.get("descending", True),
    )
    p1, p2 = comparison["params"]["period1"], comparison["params"]["period2"]
    span = f"{min(p1['start'], p2['start'])}..{max(p1['end'], p2['end'])}"
    chart = analysis.run_fact_budget(
        db,
        user,
        span,
        cost_center_id=cost_center_id,
        budget_upload_id=params.get("budget_upload_id"),
        categories=params.get("chart_categories") or None,
        amount_min=params.get("amount_min"),
        amount_max=params.get("amount_max"),
    )
    try:
        plan_fact = analysis.run_plan_fact(
            db,
            user,
            params.get("period2"),
            budget_upload_id=params.get("budget_upload_id"),
            cost_center_id=cost_center_id,
        )
    except (InvalidDataError, NotFoundError):
        plan_fact = None  # бюджета нет — AI-анализ строится без отклонений от плана
    title = f"Сравнение: {p1['label']} → {p2['label']}"
    return title, {"comparison": comparison, "plan_fact": plan_fact, "chart": chart}


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
    """Диаграмма отчёта, построенная из сохранённого снимка (а не из текущих данных)."""
    chart = snapshot.get("chart")
    if not chart:
        return {}
    comparison = snapshot.get("comparison") or {}
    names = [r["category"] for r in comparison.get("all_rows", [])]
    names += [s["category"] for s in chart["series"]]
    title = f"Факт и бюджет: {chart['period']['label']}"
    figure = charts.fact_budget_figure(chart, title, charts.colors_for(names))
    return {"fact_budget": figure}
