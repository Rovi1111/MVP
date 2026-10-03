from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import csrf_protect, require
from app.models import User
from app.permissions import Permission
from app.repositories.users import UserRepository
from app.schemas import UserCreate, UserOut, UserUpdate
from app.services import users as users_service

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(csrf_protect)])
_manager = require(Permission.USERS_MANAGE)


@router.get("", response_model=list[UserOut])
def list_users(actor: User = Depends(_manager), db: Session = Depends(get_db)):
    return UserRepository(db, actor.org_id).list()


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, actor: User = Depends(_manager), db: Session = Depends(get_db)):
    return users_service.create_user(
        db, actor, data.login, data.password, data.role, data.full_name
    )


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int, data: UserUpdate, actor: User = Depends(_manager), db: Session = Depends(get_db)
):
    return users_service.update_user(db, actor, user_id, **data.model_dump(exclude_unset=True))
