from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.logger import get_logger
from database.database import get_db
from database.database_models import OrderItems, Orders, OrderStatus, PaymentStatus, Products
from dependencies.roles import admin_required
from schemas.pydantic_models import (
    ProfitOrdersResponse,
    ProfitProductsResponse,
    ProfitSummaryResponse,
)
from utils.timezone import IST, ist_date_range_bounds, ist_day_bounds, ist_month_to_date_bounds, now_ist

logger = get_logger(__name__)

router = APIRouter(prefix="/profit", tags=["profit"])


@router.get("/summary", response_model=ProfitSummaryResponse)
def get_profit_summary(db: Session = Depends(get_db), current_user=Depends(admin_required)):
    """
    Profit KPIs:
    - accrued: FULFILLED orders (any payment status)
    - realized: FULFILLED + PAID orders
    Boundaries use IST business time; DB filtering uses UTC.
    """
    as_of_ist = now_ist()
    today_utc_start, today_utc_end = ist_day_bounds(as_of_ist.date())
    month_utc_start, month_utc_end = ist_month_to_date_bounds(as_of_ist)

    order_profit_subq = (
        db.query(
            OrderItems.order_id.label("order_id"),
            func.sum(OrderItems.profit).label("profit"),
        )
        .group_by(OrderItems.order_id)
        .subquery()
    )

    base = (
        db.query(
            Orders.id.label("order_id"),
            Orders.order_status.label("order_status"),
            Orders.payment_status.label("payment_status"),
            Orders.created_at.label("created_at"),
            order_profit_subq.c.profit.label("profit"),
        )
        .outerjoin(order_profit_subq, order_profit_subq.c.order_id == Orders.id)
        .filter(Orders.order_status == OrderStatus.FULFILLED)
    ).subquery()

    def _sum_profit_between(start_utc: datetime | None, end_utc: datetime | None, paid_only: bool) -> float:
        q = db.query(func.coalesce(func.sum(base.c.profit), 0))
        q = q.filter(base.c.profit.isnot(None))
        if paid_only:
            q = q.filter(base.c.payment_status == PaymentStatus.PAID)
        if start_utc is not None:
            q = q.filter(base.c.created_at >= start_utc)
        if end_utc is not None:
            q = q.filter(base.c.created_at < end_utc)
        return float(q.scalar() or 0)

    def _count_orders_between(start_utc: datetime | None, end_utc: datetime | None, paid_only: bool) -> int:
        q = db.query(func.count(base.c.order_id))
        if paid_only:
            q = q.filter(base.c.payment_status == PaymentStatus.PAID)
        if start_utc is not None:
            q = q.filter(base.c.created_at >= start_utc)
        if end_utc is not None:
            q = q.filter(base.c.created_at < end_utc)
        return int(q.scalar() or 0)

    def _count_missing_profit_orders() -> int:
        q = db.query(func.count(base.c.order_id)).filter(base.c.profit.is_(None))
        return int(q.scalar() or 0)

    accrued_total = _sum_profit_between(None, None, paid_only=False)
    accrued_today = _sum_profit_between(today_utc_start, today_utc_end, paid_only=False)
    accrued_month = _sum_profit_between(month_utc_start, month_utc_end, paid_only=False)

    realized_total = _sum_profit_between(None, None, paid_only=True)
    realized_today = _sum_profit_between(today_utc_start, today_utc_end, paid_only=True)
    realized_month = _sum_profit_between(month_utc_start, month_utc_end, paid_only=True)

    fulfilled_orders_total = _count_orders_between(None, None, paid_only=False)
    fulfilled_orders_today = _count_orders_between(today_utc_start, today_utc_end, paid_only=False)
    fulfilled_orders_month = _count_orders_between(month_utc_start, month_utc_end, paid_only=False)

    realized_orders_total = _count_orders_between(None, None, paid_only=True)
    realized_orders_today = _count_orders_between(today_utc_start, today_utc_end, paid_only=True)
    realized_orders_month = _count_orders_between(month_utc_start, month_utc_end, paid_only=True)

    return {
        "currency": "INR",
        "as_of": as_of_ist.isoformat(),
        "accrued": {
            "total_profit": round(accrued_total, 2),
            "today_profit": round(accrued_today, 2),
            "month_profit": round(accrued_month, 2),
        },
        "realized": {
            "total_profit": round(realized_total, 2),
            "today_profit": round(realized_today, 2),
            "month_profit": round(realized_month, 2),
        },
        "fulfilled_orders_total": fulfilled_orders_total,
        "fulfilled_orders_today": fulfilled_orders_today,
        "fulfilled_orders_month": fulfilled_orders_month,
        "realized_orders_total": realized_orders_total,
        "realized_orders_today": realized_orders_today,
        "realized_orders_month": realized_orders_month,
        "missing_profit_orders_total": _count_missing_profit_orders(),
    }


