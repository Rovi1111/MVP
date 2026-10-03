from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from app.deps import get_current_user
from app.models import User

router = APIRouter()


@router.get("/")
def home(user: User = Depends(get_current_user)):
    """Отдельной главной страницы нет: после входа открывается анализ."""
    return RedirectResponse("/web/dashboard", status_code=303)
