import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Union
from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from . import config
from .. import db
from .. import models
from .. import schemas

logger = logging.getLogger(__name__)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

# JWT token handling
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, config.settings.jwt_secret_key, algorithm=config.settings.ALGORITHM)
    return encoded_jwt

def _unauthorized_detail(error: str) -> dict[str, Union[str, bool]]:
    return {
        "status": "unauthorized",
        "error": error,
        "requires_login": True,
    }


def _credentials_exception(error: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_unauthorized_detail(error),
        headers={"WWW-Authenticate": "Bearer"},
    )


def verify_token(token: str):
    logger.debug("JWT validation started: token_exists=%s", bool(token))
    try:
        unverified_claims = jwt.get_unverified_claims(token)
        exp = unverified_claims.get("exp")
        if exp:
            logger.debug("JWT unverified expiration: %s", datetime.fromtimestamp(exp, timezone.utc).isoformat())

        payload = jwt.decode(
            token,
            config.settings.jwt_secret_key,
            algorithms=[config.settings.ALGORITHM],
        )
        username: str = payload.get("sub")
        if username is None:
            logger.warning("JWT validation failed: missing subject claim")
            raise _credentials_exception("Access token is missing a subject")
        token_data = {"username": username}
        logger.debug("JWT validation succeeded for subject=%s", username)
    except ExpiredSignatureError:
        logger.info("JWT validation failed: token expired")
        raise _credentials_exception("Access token expired")
    except JWTError as exc:
        message = str(exc).lower()
        if "signature" in message:
            logger.warning("JWT validation failed: invalid signature")
            raise _credentials_exception("Access token signature is invalid")
        logger.warning("JWT validation failed: decode error=%s", exc)
        raise _credentials_exception("Access token is malformed or invalid")
    return token_data

def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db_session: Session = Depends(db.get_db)
):
    authorization = request.headers.get("Authorization")
    if not authorization:
        logger.info("JWT validation skipped: missing Authorization header")
        raise _credentials_exception("Missing Authorization header")
    if not authorization.lower().startswith("bearer "):
        logger.info("JWT validation skipped: missing Bearer prefix")
        raise _credentials_exception("Missing Bearer token prefix")
    if not token:
        logger.info("JWT validation skipped: empty Bearer token")
        raise _credentials_exception("Missing access token")

    token_data = verify_token(token)
    user = db_session.query(models.User).filter(models.User.username == token_data["username"]).first()
    if user is None:
        logger.warning("JWT validation failed: user not found subject=%s", token_data["username"])
        raise _credentials_exception("Token user no longer exists")
    return user
