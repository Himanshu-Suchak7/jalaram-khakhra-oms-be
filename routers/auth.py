from fastapi import APIRouter, Response, HTTPException, Request, status
from fastapi.params import Depends
from sqlalchemy.orm import Session

from core.logger import get_logger
from database.database import get_db
from database.database_models import Users
from schemas.pydantic_models import LoginResponse, LoginModel
from utils.jwt import create_access_token, create_refresh_token, decode_token
from utils.security import verify_password

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=LoginResponse)
def login(data: LoginModel, response: Response, db: Session = Depends(get_db)):
    logger.info(f'Login attempt started | phone={data.phone_number}')
    # Find the user in DB
    user = db.query(Users).filter(Users.phone_number == data.phone_number).first()

    # User not found in DB
    if not user:
        logger.warning(f'Login failed | reason=user_not_found | phone={data.phone_number}')
        raise HTTPException(status_code=401, detail="Invalid Credentials")

    # User is not active (deactivated or deleted user)
    if not user.is_active:
        logger.warning(f'Login failed | reason=inactive_user | user_id={user.id}')
        raise HTTPException(status_code=401, detail="Inactive user")

    # Verify user's password
    if not verify_password(data.password, user.password):
        logger.warning(f'Login failed | reason=incorrect_password | user_id={user.id}')
        raise HTTPException(status_code=401, detail="Incorrect password")

    # Create access token for User
    access_token = create_access_token({
        "sub": str(user.id),
        "role": user.role.value
    })

    # Create refresh token as well
    refresh_token = create_refresh_token({
        "sub": str(user.id),
    })

    # Setting refresh token expiry to 30 days (User will not have to login now for 30 days from frontend)
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=False,  # Make true only in production in local use false
        samesite="lax",
        max_age=60 * 60 * 40 * 30
    )

    logger.info(f"Login successful | user_id={user.id} | role={user.role.value}")

    return {
        "access_token": access_token,
    }


@router.post("/logout")
def logout(response: Response):
    logger.info('Logout attempt received')

    response.delete_cookie(
        key="refresh_token",
        httponly=True,
        samesite="lax",
        secure=False,  # set true in production use false in local
    )

    logger.info("Logout successful")
    return {
        "message": "Logout successful"
    }


@router.post("/refresh")
def refresh_access_token(request: Request, response: Response, db: Session = Depends(get_db)):
    refresh_token = request.cookies.get("refresh_token")

    if not refresh_token:
        logger.warning(f"Refresh token missing")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token missing")

    payload = decode_token(refresh_token)

    if not payload:
        logger.warning("Invalid refresh token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )

    if payload.get("type") != "refresh":
        logger.warning("Invalid token type for refresh")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type"
        )

    user_id = payload.get("sub")
    user = db.query(Users).filter(Users.id == user_id).first()

    if not user:
        logger.warning(f"Refresh failed | user_not_found | user_id={user_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    if not user.is_active:
        logger.warning(f"Refresh failed | inactive_user | user_id={user_id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    # Create new access token
    access_token = create_access_token({
        "sub": str(user.id),
        "role": user.role.value
    })

    logger.info(f"Access token refreshed | user_id={user.id}")

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }
