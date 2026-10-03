"""Шаблоны промптов для AI-анализа."""

from sqlalchemy.orm import Session

from app.errors import ConflictError, InvalidDataError, NotFoundError
from app.models import PromptTemplate, User
from app.repositories.analyses import AnalysisRepository, PromptTemplateRepository
from app.services.ai_summary import DEFAULT_TEMPLATES, template_problems
from app.services.audit import log_action


def ensure_defaults(db: Session, org_id: int) -> None:
    """Создаёт шаблоны «из коробки», если у организации нет ни одного (без commit)."""
    repo = PromptTemplateRepository(db, org_id)
    if not repo.list():
        for item in DEFAULT_TEMPLATES:
            repo.add(PromptTemplate(**item))


def list_templates(db: Session, org_id: int, only_active: bool = False):
    ensure_defaults(db, org_id)
    db.commit()
    return PromptTemplateRepository(db, org_id).list(only_active)


def _validate(repo, name: str, text: str, exclude_id: int | None = None) -> None:
    if not name:
        raise InvalidDataError("Название шаблона не может быть пустым")
    if not text.strip():
        raise InvalidDataError("Текст шаблона не может быть пустым")
    problems = template_problems(text)
    if problems:
        raise InvalidDataError("; ".join(problems))
    if any(t.name == name and t.id != exclude_id for t in repo.list()):
        raise ConflictError(f"Шаблон «{name}» уже существует")


def create_template(db: Session, actor: User, name: str, text: str, scenario: str = ""):
    ensure_defaults(db, actor.org_id)
    repo = PromptTemplateRepository(db, actor.org_id)
    name = name.strip()
    _validate(repo, name, text)
    template = repo.add(PromptTemplate(name=name, text=text, scenario=scenario.strip()))
    log_action(db, actor, "create", "prompt_template", template.id, {"name": name})
    db.commit()
    return template


def update_template(
    db: Session,
    actor: User,
    template_id: int,
    *,
    name: str | None = None,
    text: str | None = None,
    scenario: str | None = None,
    is_active: bool | None = None,
):
    repo = PromptTemplateRepository(db, actor.org_id)
    template = repo.get(template_id)
    if template is None:
        raise NotFoundError("Шаблон не найден")
    new_name = template.name if name is None else name.strip()
    new_text = template.text if text is None else text
    _validate(repo, new_name, new_text, exclude_id=template.id)
    template.name, template.text = new_name, new_text
    if scenario is not None:
        template.scenario = scenario.strip()
    if is_active is not None:
        template.is_active = is_active
    log_action(db, actor, "update", "prompt_template", template.id, {"name": new_name})
    db.commit()
    return template


def delete_template(db: Session, actor: User, template_id: int) -> None:
    repo = PromptTemplateRepository(db, actor.org_id)
    template = repo.get(template_id)
    if template is None:
        raise NotFoundError("Шаблон не найден")
    if len(repo.list()) == 1:
        raise ConflictError("Нельзя удалить единственный шаблон")
    log_action(db, actor, "delete", "prompt_template", template.id, {"name": template.name})
    # В сохранённых анализах остаётся текст заключения; ссылка на шаблон обнуляется
    for analysis in template_usages(db, actor.org_id, template.id):
        analysis.prompt_template_id = None
    db.delete(template)
    db.commit()


def template_usages(db: Session, org_id: int, template_id: int):
    return [a for a in AnalysisRepository(db, org_id).list() if a.prompt_template_id == template_id]
