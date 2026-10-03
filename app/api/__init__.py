"""REST API (/api/...). Вся бизнес-логика доступна здесь в виде JSON."""

from fastapi import APIRouter

from app.api import admin, analyses, analytics, auth, charts, reference, uploads, users

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(reference.router)
api_router.include_router(uploads.router)
api_router.include_router(analytics.router)
api_router.include_router(charts.router)
api_router.include_router(analyses.router)
api_router.include_router(admin.router)
