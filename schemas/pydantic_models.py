import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator, EmailStr
from decimal import Decimal

class LoginModel(BaseModel):
    phone_number: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
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
    customer_address: Optional[str] = Field(None, max_length=512)
    customer_city: Optional[str] = Field(None, max_length=100)

class EditCustomerModel(BaseModel):
    customer_name: Optional[str] = Field(None, min_length=2, max_length=100)
    customer_phone_number: Optional[str] = Field(None, min_length=8, max_length=20)
    customer_address: Optional[str] = Field(None, max_length=512)
    customer_city: Optional[str] = Field(None, max_length=100)

class CreateBusinessModel(BaseModel):
    business_name: str = Field(..., min_length=2, max_length=100)
    business_address: str = Field(..., min_length=2, max_length=512)
    business_phone_number: str = Field(..., min_length=8, max_length=20)
    upi_id: str = Field(..., min_length=8, max_length=20)
    upi_qr_image: str = Field(...)
    business_email: Optional[EmailStr] = None
    gst_number: Optional[str] = None
    tax_rate: float = Field(default=18.0)
    shipping_rate: float = Field(default=15.0)

class UpdateBusinessModel(BaseModel):
    business_name: Optional[str] = Field(None, min_length=2, max_length=100)
    business_address: Optional[str] = Field(None, min_length=2, max_length=512)
    business_phone_number: Optional[str] = Field(None, min_length=8, max_length=20)
    business_email: Optional[EmailStr] = None
    upi_id: Optional[str] = Field(None, min_length=8, max_length=20)
    upi_qr_image: Optional[str] = Field(None)
    gst_number: Optional[str] = None
    tax_rate: Optional[float] = None
    shipping_rate: Optional[float] = None

class AddProductModel(BaseModel):
    product_name: str = Field(..., min_length=2, max_length=100)
    product_price: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    product_image: str = Field(...)

class EditProductModel(BaseModel):
    product_name: Optional[str] = Field(None, min_length=2, max_length=100)
    product_price: Optional[Decimal] = Field(None, gt=0, max_digits=18, decimal_places=2)
    product_image: Optional[str] = Field(None)

# --- Inventory Models ---

class InventorySummaryResponse(BaseModel):
    total_products: int
    low_stock_products: int
    out_of_stock_products: int

class InventoryItemResponse(BaseModel):
    product_id: uuid.UUID
    product_name: str
    price_per_kg: float
    stock_kg: float
    min_stock_kg: float
    status: str
    image: Optional[str] = None

class InventoryItemsListResponse(BaseModel):
    message: str
    count: int
    data: list[InventoryItemResponse]

class InventoryTransactionRequest(BaseModel):
    product_id: uuid.UUID
    action: Literal["add", "deduct", "adjust"] = "add"
    quantity_kg: Decimal = Field(..., gt=0)
    notes: Optional[str] = None

class InventoryTransactionResponse(BaseModel):
    message: str
    transaction_id: uuid.UUID
    product_id: uuid.UUID
    quantity_kg: float

# --- Order Models ---

class OrderResponse(BaseModel):
    id: uuid.UUID
    order_number: str
    customer_name: str
    total_amount: float
    order_status: str
    payment_status: str
    created_at: datetime

class OrdersListResponse(BaseModel):
    message: str
    count: int
    data: list[OrderResponse]

class OrderItemModel(BaseModel):
    product_id: uuid.UUID
    quantity_kg: Decimal = Field(..., gt=0)
    price_per_kg: Decimal = Field(..., gt=0)

class CreateOrderRequest(BaseModel):
    customer_id: uuid.UUID
    customer_name: str
    customer_phone_number: str
    items: list[OrderItemModel]
    notes: Optional[str] = None

# --- Dashboard Models ---

class DashboardCardModel(BaseModel):
    pending_orders: int
    fulfilled_orders: int
    cancelled_orders: int
    total_revenue: float

class OrderStatusDistribution(BaseModel):
    pending: int
    fulfilled: int
    cancelled: int
    total: int

class RevenueSeriesModel(BaseModel):
    label: str
    value: float

class RevenueOverviewModel(BaseModel):
    days: int
    series: list[RevenueSeriesModel]

class RecentOrderModel(BaseModel):
    id: uuid.UUID
    order_id: str
    customer_name: str
    date: str
    status: str
    total: float

class DashboardOverviewResponse(BaseModel):
    cards: DashboardCardModel
    order_status: OrderStatusDistribution
    revenue_overview: RevenueOverviewModel
    recent_orders: list[RecentOrderModel]

# --- Invoice Models ---

class BusinessInfoModel(BaseModel):
    name: str
    address: str
    phone: str
    gstin: Optional[str] = None
    upi_id: str
    upi_qr_image: str
    tax_rate: float
    shipping_rate: float

class BillToModel(BaseModel):
    name: str
    phone: str
    address: Optional[str] = None
    city: Optional[str] = None

class InvoiceItemModel(BaseModel):
    product_name: str
    quantity_kg: float
    price_per_kg: float
    line_total: float

class InvoiceSummaryModel(BaseModel):
    subtotal: float
    tax: float
    shipping: float
    grand_total: float
    tax_rate: float
    shipping_rate: float

class InvoiceResponse(BaseModel):
    invoice_number: str
    invoice_date: str
    business: BusinessInfoModel
    bill_to: BillToModel
    items: list[InvoiceItemModel]
    summary: InvoiceSummaryModel
    notes: Optional[str] = None

