from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session

from core.logger import get_logger
from database.database import get_db
from database.database_models import InventoryTransactions, InventoryActions, OrderItems, Orders, Products, OrderStatus
from dependencies.auth import get_current_user
from dependencies.roles import admin_required

from sqlalchemy import func, case

from schemas.pydantic_models import (
    InventorySummaryResponse,
    InventoryItemsListResponse,
    InventoryTransactionRequest,
    InventoryTransactionResponse
)

logger = get_logger(__name__)

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/summary", response_model=InventorySummaryResponse)
def get_inventory_summary(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
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


@router.get("/items", response_model=InventoryItemsListResponse)
def get_inventory_items(
    search: str = None,
    status: str = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    logger.info("Fetching inventory items")

    try:
        is_admin = current_user.get("role") == "admin"

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
                Products.price_per_kg,
                Products.cost_price_per_kg,
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
                "price_per_kg": float(r.price_per_kg),
                "has_cost_price": r.cost_price_per_kg is not None,
                "cost_price_per_kg": float(r.cost_price_per_kg) if (is_admin and r.cost_price_per_kg is not None) else None,
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

@router.post("/transactions", response_model=InventoryTransactionResponse, status_code=status.HTTP_201_CREATED)
def add_stock(
    payload: InventoryTransactionRequest,
    db: Session = Depends(get_db),
    current_user=Depends(admin_required),
):
    logger.info(f"Inventory transaction initiated | by_admin={current_user.get('sub')}")

    try:
        product_id = payload.product_id
        requested_qty = payload.quantity_kg
        requested_action = payload.action

        if requested_qty is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quantity is required")

        # 🔹 Check product exists
        product = db.query(Products).filter(Products.id == product_id).first()

        if not product:
            logger.warning(f"Product not found | product_id={product_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )

        # --- Current on-hand stock (ledger): ADD - DEDUCT ---
        onhand = (
            db.query(
                func.coalesce(
                    func.sum(
                        case(
                            (InventoryTransactions.action == InventoryActions.ADD, InventoryTransactions.quantity_kg),
                            (InventoryTransactions.action == InventoryActions.DEDUCT, -InventoryTransactions.quantity_kg),
                            else_=0,
                        )
                    ),
                    0,
                )
            )
            .filter(InventoryTransactions.product_id == product_id)
            .scalar()
        ) or 0

        # --- Reserved stock (PENDING orders) ---
        reserved = (
            db.query(func.coalesce(func.sum(OrderItems.quantity_kg), 0))
            .join(Orders, Orders.id == OrderItems.order_id)
            .filter(OrderItems.product_id == product_id)
            .filter(Orders.order_status == OrderStatus.PENDING)
            .scalar()
        ) or 0

        # Normalize action semantics:
        # - add: increase on-hand by requested_qty
        # - deduct: decrease on-hand by requested_qty (must not break pending reservations)
        # - adjust: set on-hand to requested_qty by translating into add/deduct delta
        if requested_action == "adjust":
            delta = requested_qty - onhand
            if delta == 0:
                return {
                    "message": "Stock already matches requested level",
                    "transaction_id": "00000000-0000-0000-0000-000000000000",
                    "product_id": str(product_id),
                    "quantity_kg": 0.0,
                }
            action = InventoryActions.ADD if delta > 0 else InventoryActions.DEDUCT
            quantity = abs(delta)
            notes = payload.notes or f"Adjusted stock to {float(requested_qty)} kg"
        else:
            action = InventoryActions(requested_action)
            quantity = requested_qty
            notes = payload.notes or ("Manual stock added" if action == InventoryActions.ADD else "Manual stock deducted")

        if quantity <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quantity must be greater than 0")

        if action == InventoryActions.DEDUCT:
            # Protect against negative on-hand or breaking pending reservations (available < 0).
            if onhand - quantity < 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot deduct more than current stock",
                )
            if (onhand - quantity) - reserved < 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot deduct stock below reserved quantity for pending orders",
                )

        transaction = InventoryTransactions(
            product_id=product_id,
            action=action,
            quantity_kg=quantity,
            notes=notes,
        )

        db.add(transaction)
        db.commit()
        db.refresh(transaction)

        logger.info(f"Inventory updated | product_id={product_id} | action={action.value} | quantity={quantity}")

        return {
            "message": "Inventory updated successfully",
            "transaction_id": str(transaction.id),
            "product_id": str(product_id),
            "quantity_kg": float(quantity)
        }

    except HTTPException:
        raise

    except Exception:
        logger.error(
            f"Error updating inventory | product_id={getattr(payload, 'product_id', None)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update inventory"
        )
