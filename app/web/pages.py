from fastapi import APIRouter, Depends, Request

from app.deps import get_current_user
from app.models import User
from app.web.common import render

router = APIRouter()


@router.get("/")
def home(request: Request, user: User = Depends(get_current_user)):
    return render(request, "home.html", user=user)