@router.get("/products", response_model=ProfitProductsResponse)
def get_profit_by_product(
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(admin_required),
):
    """
    Aggregates profit by product for FULFILLED orders.
    Profit is computed from stored OrderItems snapshots and excluded if profit is NULL.
    """
    start_utc, end_utc = ist_date_range_bounds(from_date, to_date)

    q = (
        db.query(
            Products.id.label("product_id"),
            Products.product_name.label("product_name"),
            func.coalesce(func.sum(OrderItems.quantity_kg), 0).label("quantity_sold_kg"),
            func.coalesce(func.sum(OrderItems.line_total), 0).label("revenue"),
            func.coalesce(func.sum(OrderItems.profit), 0).label("profit"),
        )
        .join(OrderItems, OrderItems.product_id == Products.id)
        .join(Orders, Orders.id == OrderItems.order_id)
        .filter(Orders.order_status == OrderStatus.FULFILLED)
        .filter(OrderItems.profit.isnot(None))
        .group_by(Products.id, Products.product_name)
    )

    if start_utc is not None:
        q = q.filter(Orders.created_at >= start_utc)
    if end_utc is not None:
        q = q.filter(Orders.created_at < end_utc)

    rows = q.order_by(func.sum(OrderItems.profit).desc()).all()

    items = []
    for r in rows:
        revenue = float(r.revenue or 0)
        profit = float(r.profit or 0)
        margin = (profit / revenue * 100) if revenue > 0 else None
        items.append(
            {
                "product_id": r.product_id,
                "product_name": r.product_name,
                "quantity_sold_kg": float(r.quantity_sold_kg or 0),
                "revenue": round(revenue, 2),
                "profit": round(profit, 2),
                "margin_percent": round(margin, 2) if margin is not None else None,
            }
        )

    return {
        "currency": "INR",
        "period": {
            "from": from_date.isoformat() if from_date else None,
            "to": to_date.isoformat() if to_date else None,
            "timezone": "Asia/Kolkata",
        },
        "items": items,
    }


@router.get("/orders", response_model=ProfitOrdersResponse)
def get_profit_by_order(
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(admin_required),
):
    """
    Profit per order for FULFILLED orders.
    Excludes orders whose OrderItems profit is NULL (incomplete cost snapshot).
    """
    start_utc, end_utc = ist_date_range_bounds(from_date, to_date)

    order_profit_subq = (
        db.query(
            OrderItems.order_id.label("order_id"),
            func.sum(OrderItems.line_total).label("revenue"),
            func.sum(OrderItems.profit).label("profit"),
        )
        .filter(OrderItems.profit.isnot(None))
        .group_by(OrderItems.order_id)
        .subquery()
    )

    q = (
        db.query(
            Orders.id.label("order_id"),
            Orders.order_number.label("order_number"),
            Orders.created_at.label("created_at"),
            Orders.payment_status.label("payment_status"),
            order_profit_subq.c.revenue.label("revenue"),
            order_profit_subq.c.profit.label("profit"),
        )
        .join(order_profit_subq, order_profit_subq.c.order_id == Orders.id)
        .filter(Orders.order_status == OrderStatus.FULFILLED)
    )

    if start_utc is not None:
        q = q.filter(Orders.created_at >= start_utc)
    if end_utc is not None:
        q = q.filter(Orders.created_at < end_utc)

    rows = q.order_by(Orders.created_at.desc()).all()

    orders = [
        {
            "order_id": r.order_id,
            "order_number": r.order_number,
            "order_date": r.created_at.astimezone(IST).strftime("%Y-%m-%d"),
            "payment_status": r.payment_status.name,
            "revenue": round(float(r.revenue or 0), 2),
            "profit": round(float(r.profit or 0), 2),
        }
        for r in rows
    ]

    return {
        "currency": "INR",
        "period": {
            "from": from_date.isoformat() if from_date else None,
            "to": to_date.isoformat() if to_date else None,
            "timezone": "Asia/Kolkata",
        },
        "orders": orders,
    }

