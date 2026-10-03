"""Клиент локальной Ollama."""

import httpx

from app.errors import AppError
from app.services.settings import OrgSettings


class OllamaError(AppError):
    """Ollama недоступна или вернула ошибку; сообщение готово к показу пользователю."""

    status_code = 503


class OllamaClient:
    def __init__(
        self, url: str, model: str, timeout: float, transport: httpx.BaseTransport | None = None
    ):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._transport = transport

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
                response = client.request(method, f"{self.url}{path}", **kwargs)
        except httpx.TimeoutException:
            raise OllamaError(
                f"Ollama не ответила за {self.timeout:g} с. Попробуйте ещё раз, "
                "увеличьте таймаут в настройках или выберите модель поменьше"
            ) from None
        except httpx.HTTPError:
            raise OllamaError(
                f"Ollama недоступна по адресу {self.url}. Запустите её командой «ollama serve» "
                "или проверьте адрес в настройках"
            ) from None
        if response.status_code == 404 and path == "/api/generate":
            raise OllamaError(
                f"Модель «{self.model}» не найдена в Ollama. "
                f"Загрузите её командой «ollama pull {self.model}»"
            )
        if response.status_code >= 400:
            raise OllamaError(
                f"Ollama вернула ошибку {response.status_code}: {response.text[:200]}"
            )
        return response

    def generate(self, prompt: str) -> str:
        """Возвращает текст ответа модели на промпт."""
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        response = self._request("POST", "/api/generate", json=payload)
        try:
            text = response.json().get("response", "")
        except ValueError:
            raise OllamaError("Ollama вернула ответ в неожиданном формате") from None
        if not text.strip():
            raise OllamaError("Ollama вернула пустой ответ. Попробуйте запустить анализ ещё раз")
        return text.strip()

    def list_models(self) -> list[str]:
        """Имена установленных моделей; заодно проверка доступности."""
        response = self._request("GET", "/api/tags")
        try:
            return [m["name"] for m in response.json().get("models", [])]
        except (ValueError, KeyError, TypeError):
            raise OllamaError("Ollama вернула ответ в неожиданном формате") from None


def get_client(settings: OrgSettings) -> OllamaClient:
    """Точка подмены в тестах."""
    return OllamaClient(settings.ollama_url, settings.ollama_model, settings.ollama_timeout)


def check_connection(settings: OrgSettings) -> str:
    """Проверка для страницы настроек: человекочитаемый результат."""
    models = get_client(settings).list_models()
    wanted = settings.ollama_model
    if any(name == wanted or name.split(":")[0] == wanted for name in models):
        return f"Ollama доступна, модель «{wanted}» установлена"
    available = ", ".join(models) or "нет"
    raise OllamaError(
        f"Ollama доступна, но модель «{wanted}» не установлена (есть: {available}). "
        f"Выполните «ollama pull {wanted}»"
    )
