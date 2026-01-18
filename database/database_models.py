import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Boolean, Enum, DateTime, Text, Numeric, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class TimeStamp:
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )


class UserRole(enum.Enum):
    ADMIN = 'admin'
    USER = 'user'


class Users(TimeStamp, Base):
    """Users table"""
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=True)
    phone_number = Column(String(20), unique=True, index=True, nullable=False)
    password = Column(String(512), nullable=False)
    profile_picture = Column(String(512), nullable=True)
    role = Column(Enum(UserRole, name='user_role'), nullable=False, default=UserRole.USER)
    is_active = Column(Boolean, nullable=False, default=True)


class BusinessSettings(TimeStamp, Base):
    """Business settings table"""
    __tablename__ = "business_settings"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_name = Column(String(255), nullable=False)
    business_address = Column(Text, nullable=False)
    business_phone_number = Column(String(20), nullable=False)
    business_email = Column(String(255), nullable=True)
    gst_number = Column(String(20), nullable=True)
    upi_id = Column(String(50), nullable=False)
    upi_qr_image = Column(String(512), nullable=False)


class Products(TimeStamp, Base):
    """Products table"""
    __tablename__ = "products"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_name = Column(String(255), nullable=False, unique=True)
    price_per_kg = Column(Numeric(10, 2), nullable=False)
    product_image = Column(String(512), nullable=True)
    min_stock_kg = Column(Numeric(10, 2), nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)


class OrderStatus(enum.Enum):
    PENDING = 'pending'
    FULFILLED = 'fulfilled'
    CANCELLED = 'cancelled'


class PaymentStatus(enum.Enum):
    UNPAID = 'unpaid'
    PAID = 'paid'
    PARTIAL = 'partial'


class Orders(TimeStamp, Base):
    """Orders table"""
    __tablename__ = "orders"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_number = Column(String(50), unique=True, index=True, nullable=True)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False)
    customer_name = Column(String(255), nullable=False)
    customer_phone_number = Column(String(20), nullable=False)
    order_status = Column(Enum(OrderStatus, name="order_status"), nullable=False, default=OrderStatus.PENDING)
    payment_status = Column(Enum(PaymentStatus, name='payment_status'), nullable=False, default=PaymentStatus.UNPAID)
    subtotal = Column(Numeric(12, 2), nullable=False)
    total = Column(Numeric(12, 2), nullable=False)
    notes = Column(Text, nullable=True)


class OrderItems(TimeStamp, Base):
    """Order items table"""
    __tablename__ = "order_items"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    quantity = Column(Numeric(10, 2), nullable=False)
    price_per_kg = Column(Numeric(10, 2), nullable=False)
    line_total = Column(Numeric(12, 2), nullable=False)


class InventoryActions(enum.Enum):
    ADD = 'add'
    DEDUCT = 'deduct'
    ADJUST = 'adjust'


class InventoryTransactions(TimeStamp, Base):
    """Inventory transactions table"""
    __tablename__ = "inventory_transactions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    action = Column(Enum(InventoryActions, name='inventory_actions'), nullable=False)
    quantity_kg = Column(Numeric(10, 2), nullable=False)
    notes = Column(Text, nullable=True)


class Customers(TimeStamp, Base):
    """Customers table"""
    __tablename__ = "customers"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_name = Column(String(255), nullable=False)
    customer_phone_number = Column(String(20), nullable=False, index=True, unique=True)
    is_active = Column(Boolean, nullable=False, default=True)
