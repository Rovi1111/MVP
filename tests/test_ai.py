"""AI-анализ: агрегаты, шаблоны, клиент Ollama (без реальной Ollama), сохранение анализов."""

import json

import httpx
import pytest

from app.services import ai_summary, ollama
from app.services.settings import OrgSettings
from tests.helpers import load

FACT = [(f"{day:02}.01.2025", f"Статья {i}", 100 + i, "Офис") for i, day in enumerate(range(1, 9))]
FACT += [
    (f"{day:02}.02.2025", f"Статья {i}", 200 + 10 * i, "Офис") for i, day in enumerate(range(1, 9))
]
FACT += [("15.01.2025", "Ушедшая", 55, "Склад"), ("15.02.2025", "Свежая", 77.7, "Склад")]
BUDGET = [("2025-02", "Статья 0", 100), ("2025-02", "Статья 1", 500)]
COMPARISON = {"kind": "comparison", "period1": "2025-01", "period2": "2025-02"}


class FakeOllama:
    """Подмена Ollama: запоминает запросы и отвечает как настоящий сервер."""

    def __init__(self, handler=None):
        self.requests: list[httpx.Request] = []
        self.handler = handler or (
            lambda request: httpx.Response(200, json={"response": " Заключение. "})
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    def install(self, monkeypatch):
        def factory(settings):
            return ollama.OllamaClient(
                settings.ollama_url, settings.ollama_model, settings.ollama_timeout,
                transport=httpx.MockTransport(self),
            )  # fmt: skip

        monkeypatch.setattr(ollama, "get_client", factory)
        return self

    @property
    def prompt(self) -> str:
        return json.loads(self.requests[-1].content)["prompt"]


@pytest.fixture
def client(client_for):
    client = client_for("a_admin")
    load(client, "fact", FACT)
    load(client, "budget", BUDGET)
    return client


@pytest.fixture
def fake(monkeypatch):
    return FakeOllama().install(monkeypatch)


# ---------- шаблоны и агрегаты ----------


def test_default_templates_are_valid():
    assert len(ai_summary.DEFAULT_TEMPLATES) >= 2
    for template in ai_summary.DEFAULT_TEMPLATES:
        assert ai_summary.template_problems(template["text"]) == []


def test_template_problems():
    assert (
        "Неизвестные плейсхолдеры: {secret}" in ai_summary.template_problems("{data} {secret}")[0]
    )
    assert "хотя бы один" in ai_summary.template_problems("Привет, {organization}")[0]
    assert "Непарная" in ai_summary.template_problems("{data} и {")[0]
    assert ai_summary.template_problems("JSON {{ }} {totals}") == []


def test_prompt_contains_only_aggregates(client, fake):
    created = client.post("/api/analyses", json=COMPARISON | {"run_ai": True}).json()
    assert created["ai_text"] == "Заключение." and created["ai_error"] is None
    prompt = fake.prompt
    body = json.loads(fake.requests[-1].content)
    assert body["model"] == "llama3.1" and body["stream"] is False
    assert fake.requests[-1].url == "http://localhost:11434/api/generate"

    assert "Организация А" in prompt and "январь 2025" in prompt and "февраль 2025" in prompt
    assert "Свежая: 77,70" in prompt and "Ушедшая: было 55,00" in prompt
    assert "перерасход" in prompt  # отклонение от бюджета за второй период
    # Топ ограничен: из 8 выросших статей в промпт попадают 5 крупнейших
    changes = prompt.split("План-факт:")[0]
    assert sum(f"Статья {i}:" in changes for i in range(8)) == ai_summary.TOP_N
    assert "Статья 7: 107,00 → 270,00" in prompt and "Статья 0: 100,00" not in changes
    # Сырых строк нет: ни дат операций, ни ЦФО отдельных записей
    assert "15.02.2025" not in prompt and "01.01.2025" not in prompt and "Склад" not in prompt


def test_only_comparison_kind_is_supported(client, fake):
    removed = client.post(
        "/api/analyses", json={"kind": "plan_fact", "period1": "2025-01", "period2": "2025-02"}
    )
    assert removed.status_code == 422 and not fake.requests


def test_choose_template_and_rerun(client, fake):
    templates = client.get("/api/prompt-templates").json()
    assert [t["scenario"] for t in templates] == ["analyst", "plain"]
    saved = client.post("/api/analyses", json=COMPARISON).json()
    assert saved["ai_text"] is None and not fake.requests  # без run_ai Ollama не вызывается

    plain = client.post(
        f"/api/analyses/{saved['id']}/ai", json={"template_id": templates[1]["id"]}
    ).json()
    assert plain["prompt_template_id"] == templates[1]["id"] and "простыми словами" in fake.prompt
    analyst = client.post(f"/api/analyses/{saved['id']}/ai", json={}).json()
    assert (
        analyst["prompt_template_id"] == templates[0]["id"] and "финансовый аналитик" in fake.prompt
    )
    assert (
        client.post(f"/api/analyses/{saved['id']}/ai", json={"template_id": 999}).status_code == 404
    )


# ---------- ошибки Ollama ----------


def _raise(exc):
    def handler(request):
        raise exc

    return handler


@pytest.mark.parametrize(
    ("handler", "fragment"),
    [
        (
            _raise(httpx.ConnectError("refused")),
            "Ollama недоступна по адресу http://localhost:11434",
        ),
        (_raise(httpx.ReadTimeout("slow")), "не ответила за 120 с"),
        (lambda r: httpx.Response(404, json={"error": "model not found"}), "ollama pull llama3.1"),
        (lambda r: httpx.Response(500, text="boom"), "вернула ошибку 500"),
        (lambda r: httpx.Response(200, json={"response": "  "}), "пустой ответ"),
        (lambda r: httpx.Response(200, text="<html>"), "неожиданном формате"),
    ],
)
def test_ollama_failures_are_explained_and_app_keeps_working(
    client, monkeypatch, handler, fragment
):
    FakeOllama(handler).install(monkeypatch)
    created = client.post("/api/analyses", json=COMPARISON | {"run_ai": True})
    assert created.status_code == 201  # расчёт сохранён, несмотря на сбой AI
    assert fragment in created.json()["ai_error"] and created.json()["ai_text"] is None

    rerun = client.post(f"/api/analyses/{created.json()['id']}/ai", json={})
    assert rerun.status_code == 503 and fragment in rerun.json()["detail"]
    assert (
        client.get(
            "/api/analytics/comparison", params={"period1": "2025-01", "period2": "2025-02"}
        ).status_code
        == 200
    )


def test_check_connection(monkeypatch):
    settings = OrgSettings("http://x:1", "llama3.1", 5, False, 10, "", 587, "", "", "", True)
    FakeOllama(
        lambda r: httpx.Response(200, json={"models": [{"name": "llama3.1:latest"}]})
    ).install(monkeypatch)
    assert "установлена" in ollama.check_connection(settings)
    FakeOllama(lambda r: httpx.Response(200, json={"models": [{"name": "qwen:7b"}]})).install(
        monkeypatch
    )
    with pytest.raises(ollama.OllamaError) as exc:
        ollama.check_connection(settings)
    assert "ollama pull llama3.1" in exc.value.message and "qwen:7b" in exc.value.message


# ---------- настройки и шаблоны ----------


def test_settings_change_ollama_target(client, fake):
    updated = client.patch(
        "/api/settings",
        json={
            "ollama_url": "http://10.0.0.5:11434/",
            "ollama_model": "qwen2.5",
            "ollama_timeout": 30,
        },
    )
    assert updated.status_code == 200 and updated.json()["ollama_model"] == "qwen2.5"
    client.post("/api/analyses", json=COMPARISON | {"run_ai": True})
    assert str(fake.requests[-1].url) == "http://10.0.0.5:11434/api/generate"
    assert json.loads(fake.requests[-1].content)["model"] == "qwen2.5"

    assert client.patch("/api/settings", json={"ollama_url": "ftp://x"}).status_code == 422
    assert client.patch("/api/settings", json={"ollama_timeout": 0}).status_code == 422
    assert client.patch("/api/settings", json={"plan_fact_threshold": -1}).status_code == 422
    assert "smtp_password" not in client.get("/api/settings").json()


def test_threshold_setting_affects_plan_fact(client):
    def significant():
        rows = client.get("/api/analytics/plan-fact", params={"period": "2025-02"}).json()["rows"]
        return {r["category"] for r in rows if r["significant"] and r["plan"]}

    assert significant() == {"Статья 0", "Статья 1"}  # +100 % и −58 %
    client.patch("/api/settings", json={"plan_fact_threshold": 60})
    assert significant() == {"Статья 0"}


def test_prompt_template_crud(client):
    bad = client.post("/api/prompt-templates", json={"name": "Плохой", "text": "{nope}"})
    assert bad.status_code == 422 and "Неизвестные плейсхолдеры" in bad.json()["detail"]
    created = client.post(
        "/api/prompt-templates", json={"name": "Кратко", "text": "Кратко: {totals}"}
    )
    assert created.status_code == 201
    template_id = created.json()["id"]
    assert (
        client.post("/api/prompt-templates", json={"name": "Кратко", "text": "{data}"}).status_code
        == 409
    )
    patched = client.patch(
        f"/api/prompt-templates/{template_id}", json={"text": "Итог: {data}", "is_active": False}
    )
    assert patched.json()["text"] == "Итог: {data}" and patched.json()["is_active"] is False
    assert (
        client.patch(
            f"/api/prompt-templates/{template_id}", json={"text": "без данных"}
        ).status_code
        == 422
    )
    assert client.delete(f"/api/prompt-templates/{template_id}").status_code == 204
    assert len(client.get("/api/prompt-templates").json()) == 2


def test_settings_and_templates_permissions_and_isolation(client, client_for):
    employee, other = client_for("a_employee"), client_for("b_admin")
    assert employee.get("/api/settings").status_code == 403
    assert employee.patch("/api/settings", json={"ollama_model": "x"}).status_code == 403
    assert (
        employee.post("/api/prompt-templates", json={"name": "n", "text": "{data}"}).status_code
        == 403
    )
    assert employee.get("/web/settings").status_code == 403
    assert employee.get("/api/prompt-templates").status_code == 200  # выбор шаблона при запуске

    template = client.get("/api/prompt-templates").json()[0]
    assert (
        other.patch(f"/api/prompt-templates/{template['id']}", json={"name": "x"}).status_code
        == 404
    )
    client.patch("/api/settings", json={"ollama_model": "private-model"})
    assert other.get("/api/settings").json()["ollama_model"] == "llama3.1"

    saved = client.post("/api/analyses", json=COMPARISON).json()
    assert other.get(f"/api/analyses/{saved['id']}").status_code == 404
    assert other.post(f"/api/analyses/{saved['id']}/ai", json={}).status_code == 404
    assert other.get("/api/analyses").json() == []


# ---------- веб ----------

FORM = {"mode": "month", "p1_year": "2025", "p1_month": "1", "p2_year": "2025", "p2_month": "2"}


def test_web_ai_flow(client, fake):
    result = client.get("/web/dashboard/result", params=FORM)
    assert "Запустить AI-анализ" in result.text and "Простым языком" in result.text
    assert 'hx-trigger="click, load"' not in result.text  # автозапуск выключен по умолчанию

    output = client.post("/web/analyses", data=FORM | {"kind": "comparison", "action": "ai"})
    assert "Заключение." in output.text and "Скопировать" in output.text and len(fake.requests) == 1
    saved = client.post("/web/analyses", data=FORM | {"kind": "comparison", "action": "save"})
    assert "Расчёт сохранён" in saved.text and len(fake.requests) == 1

    history = client.get("/web/analyses")
    assert history.text.count("Сравнение: январь 2025 → февраль 2025") == 2
    analysis_id = client.get("/api/analyses").json()[-1]["id"]
    detail = client.get(f"/web/analyses/{analysis_id}")
    assert (
        detail.status_code == 200
        and "Заключение." in detail.text
        and "Факт и бюджет по месяцам" in detail.text
    )
    assert detail.text.count('class="chart"') == 1 and "Перерасход" not in detail.text
    assert f"/api/analyses/{analysis_id}/charts/fact_budget?format=png" in detail.text
    png = client.get(f"/api/analyses/{analysis_id}/charts/fact_budget", params={"format": "png"})
    assert png.content.startswith(b"\x89PNG")
    assert client.get(f"/api/analyses/{analysis_id}/charts/pie1").status_code == 404


def test_web_ai_error_and_auto_run(client, monkeypatch):
    FakeOllama(_raise(httpx.ConnectError("refused"))).install(monkeypatch)
    output = client.post("/web/analyses", data=FORM | {"kind": "comparison", "action": "ai"})
    assert (
        output.status_code == 200
        and "Ollama недоступна" in output.text
        and "Расчёт сохранён" in output.text
    )

    client.post(
        "/web/settings",
        data={
            "ollama_url": "http://localhost:11434",
            "ollama_model": "llama3.1",
            "ollama_timeout": "60",
            "plan_fact_threshold": "10",
            "ai_auto_run": "on",
        },
    )
    assert 'hx-trigger="click, load"' in client.get("/web/dashboard/result", params=FORM).text
    check = client.post("/web/settings/ollama-check")
    assert "Ollama недоступна" in check.text


def test_web_settings_page_and_templates(client):
    page = client.get("/web/settings")
    assert page.status_code == 200 and "Шаблоны промптов" in page.text and "{data}" in page.text
    created = client.post("/web/settings/templates", data={"name": "Мой", "text": "{data}"})
    assert "Мой" in created.text
    invalid = client.post(
        "/web/settings/templates",
        data={"name": "Мой 2", "text": "{x}"},
        headers={"HX-Request": "true"},
    )
    assert invalid.status_code == 422 and invalid.headers["HX-Retarget"] == "#flash"


def test_employee_can_run_ai_but_sees_no_settings(client, client_for, fake):
    employee = client_for("a_employee")
    created = employee.post("/api/analyses", json=COMPARISON | {"run_ai": True})
    assert created.status_code == 201 and created.json()["ai_text"] == "Заключение."
    assert "Настройки" not in employee.get("/web/dashboard").text
