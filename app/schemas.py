"""Pydantic-схемы REST API."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.permissions import Role
from app.security import MIN_PASSWORD_LENGTH


class LoginIn(BaseModel):
    login: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    org_id: int
    login: str
    full_name: str
    role: Role
    is_active: bool


class LoginOut(BaseModel):
    user: UserOut
    csrf_token: str


class MeOut(UserOut):
    organization: str
    permissions: list[str]


class UserCreate(BaseModel):
    login: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH)
    role: Role
    full_name: str = ""


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=MIN_PASSWORD_LENGTH)


class NamedItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool


class NamedItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class NamedItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class AliasOut(BaseModel):
    id: int
    alias: str
    category_id: int
    category: str


class ManualRow(BaseModel):
    period: str | None = None
    category: str | None = None
    amount: float | int | str | None = None
    cost_center: str | None = None


class ManualInput(BaseModel):
    kind: str
    rows: list[ManualRow]


class MappingTarget(BaseModel):
    category_id: int | None = None
    new_name: str | None = None


class MappingIn(BaseModel):
    mapping: dict[str, MappingTarget]


class UploadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    source: str
    file_name: str
    status: str
    version: int | None
    row_count: int
    total: float
    created_at: datetime


class AnalysisCreate(BaseModel):
    kind: Literal["comparison"] = "comparison"
    period1: str
    period2: str
    cost_center_id: int | None = None
    budget_upload_id: int | None = Field(default=None, description="Версия бюджета для диаграммы")
    category: str | None = None
    change_types: list[str] | None = None
    sort: str = "delta"
    order: Literal["asc", "desc"] = "desc"
    chart_categories: list[str] | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    run_ai: bool = False
    template_id: int | None = None


class AiRun(BaseModel):
    template_id: int | None = None


class AnalysisBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    title: str
    created_at: datetime
    has_ai: bool = False


class AnalysisOut(BaseModel):
    id: int
    kind: str
    title: str
    params: dict
    result: dict
    ai_text: str | None
    ai_error: str | None = None
    prompt_template_id: int | None
    author: str
    created_at: datetime


class PromptTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    scenario: str
    text: str
    is_active: bool


class PromptTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)
    scenario: str = ""


class PromptTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    text: str | None = Field(default=None, min_length=1)
    scenario: str | None = None
    is_active: bool | None = None


class SettingsOut(BaseModel):
    ollama_url: str
    ollama_model: str
    ollama_timeout: float
    ai_auto_run: bool
    plan_fact_threshold: float
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_from: str
    smtp_tls: bool
    smtp_configured: bool


class SettingsUpdate(BaseModel):
    ollama_url: str | None = None
    ollama_model: str | None = None
    ollama_timeout: float | None = None
    ai_auto_run: bool | None = None
    plan_fact_threshold: float | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_tls: bool | None = None


class EmailReport(BaseModel):
    to: str
    formats: list[Literal["pdf", "xlsx"]] = ["pdf"]


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    user_login: str
    action: str
    entity: str
    entity_id: str | None
    details: dict | None
