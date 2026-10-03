from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import csrf_protect, get_current_user
from app.models import User
from app.permissions import MATRIX, Role
from app.schemas import LoginIn, LoginOut, MeOut, UserOut
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/csrf")
def csrf_token(request: Request) -> dict[str, str]:
    """Токен для заголовка X-CSRF-Token (нужен всем изменяющим запросам)."""
    return {"csrf_token": request.state.csrf_token}


@router.post("/login", response_model=LoginOut)
def login(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    user = auth_service.login(db, data.login, data.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    auth_service.set_session_cookie(response, user)
    return LoginOut(user=UserOut.model_validate(user), csrf_token=request.state.csrf_token)


@router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(csrf_protect)]
)
def logout(
    response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    auth_service.logout(db, user)
    auth_service.clear_session_cookie(response)


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)):
    return MeOut(
        **UserOut.model_validate(user).model_dump(),
        organization=user.organization.name,
        permissions=sorted(MATRIX[Role(user.role)]),
    )
