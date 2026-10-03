from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import SESSION_COOKIE, find_current_user, get_current_user
from app.models import User
from app.services import auth as auth_service
from app.web.common import render

router = APIRouter()


@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    # Проверяем саму сессию, а не только подпись cookie: иначе устаревшая cookie
    # (пользователь удалён, пароль сменён) зацикливает переадресацию login ↔ dashboard
    if find_current_user(request, db) is not None:
        return RedirectResponse("/web/dashboard", status_code=303)
    response = render(request, "login.html")
    if request.cookies.get(SESSION_COOKIE):
        auth_service.clear_session_cookie(response)
    return response


@router.post("/login")
def login_submit(
    request: Request,
    login: str = Form(""),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    user = auth_service.login(db, login, password)
    if user is None:
        return render(
            request,
            "login.html",
            {"error": "Неверный логин или пароль", "login": login},
            status_code=401,
        )
    response = RedirectResponse("/web/dashboard", status_code=303)
    auth_service.set_session_cookie(response, user)
    return response


@router.post("/logout")
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    auth_service.logout(db, user)
    response = RedirectResponse("/web/login", status_code=303)
    auth_service.clear_session_cookie(response)
    return response
