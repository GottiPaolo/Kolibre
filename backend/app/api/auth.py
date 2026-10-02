from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from .. import models, schemas, database, auth as auth_module
from ..logging_utils import log_message

router = APIRouter(tags=["auth"])


@router.post("/token", response_model=schemas.Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not auth_module.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenziali non valide",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=auth_module.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth_module.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    log_message("info", "auth", f"Token issued for user: {user.username}")
    return {"access_token": access_token, "token_type": "bearer"}
