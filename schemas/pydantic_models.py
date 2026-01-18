from typing import Literal

from pydantic import BaseModel, Field, model_validator


class LoginModel(BaseModel):
    phone_number: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class CreateUserModel(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    phone_number: str = Field(..., min_length=8, max_length=20)
    password: str = Field(..., min_length=6)
    role: Literal["admin", "user"] = "user"

class UpdateUserRoleModel(BaseModel):
    role: Literal["admin", "user"]

class ChangePasswordModel(BaseModel):
    new_password: str = Field(..., min_length=6)
    confirm_new_password: str = Field(..., min_length=6)

    @model_validator(mode='after')
    def validate_new_password(self):
        if self.new_password != self.confirm_new_password:
            raise ValueError("New password and confirm new password must match")
        return self
