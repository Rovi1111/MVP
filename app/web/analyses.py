"""Сохранённые анализы и AI-заключения."""

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require
from app.errors import AppError
from app.models import User
from app.permissions import Permission
from app.repositories.analyses import AnalysisRepository
from app.services import analyses, charts, prompts, reports
from app.services.ollama import OllamaError
from app.services.settings import get_org_settings
from app.web.common import can, render
from app.web.dashboard import _int, read_comparison_params, read_plan_fact_params

router = APIRouter(prefix="/analyses")
_viewer = require(Permission.ANALYTICS_VIEW)


def _ai_output(request, user, record, error: str | None = None, status_code: int = 200):
    context = {"analysis": record, "error": error}
    return render(request, "partials/ai_output.html", context, user, status_code)


@router.post("")
async def create(request: Request, user: User = Depends(_viewer), db: Session = Depends(get_db)):
    """Сохраняет расчёт с текущими параметрами формы; action=ai — ещё и запускает AI."""
    form = await request.form()
    kind = form.get("kind", "")
    try:
        reader = read_plan_fact_params if kind == "plan_fact" else read_comparison_params
        record = analyses.save_analysis(db, user, kind, reader(form))
    except AppError as exc:
        return render(request, "partials/alert.html", {"message": exc.message}, user)
    if form.get("action") != "ai":
        return _ai_output(request, user, record)
    if not can(user, Permission.AI_RUN):
        return _ai_output(request, user, record, "Недостаточно прав для запуска AI-анализа")
    try:
        record = analyses.run_ai(db, user, record.id, _int(form, "template_id"))
    except (OllamaError, AppError) as exc:
        return _ai_output(request, user, record, exc.message)
    return _ai_output(request, user, record)


@router.get("")
def history(request: Request, user: User = Depends(_viewer), db: Session = Depends(get_db)):
    context = {"analyses": AnalysisRepository(db, user.org_id).recent()}
    return render(request, "analyses.html", context, user)


@router.get("/{analysis_id}")
def detail(
    request: Request, analysis_id: int, user: User = Depends(_viewer), db: Session = Depends(get_db)
):
    record = analyses.get_analysis(db, user, analysis_id)
    figures = analyses.snapshot_figures(record.result)
    chart_data = {
        name: {
            "figure": charts.figure_json(figure),
            "png_url": f"/api/analyses/{record.id}/charts/{name}?format=png",
        }
        for name, figure in figures.items()
    }
    context = {
        "analysis": record,
        "snapshot": record.result,
        "charts": chart_data,
        "templates": prompts.list_templates(db, user.org_id, only_active=True)
        if can(user, Permission.AI_RUN)
        else [],
        "smtp_configured": get_org_settings(db, user.org_id).smtp_configured,
    }
    return render(request, "analysis_detail.html", context, user)


@router.post("/{analysis_id}/ai")
def rerun_ai(
    request: Request,
    analysis_id: int,
    template_id: str = Form(""),
    user: User = Depends(require(Permission.AI_RUN)),
    db: Session = Depends(get_db),
):
    record = analyses.get_analysis(db, user, analysis_id)
    try:
        record = analyses.run_ai(db, user, record.id, int(template_id) if template_id else None)
    except AppError as exc:
        return _ai_output(request, user, record, exc.message)
    return _ai_output(request, user, record)


@router.post("/{analysis_id}/email")
def email(
    request: Request,
    analysis_id: int,
    to: str = Form(""),
    formats: list[str] = Form(default=["pdf"]),
    user: User = Depends(require(Permission.REPORTS)),
    db: Session = Depends(get_db),
):
    try:
        reports.email_report(db, user, analysis_id, to, formats)
    except AppError as exc:
        return render(request, "partials/alert.html", {"message": exc.message}, user)
    context = {"message": f"Отчёт отправлен на {to.strip()}", "kind": "ok"}
    return render(request, "partials/alert.html", context, user)
