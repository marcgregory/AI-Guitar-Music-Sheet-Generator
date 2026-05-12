from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta
from .... import db, core
from ....core.security import get_current_user
from .. import schemas, services

router = APIRouter()

@router.post("/register", response_model=schemas.User)
def register_user(
    user_in: schemas.UserCreate,
    db_session: Session = Depends(db.get_db)
):
    user = services.auth_service.get_user_by_email(db_session, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )
    user = services.auth_service.get_user_by_username(db_session, username=user_in.username)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this username already exists in the system.",
        )
    user = services.auth_service.create_user(db_session, user=user_in)
    return user

@router.post("/login", response_model=schemas.Token)
def login_access_token(
    db_session: Session = Depends(db.get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
):
    user = services.auth_service.authenticate_user(
        db_session, username=form_data.username, password=form_data.password
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=core.config.settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = core.security.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=schemas.User)
def read_current_user(
    current_user: schemas.User = Depends(get_current_user)
):
    return current_user