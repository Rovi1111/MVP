"""Точка входа: uvicorn app.main:app."""

import logging
from pathlib import Path

import plotly
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import api_router
from app.config import DEV_SECRET_KEY, get_settings
from app.deps import CSRF_COOKIE
from app.errors import AppError
from app.security import is_valid_csrf_token, new_csrf_token
from app.web import web_router
from app.web.common import BASE_DIR, render

logger = logging.getLogger("app")

ERROR_TITLES = {403: "Доступ запрещён", 404: "Страница не найдена"}


def _is_api(request: Request) -> bool:
    return request.url.path.startswith("/api")


def _error_response(
    request: Request, status_code: int, message: str, errors: list | None = None
) -> Response:
    if _is_api(request):
        body = {"detail": message} | ({"errors": errors} if errors else {})
        return JSONResponse(body, status_code=status_code)
    if status_code == 401:
        # HTMX не следует за редиректом на полную страницу — нужен отдельный заголовок
        if request.headers.get("HX-Request"):
            return Response(status_code=200, headers={"HX-Redirect": "/web/login"})
        return RedirectResponse("/web/login", status_code=303)
    if request.headers.get("HX-Request"):
        # Ошибка действия HTMX показывается в общей области уведомлений, а не вместо контента
        response = render(
            request, "partials/alert.html", {"message": message}, status_code=status_code
        )
        response.headers["HX-Retarget"] = "#flash"
        response.headers["HX-Reswap"] = "innerHTML"
        return response
    context = {"title": ERROR_TITLES.get(status_code, "Ошибка"), "message": message}
    return render(request, "error.html", context, status_code=status_code)


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.secret_key == DEV_SECRET_KEY:
        logger.warning("SECRET_KEY не задан: используется ключ для разработки. Задайте его в .env")

    app = FastAPI(title=settings.app_name, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    app.include_router(api_router)
    app.include_router(web_router)

    @app.middleware("http")
    async def csrf_cookie(request: Request, call_next):
        """Выдаёт каждому браузеру подписанный CSRF-токен в cookie."""
        token = request.cookies.get(CSRF_COOKIE)
        is_new = not is_valid_csrf_token(token)
        if is_new:
            token = new_csrf_token()
        request.state.csrf_token = token
        response = await call_next(request)
        if is_new:
            response.set_cookie(
                CSRF_COOKIE, token, httponly=True, samesite="lax", secure=settings.cookie_secure
            )
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return _error_response(request, exc.status_code, str(exc.detail))

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        errors = getattr(exc, "errors", None)
        return _error_response(request, exc.status_code, exc.message, errors)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        if _is_api(request):
            errors = [
                {"field": ".".join(str(p) for p in e["loc"][1:]), "problem": e["msg"]}
                for e in exc.errors()
            ]
            return JSONResponse(
                {"detail": "Некорректные данные запроса", "errors": errors}, status_code=422
            )
        return _error_response(request, 422, "Некорректные данные формы")

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/web/")

    @app.get("/assets/plotly.min.js", include_in_schema=False)
    def plotly_js():
        """plotly.js из установленного пакета plotly: версия всегда совпадает с сервером."""
        path = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
        return FileResponse(
            path,
            media_type="application/javascript",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok"}

    return app


app = create_app()
