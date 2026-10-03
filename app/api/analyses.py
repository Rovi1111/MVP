import json

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import csrf_protect, require
from app.errors import NotFoundError
from app.models import Analysis, User
from app.permissions import Permission, has_permission
from app.repositories.analyses import AnalysisRepository
from app.schemas import AiRun, AnalysisBrief, AnalysisCreate, AnalysisOut, EmailReport
from app.services import analyses, charts, reports
from app.services.audit import log_action
from app.services.ollama import OllamaError

router = APIRouter(prefix="/analyses", tags=["analyses"], dependencies=[Depends(csrf_protect)])
_viewer = require(Permission.ANALYTICS_VIEW)


def _out(record: Analysis, ai_error: str | None = None) -> AnalysisOut:
    return AnalysisOut(
        id=record.id,
        kind=record.kind,
        title=record.title,
        params=record.params,
        result=record.result,
        ai_text=record.ai_text,
        ai_error=ai_error,
        prompt_template_id=record.prompt_template_id,
        author=record.author.login,
        created_at=record.created_at,
    )


@router.get("", response_model=list[AnalysisBrief])
def list_analyses(user: User = Depends(_viewer), db: Session = Depends(get_db)):
    return [
        AnalysisBrief(
            id=a.id, kind=a.kind, title=a.title, created_at=a.created_at, has_ai=bool(a.ai_text)
        )
        for a in AnalysisRepository(db, user.org_id).recent()
    ]


@router.post("", response_model=AnalysisOut, status_code=status.HTTP_201_CREATED)
def create_analysis(
    data: AnalysisCreate, user: User = Depends(_viewer), db: Session = Depends(get_db)
):
    """Выполняет расчёт и сохраняет его снимок. run_ai=true — сразу запросить AI-заключение.

    Если Ollama недоступна, расчёт всё равно сохраняется, а причина возвращается в ai_error.
    """
    params = data.model_dump(exclude={"kind", "run_ai", "template_id"})
    record = analyses.save_analysis(db, user, data.kind, params)
    ai_error = None
    if data.run_ai:
        if not has_permission(user.role, Permission.AI_RUN):
            ai_error = "Недостаточно прав для запуска AI-анализа"
        else:
            try:
                record = analyses.run_ai(db, user, record.id, data.template_id)
            except OllamaError as exc:
                ai_error = exc.message
    return _out(record, ai_error)


@router.get("/{analysis_id}", response_model=AnalysisOut)
def get_analysis(analysis_id: int, user: User = Depends(_viewer), db: Session = Depends(get_db)):
    return _out(analyses.get_analysis(db, user, analysis_id))


@router.post("/{analysis_id}/ai", response_model=AnalysisOut)
def run_ai(
    analysis_id: int,
    data: AiRun,
    user: User = Depends(require(Permission.AI_RUN)),
    db: Session = Depends(get_db),
):
    """AI-заключение по сохранённому расчёту. 503 — если Ollama недоступна."""
    return _out(analyses.run_ai(db, user, analysis_id, data.template_id))


@router.get("/{analysis_id}/charts/{name}")
def analysis_chart(
    analysis_id: int,
    name: str,
    format: str = Query("json", pattern="^(json|png)$"),
    user: User = Depends(_viewer),
    db: Session = Depends(get_db),
):
    """Диаграмма сохранённого расчёта: pie1, pie2, stacked, plan_fact."""
    record = analyses.get_analysis(db, user, analysis_id)
    figure = analyses.snapshot_figures(record.result).get(name)
    if figure is None:
        raise NotFoundError("В этом анализе нет такой диаграммы")
    if format == "json":
        return json.loads(charts.figure_json(figure))
    log_action(db, user, "export", "chart", record.id, {"chart": name, "format": "png"})
    db.commit()
    headers = {"Content-Disposition": f'attachment; filename="analysis_{record.id}_{name}.png"'}
    return Response(charts.figure_png(figure), media_type="image/png", headers=headers)


@router.get("/{analysis_id}/export")
def export_report(
    analysis_id: int,
    format: str = Query("pdf", pattern="^(pdf|xlsx)$"),
    user: User = Depends(require(Permission.REPORTS)),
    db: Session = Depends(get_db),
):
    """Единый отчёт: PDF (с диаграммами) или Excel (числа как числа)."""
    content, mime, name = reports.export_report(db, user, analysis_id, format)
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    return Response(content, media_type=mime, headers=headers)


@router.post("/{analysis_id}/email")
def email_report(
    analysis_id: int,
    data: EmailReport,
    user: User = Depends(require(Permission.REPORTS)),
    db: Session = Depends(get_db),
):
    """Отправляет отчёт на email. 422 — если SMTP не настроен, 502 — если сервер отказал."""
    reports.email_report(db, user, analysis_id, data.to, data.formats)
    return {"detail": f"Отчёт отправлен на {data.to.strip()}"}
