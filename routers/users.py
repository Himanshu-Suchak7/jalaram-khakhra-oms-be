from fastapi import APIRouter, HTTPException
from fastapi.params import Depends
from sqlalchemy.orm import Session
from sqlalchemy.sql.functions import user
from starlette import status

from core.logger import get_logger
from database.database import get_db
from database.database_models import Users, UserRole
from dependencies.auth import get_current_user
from dependencies.roles import admin_required
from schemas.pydantic_models import CreateUserModel, UpdateUserRoleModel, ChangePasswordModel
from utils.security import hash_password

logger = get_logger(__name__)
router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/")
def get_users(
        db: Session = Depends(get_db),
        current_user=Depends(admin_required)
):
    logger.info(f"Fetching users list | requested_by={current_user['sub']}")

    users = db.query(Users).all()

    response = [
        {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "phone_number": user.phone_number,
            "role": user.role.value,
            "is_active": user.is_active,
        }
        for user in users
    ]
    logger.info(f"Users list fetched successfully | count={len(response)}")

    return {
        "users": response,
        "total": len(response),
    }


@router.post("/")
def create_user(data: CreateUserModel, db: Session = Depends(get_db), current_user=Depends(admin_required)):
    logger.info("Creating new user | requested_by={current_user['sub']}")

    existing_user = db.query(Users).filter(Users.phone_number == data.phone_number).first()
    if existing_user:
        logger.warning(f"Create user failed | reason=phone_exists | phone={data.phone_number}")
        raise HTTPException(status_code=400, detail="User with this phone number already exists")

    new_user = Users(
        name=data.name,
        phone_number=data.phone_number,
        role=UserRole(data.role),
        is_active=True,
        password=hash_password(data.password),
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    logger.info(f"User created successfully | user_id={new_user.id} | role={new_user.role.value}")

    return {
        "message": "User created successfully",
        "user": {
            "id": str(new_user.id),
            "name": new_user.name,
            "phone_number": new_user.phone_number,
            "role": new_user.role.value,
            "is_active": new_user.is_active,
        }
    }


@router.patch('/{user_id}', status_code=status.HTTP_200_OK)
def update_user_role(user_id: str, data: UpdateUserRoleModel, db: Session = Depends(get_db),
                     current_user=Depends(admin_required)):
    user = db.query(Users).filter(Users.id == user_id).first()
    if not user:
        logger.warning(f"Update user role failed | reason=user_not_found | user_id={user_id}")
        raise HTTPException(status_code=404, detail="User not found")
    old_role = user.role
    new_role = data.role

    if old_role == new_role:
        return {
            "message": "User role already set",
            "role": old_role
        }

    user.role = UserRole(new_role)
    db.commit()

    logger.info(f"User role updated | user_id={user.id} | {old_role} -> {new_role} | updated_by={current_user['sub']}")

    return {
        "message": "User role updated successfully",
        "user": {
            "id": str(user.id),
            "name": user.name,
            "role": user.role.value,
        }
    }


@router.patch('/{user_id}/change-password')
def admin_change_password(user_id: str, data: ChangePasswordModel, db: Session = Depends(get_db),
                          current_user=Depends(admin_required)):
    logger.warning(f"Admin password change initiated | target_user={user_id} | by_admin={current_user['sub']}")
    user = db.query(Users).filter(Users.id == user_id).first()
    if not user:
        logger.warning(f"Update user role failed | reason=user_not_found | user_id={user_id}")
        raise HTTPException(status_code=404, detail="User not found")
    user.password = hash_password(data.new_password)
    db.commit()
    logger.warning(f"Password reset successful | user_id={user.id} | by_admin={current_user['sub']}")

    return {
        "message": "Password updated successfully",
        "user": {
            "id": str(user.id),
            "name": user.name,
            "phone_number": user.phone_number,
            "role": user.role.value,
        }
    }


@router.delete('/{user_id}', status_code=status.HTTP_200_OK)
def delete_user(user_id: str, db: Session = Depends(get_db), current_user=Depends(admin_required)):
    logger.warning(f"Soft delete user request | target_user={user_id} | by_admin={current_user['sub']}")
    user = db.query(Users).filter(Users.id == user_id).first()
    if not user:
        logger.warning(f"Update user role failed | reason=user_not_found | user_id={user_id}")
        raise HTTPException(status_code=404, detail="User not found")

    if not user.is_active:
        return {
            "message": "User already deactivated"
        }

    if str(user.id) == current_user["sub"]:
        raise HTTPException(status_code=400, detail="Admin cannot delete themselves")

    user.is_active = False
    db.commit()
    logger.warning(f"User soft deleted | user_id={user.id} | by_admin={current_user['sub']}")

    return {
        "message": "User deleted successfully",
        "user": {
            "id": str(user.id),
            "name": user.name,
            "phone_number": user.phone_number,
            "role": user.role.value,
        }
    }


@router.get("/me", status_code=status.HTTP_200_OK)
def me(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    user_id = str(current_user["sub"])
    logger.info(f"Fetching current user info | user_id={user_id}")
    user = db.query(Users).filter(Users.id == user_id).first()

    if not user:
        # Edge case: user deleted after token issued
        logger.warning(f"Current user not found | user_id={user_id}")
        raise HTTPException(status_code=404, detail="User not found")

    if not user.is_active:
        logger.warning(f"Inactive user tried to access /me | user_id={user_id}")
        raise HTTPException(status_code=403, detail="Inactive user")

    return {
        "id": str(user.id),
        "name": user.name,
        "phone_number": user.phone_number,
        "email": user.email,
        "role": user.role.value,
        "is_active": user.is_active,
        "profile_picture": user.profile_picture,
    }
