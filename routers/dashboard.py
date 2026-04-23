from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from datetime import datetime, timedelta, timezone

from core.logger import get_logger
from database.database import get_db
from database.database_models import Orders, OrderStatus
from dependencies.auth import get_current_user
from dependencies.roles import admin_required
from schemas.pydantic_models import DashboardOverviewResponse, ProfitSummaryResponse
from utils.timezone import IST, now_ist
from routers import profit as profit_router

logger = get_logger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

@router.get("/overview", response_model=DashboardOverviewResponse)
def get_dashboard_overview(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    logger.info("Fetching dashboard overview")

    try:
        # 1. Order Status Counts & Distribution
        status_counts = (
            db.query(
                Orders.order_status,
                func.count(Orders.id).label("count")
            )
            .group_by(Orders.order_status)
            .all()
        )

        counts = {s.name.lower(): 0 for s in OrderStatus}
        for status, count in status_counts:
            counts[status.name.lower()] = count

        total_orders = sum(counts.values())

        # 2. Total Revenue (FULFILLED only)
        total_revenue = (
            db.query(func.sum(Orders.total))
            .filter(Orders.order_status == OrderStatus.FULFILLED)
            .scalar()
        ) or 0.0

        # 3. Revenue Overview (Last 30 Days - 4 Weeks)
        # For simplicity, we'll calculate 4 week-long buckets
        # Reporting boundaries are based on IST business time; DB comparisons use UTC.
        today_ist = now_ist()
        revenue_series = []
        
        for i in range(4, 0, -1):
            start_date_ist = today_ist - timedelta(days=i * 7)
            end_date_ist = today_ist - timedelta(days=(i - 1) * 7)
            start_date = start_date_ist.astimezone(timezone.utc)
            end_date = end_date_ist.astimezone(timezone.utc)
            
            week_revenue = (
                db.query(func.sum(Orders.total))
                .filter(Orders.order_status == OrderStatus.FULFILLED)
                .filter(Orders.created_at >= start_date)
                .filter(Orders.created_at < end_date)
                .scalar()
            ) or 0.0
            
            revenue_series.append({
                "label": f"Week {5-i}",
                "value": float(week_revenue)
            })

        # 4. Recent Orders (Latest 5)
        recent_orders_db = (
            db.query(Orders)
            .order_by(Orders.created_at.desc())
            .limit(5)
            .all()
        )

        recent_orders = [
            {
                "id": r.id,
                "order_id": r.order_number,
                "customer_name": r.customer_name,
                "date": r.created_at.astimezone(IST).strftime("%Y-%m-%d"),
                "status": r.order_status.name,
                "total": float(r.total)
            }
            for r in recent_orders_db
        ]

        logger.info("Dashboard overview data compiled successfully")

        return {
            "cards": {
                "pending_orders": counts.get("pending", 0),
                "fulfilled_orders": counts.get("fulfilled", 0),
                "cancelled_orders": counts.get("cancelled", 0),
                "total_revenue": float(total_revenue)
            },
            "order_status": {
                "pending": counts.get("pending", 0),
                "fulfilled": counts.get("fulfilled", 0),
                "cancelled": counts.get("cancelled", 0),
                "total": total_orders
            },
            "revenue_overview": {
                "days": 30,
                "series": revenue_series
            },
            "recent_orders": recent_orders
        }

    except Exception as e:
        logger.error("Error fetching dashboard overview", exc_info=True)
        raise


@router.get("/profit-summary", response_model=ProfitSummaryResponse)
def get_dashboard_profit_summary(db: Session = Depends(get_db), current_user=Depends(admin_required)):
    # Delegate to the canonical profit summary implementation.
    return profit_router.get_profit_summary(db=db, current_user=current_user)
