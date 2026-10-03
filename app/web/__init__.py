"""Веб-страницы (/web/...): тонкий слой над теми же сервисами, что и API."""

from fastapi import APIRouter, Depends

from app.deps import csrf_protect
from app.web import admin, analyses, auth, dashboard, data, pages, reference, settings

web_router = APIRouter(prefix="/web", dependencies=[Depends(csrf_protect)], include_in_schema=False)
web_router.include_router(auth.router)
web_router.include_router(pages.router)
web_router.include_router(data.router)
web_router.include_router(reference.router)
web_router.include_router(dashboard.router)
web_router.include_router(analyses.router)
web_router.include_router(settings.router)
web_router.include_router(admin.router)
