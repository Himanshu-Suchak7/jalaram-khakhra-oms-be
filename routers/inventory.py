from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.logger import get_logger
from database.database import get_db
from database.database_models import InventoryTransactions, InventoryActions, OrderItems, Orders, Products, OrderStatus

from sqlalchemy import func, case

logger = get_logger(__name__)

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/summary")
def get_inventory_summary(db: Session = Depends(get_db)):
    logger.info("Fetching inventory summary")

    try:
        stock_subq = (
            db.query(
                InventoryTransactions.product_id,
                func.sum(
                    case(
                        (InventoryTransactions.action == InventoryActions.ADD, InventoryTransactions.quantity_kg),
                        (InventoryTransactions.action == InventoryActions.DEDUCT, -InventoryTransactions.quantity_kg),
                        else_=0
                    )
                ).label("stock")
            )
            .group_by(InventoryTransactions.product_id)
            .subquery()
        )

        reserved_subq = (
            db.query(
                OrderItems.product_id,
                func.sum(OrderItems.quantity_kg).label("reserved")
            )
            .join(Orders, Orders.id == OrderItems.order_id)
            .filter(Orders.order_status == OrderStatus.PENDING)
            .group_by(OrderItems.product_id)
            .subquery()
        )

        results = (
            db.query(
                Products.id,
                Products.min_stock_kg,
                func.coalesce(stock_subq.c.stock, 0).label("stock"),
                func.coalesce(reserved_subq.c.reserved, 0).label("reserved"),
            )
            .outerjoin(stock_subq, Products.id == stock_subq.c.product_id)
            .outerjoin(reserved_subq, Products.id == reserved_subq.c.product_id)
            .all()
        )

        total_products = len(results)
        low_stock = 0
        out_of_stock = 0

        for r in results:
            available_stock = float(r.stock) - float(r.reserved)

            if available_stock == 0:
                out_of_stock += 1
            elif available_stock <= float(r.min_stock_kg):
                low_stock += 1

        logger.info(
            f"Inventory summary computed | total={total_products}, low={low_stock}, out={out_of_stock}"
        )

        return {
            "total_products": total_products,
            "low_stock_products": low_stock,
            "out_of_stock_products": out_of_stock
        }

    except Exception as e:
        logger.error("Error while fetching inventory summary", exc_info=True)
        raise

@router.get("/items")
def get_inventory_items(
    search: str = None,
    status: str = None,
    db: Session = Depends(get_db)
):
    logger.info("Fetching inventory items")

    try:
        # --- Stock (ADD - DEDUCT) ---
        stock_subq = (
            db.query(
                InventoryTransactions.product_id,
                func.sum(
                    case(
                        (InventoryTransactions.action == InventoryActions.ADD, InventoryTransactions.quantity_kg),
                        (InventoryTransactions.action == InventoryActions.DEDUCT, -InventoryTransactions.quantity_kg),
                        else_=0
                    )
                ).label("stock")
            )
            .group_by(InventoryTransactions.product_id)
            .subquery()
        )

        # --- Reserved (PENDING orders) ---
        reserved_subq = (
            db.query(
                OrderItems.product_id,
                func.sum(OrderItems.quantity_kg).label("reserved")  # ⚠️ using quantity (your DB)
            )
            .join(Orders, Orders.id == OrderItems.order_id)
            .filter(Orders.order_status == OrderStatus.PENDING)
            .group_by(OrderItems.product_id)
            .subquery()
        )

        # --- Main Query ---
        query = (
            db.query(
                Products.id,
                Products.product_name,
                Products.product_image,
                Products.min_stock_kg,
                func.coalesce(stock_subq.c.stock, 0).label("stock"),
                func.coalesce(reserved_subq.c.reserved, 0).label("reserved"),
            )
            .outerjoin(stock_subq, Products.id == stock_subq.c.product_id)
            .outerjoin(reserved_subq, Products.id == reserved_subq.c.product_id)
            .filter(Products.is_active == True)
        )

        # --- Search filter ---
        if search:
            query = query.filter(Products.product_name.ilike(f"%{search}%"))

        results = query.all()

        data = []

        for r in results:
            available_stock = float(r.stock) - float(r.reserved)

            # --- Status logic ---
            if available_stock == 0:
                stock_status = "OUT_OF_STOCK"
            elif available_stock <= float(r.min_stock_kg):
                stock_status = "LOW_STOCK"
            else:
                stock_status = "OK"

            # --- Status filter ---
            if status and stock_status != status:
                continue

            data.append({
                "product_id": str(r.id),
                "product_name": r.product_name,
                "stock_kg": round(available_stock, 2),
                "min_stock_kg": float(r.min_stock_kg),
                "status": stock_status,
                "image": r.product_image
            })

        logger.info(f"Inventory items fetched: {len(data)} records")

        return {"message": "Inventory Items","count": len(data),"data": data}

    except Exception:
        logger.error("Error while fetching inventory items", exc_info=True)
        raise