from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator, EmailStr
from decimal import Decimal

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

class EditUserProfileModel(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    phone_number: Optional[str] = Field(None, min_length=8, max_length=20)
    email: Optional[EmailStr] = None
    profile_picture: Optional[str] = None

class CreateCustomerModel(BaseModel):
    customer_name: str = Field(..., min_length=2, max_length=100)
    customer_phone_number: str = Field(..., min_length=8, max_length=20)

class EditCustomerModel(BaseModel):
    customer_name: Optional[str] = Field(None, min_length=2, max_length=100)
    customer_phone_number: Optional[str] = Field(None, min_length=8, max_length=20)

class CreateBusinessModel(BaseModel):
    business_name: str = Field(..., min_length=2, max_length=100)
    business_address: str = Field(..., min_length=2, max_length=512)
    business_phone_number: str = Field(..., min_length=8, max_length=20)
    upi_id: str = Field(..., min_length=8, max_length=20)
    upi_qr_image: str = Field(...)
    business_email: Optional[EmailStr] = None
    gst_number: Optional[str] = None

class UpdateBusinessModel(BaseModel):
    business_name: Optional[str] = Field(None, min_length=2, max_length=100)
    business_address: Optional[str] = Field(None, min_length=2, max_length=512)
    business_phone_number: Optional[str] = Field(None, min_length=8, max_length=20)
    business_email: Optional[EmailStr] = None
    upi_id: Optional[str] = Field(None, min_length=8, max_length=20)
    upi_qr_image: Optional[str] = Field(None)
    gst_number: Optional[str] = None

class AddProductModel(BaseModel):
    product_name: str = Field(..., min_length=2, max_length=100)
    product_price: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    product_image: str = Field(...)

class EditProductModel(BaseModel):
    product_name: Optional[str] = Field(None, min_length=2, max_length=100)
    product_price: Optional[Decimal] = Field(None, gt=0, max_digits=18, decimal_places=2)
    product_image: Optional[str] = Field(None)

