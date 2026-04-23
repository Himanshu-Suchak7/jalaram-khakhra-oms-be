from fastapi import APIRouter, Query, Depends, HTTPException, status
from decimal import Decimal
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
import uuid
from datetime import datetime, timezone

from core.logger import get_logger
from database.database import get_db
from database.database_models import Orders, Customers, OrderItems, BusinessSettings, Products, InventoryTransactions, InventoryActions, OrderStatus, PaymentStatus
from dependencies.auth import get_current_user
from schemas.pydantic_models import OrdersListResponse, InvoiceResponse, CreateOrderRequest
from utils.generate_order_number import generate_order_number
from utils.generate_invoice_number import generate_invoice_number
from utils.pdf_generator import generate_invoice_pdf_content, PDF_TEMPLATE_VERSION
from utils.storage import upload_pdf_bytes, check_invoice_exists
from utils.money import money
from utils.timezone import IST
from fastapi.responses import Response, RedirectResponse
import requests

logger = get_logger(__name__)

router = APIRouter(prefix='/orders', tags=["orders"])


def _load_products_for_items(db: Session, items: list) -> dict[str, Products]:
    product_ids = list({i.product_id for i in items})
    if not product_ids:
        return {}
    products = db.query(Products).filter(Products.id.in_(product_ids)).all()
    return {str(p.id): p for p in products}


def _validate_cost_prices(items: list, products_by_id: dict[str, Products]) -> None:
    missing = []
    for item in items:
        product = products_by_id.get(str(item.product_id))
        if not product:
            raise HTTPException(status_code=400, detail=f"Product {item.product_id} not found")
        if product.cost_price_per_kg is None:
            missing.append({"product_id": str(product.id), "product_name": product.product_name})

    if missing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "MISSING_COST_PRICE",
                "message": "Cost price is required for all items before creating/updating an order.",
                "missing_products": missing,
            },
        )


@router.get('/', response_model=OrdersListResponse)
def get_orders(
    search: str = Query(None),
    status: str = Query(None),
    payment_status: str = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    logger.info("Fetching orders list")

    try:
        query = (
            db.query(
                Orders.id,
                Orders.order_number,
                Orders.customer_name.label("customer_name"),
                Orders.order_status,
                Orders.payment_status,
                Orders.created_at,
                func.coalesce(
                    func.sum(
                        OrderItems.line_total
                    ),
                    0
                ).label("total_amount")
            )
            .outerjoin(OrderItems, OrderItems.order_id == Orders.id)
            .group_by(
                Orders.id,
                Orders.order_number,
                Orders.customer_name,
                Orders.order_status,
                Orders.payment_status,
                Orders.created_at
            )
        )

        if search:
            query = query.filter(
                or_(
                    Orders.order_number.ilike(f"%{search}%"),
                    Orders.customer_name.ilike(f"%{search}%")
                )
            )

        if status:
            query = query.filter(Orders.order_status == status)

        if payment_status:
            query = query.filter(Orders.payment_status == payment_status)

        results = query.order_by(Orders.created_at.desc()).all()

        data = [
            {
                "id": str(r.id),
                "order_number": r.order_number,
                "customer_name": r.customer_name,
                "total_amount": round(float(r.total_amount), 2),
                "order_status": r.order_status,
                "payment_status": r.payment_status,
                "created_at": r.created_at.isoformat()
            }
            for r in results
        ]

        logger.info(f"Orders fetched successfully | count={len(data)}")

        return {"message": "Orders fetched successfully", "count": len(data), "data": data}

    except Exception:
        logger.error("Error fetching orders", exc_info=True)
        raise

@router.get('/{order_id}/invoice', response_model=InvoiceResponse)
def get_invoice(order_id: uuid.UUID, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    logger.info(f"Generating invoice data for order {order_id}")

    order = db.query(Orders).filter(Orders.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    business = db.query(BusinessSettings).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business settings not found")

    items = db.query(OrderItems, Products.product_name).join(
        Products, Products.id == OrderItems.product_id
    ).filter(OrderItems.order_id == order_id).all()

    # Dynamic Tax & Shipping
    tax_rate = (Decimal(str(business.tax_rate)) / Decimal("100")) if business else Decimal("0")
    shipping_rate = (Decimal(str(business.shipping_rate)) / Decimal("100")) if business else Decimal("0")

    subtotal = Decimal(str(order.subtotal))
    tax = money(subtotal * tax_rate)
    shipping = money(subtotal * shipping_rate)
    grand_total = money(subtotal + tax + shipping)

    customer = db.query(Customers).filter(Customers.id == order.customer_id).first()

    return {
        "invoice_number": order.invoice_number or f"INV-{order.order_number}",
        "invoice_date": order.created_at.astimezone(IST).strftime("%Y-%m-%d"),
        "business": {
            "name": business.business_name,
            "address": business.business_address,
            "phone": business.business_phone_number,
            "gstin": business.gst_number,
            "upi_id": business.upi_id,
            "upi_qr_image": business.upi_qr_image,
            "tax_rate": float(business.tax_rate),
            "shipping_rate": float(business.shipping_rate)
        },
        "bill_to": {
            "name": order.customer_name,
            "phone": order.customer_phone_number,
            "address": customer.customer_address if customer else None,
            "city": customer.customer_city if customer else None
        },
        "items": [
            {
                "product_name": item.product_name,
                "quantity_kg": float(item.OrderItems.quantity_kg),
                "price_per_kg": float(item.OrderItems.price_per_kg),
                "line_total": float(item.OrderItems.line_total)
            }
            for item in items
        ],
        "summary": {
            "subtotal": float(subtotal),
            "tax": float(tax),
            "shipping": float(shipping),
            "grand_total": float(grand_total),
            "tax_rate": float(business.tax_rate),
            "shipping_rate": float(business.shipping_rate)
        },
        "notes": order.notes or "Thank You for your Business!"
    }

@router.get('/{order_id}')
def get_order(order_id: uuid.UUID, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    logger.info(f"Fetching order details for {order_id}")
    order = db.query(Orders).filter(Orders.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    items = db.query(OrderItems, Products.product_name).join(
        Products, Products.id == OrderItems.product_id
    ).filter(OrderItems.order_id == order_id).all()

    return {
        "order": order,
        "items": [
            {
                "product_id": str(item.OrderItems.product_id),
                "product_name": item.product_name,
                "quantity_kg": float(item.OrderItems.quantity_kg),
                "price_per_kg": float(item.OrderItems.price_per_kg),
                "cost_price_per_kg": float(item.OrderItems.cost_price_per_kg) if item.OrderItems.cost_price_per_kg is not None else None,
                "line_total": float(item.OrderItems.line_total),
                "profit": float(item.OrderItems.profit) if item.OrderItems.profit is not None else None,
            }
            for item in items
        ]
    }

@router.post('/', status_code=status.HTTP_201_CREATED)
def create_order(payload: CreateOrderRequest, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    logger.info(f"Creating new order for customer {payload.customer_name}")

    try:
        order_num = generate_order_number(db)
        subtotal = Decimal("0.00")
        order_items_data = []

        products_by_id = _load_products_for_items(db, payload.items)
        _validate_cost_prices(payload.items, products_by_id)

        for item in payload.items:
            product = products_by_id[str(item.product_id)]
            cost_price = Decimal(str(product.cost_price_per_kg))

            line_total = money(item.quantity_kg * item.price_per_kg)
            profit = money((item.price_per_kg - cost_price) * item.quantity_kg)
            subtotal = money(subtotal + line_total)
            
            order_items_data.append({
                "product_id": item.product_id,
                "quantity_kg": item.quantity_kg,
                "price_per_kg": item.price_per_kg,
                "cost_price_per_kg": cost_price,
                "line_total": line_total,
                "profit": profit,
            })

        # Dynamic Tax & Shipping
        business = db.query(BusinessSettings).first()
        tax_rate = (Decimal(str(business.tax_rate)) / Decimal("100")) if business else Decimal("0")
        shipping_rate = (Decimal(str(business.shipping_rate)) / Decimal("100")) if business else Decimal("0")

        tax = money(subtotal * tax_rate)
        shipping = money(subtotal * shipping_rate)
        total = money(subtotal + tax + shipping)

        new_order = Orders(
            order_number=order_num,
            customer_id=payload.customer_id,
            customer_name=payload.customer_name,
            customer_phone_number=payload.customer_phone_number,
            order_status=OrderStatus.PENDING,
            payment_status=PaymentStatus.UNPAID,
            subtotal=subtotal,
            total=total,
            notes=payload.notes
        )

        db.add(new_order)
        db.flush()

        for item_data in order_items_data:
            order_item = OrderItems(
                order_id=new_order.id,
                **item_data
            )
            db.add(order_item)

        db.commit()
        db.refresh(new_order)

        logger.info(f"Order created successfully | order_number={order_num}")
        return {"message": "Order created successfully", "order_id": str(new_order.id), "order_number": order_num}

    except Exception:
        db.rollback()
        logger.error("Error creating order", exc_info=True)
        raise

@router.patch('/{order_id}', response_model=dict)
def update_order(order_id: str, payload: CreateOrderRequest, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    logger.info(f"Updating order {order_id}")
    order = db.query(Orders).filter(Orders.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    try:
        def _items_match(existing_items: list[OrderItems], incoming_items: list) -> bool:
            existing_norm = sorted(
                [
                    (str(i.product_id), Decimal(str(i.quantity_kg)), Decimal(str(i.price_per_kg)))
                    for i in existing_items
                ],
                key=lambda x: x[0],
            )
            incoming_norm = sorted(
                [
                    (str(i.product_id), Decimal(str(i.quantity_kg)), Decimal(str(i.price_per_kg)))
                    for i in incoming_items
                ],
                key=lambda x: x[0],
            )
            return existing_norm == incoming_norm

        edit_mode = "full"
        if order.order_status == OrderStatus.CANCELLED:
            edit_mode = "none"
        elif order.order_status == OrderStatus.FULFILLED and order.payment_status == PaymentStatus.PAID:
            edit_mode = "notes_only"
        elif order.order_status == OrderStatus.FULFILLED:
            edit_mode = "limited"
        elif order.order_status == OrderStatus.PENDING and order.payment_status == PaymentStatus.PAID:
            edit_mode = "limited"

        if edit_mode == "none":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cancelled orders cannot be edited"
            )

        existing_items = db.query(OrderItems).filter(OrderItems.order_id == order.id).all()

        if edit_mode in ("limited", "notes_only"):
            if str(payload.customer_id) != str(order.customer_id):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Customer cannot be changed for this order"
                )

            if not _items_match(existing_items, payload.items):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Order items cannot be changed for this order"
                )

            if edit_mode == "notes_only":
                if payload.customer_name != order.customer_name or payload.customer_phone_number != order.customer_phone_number:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Only notes can be edited for this order"
                    )
                order.notes = payload.notes
            else:
                order.customer_name = payload.customer_name
                order.customer_phone_number = payload.customer_phone_number
                order.notes = payload.notes

            db.commit()
            logger.info(f"Order {order.order_number} updated successfully | mode={edit_mode}")
            return {"message": "Order updated successfully"}

        order.customer_id = payload.customer_id
        order.customer_name = payload.customer_name
        order.customer_phone_number = payload.customer_phone_number
        order.notes = payload.notes

        db.query(OrderItems).filter(OrderItems.order_id == order.id).delete()

        subtotal = Decimal("0.00")

        products_by_id = _load_products_for_items(db, payload.items)
        _validate_cost_prices(payload.items, products_by_id)

        for item in payload.items:
            product = products_by_id[str(item.product_id)]
            cost_price = Decimal(str(product.cost_price_per_kg))

            line_total = money(item.quantity_kg * item.price_per_kg)
            profit = money((item.price_per_kg - cost_price) * item.quantity_kg)
            subtotal = money(subtotal + line_total)
            
            order_item = OrderItems(
                order_id=order.id,
                product_id=item.product_id,
                quantity_kg=item.quantity_kg,
                price_per_kg=item.price_per_kg,
                cost_price_per_kg=cost_price,
                line_total=line_total,
                profit=profit,
            )
            db.add(order_item)

        # Dynamic Tax & Shipping
        business = db.query(BusinessSettings).first()
        tax_rate = (Decimal(str(business.tax_rate)) / Decimal("100")) if business else Decimal("0")
        shipping_rate = (Decimal(str(business.shipping_rate)) / Decimal("100")) if business else Decimal("0")

        tax = money(subtotal * tax_rate)
        shipping = money(subtotal * shipping_rate)
        order.subtotal = subtotal
        order.total = money(subtotal + tax + shipping)

        db.commit()
        logger.info(f"Order {order.order_number} updated successfully")
        return {"message": "Order updated successfully"}

    except Exception:
        db.rollback()
        logger.error("Error updating order", exc_info=True)
        raise

@router.delete('/{order_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_order(order_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    logger.info(f"Deleting order {order_id}")
    order = db.query(Orders).filter(Orders.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    try:
        db.query(OrderItems).filter(OrderItems.order_id == order_id).delete()
        db.delete(order)
        db.commit()
        return None
    except Exception:
        db.rollback()
        logger.error("Error deleting order", exc_info=True)
        raise

@router.patch("/{order_id}/status/", response_model=dict)
def update_order_status(order_id: str, payload: dict, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    order = db.query(Orders).filter(Orders.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    new_status_str = payload.get("status")
    try:
        new_status = OrderStatus[new_status_str.upper()]
    except (KeyError, AttributeError):
        raise HTTPException(status_code=400, detail=f"Invalid status: {new_status_str}")

    if order.order_status == new_status:
        return {"message": "Status is already set to this value"}

    # Lock final states (no undo flows implemented)
    if order.order_status in (OrderStatus.CANCELLED, OrderStatus.FULFILLED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Order status is locked ({order.order_status.value})"
        )

    if new_status == OrderStatus.FULFILLED:
        if not order.invoice_number:
            order.invoice_number = generate_invoice_number(db)
        
        order_items = db.query(OrderItems).filter(OrderItems.order_id == order_id).all()
        for item in order_items:
            transaction = InventoryTransactions(
                product_id=item.product_id,
                action=InventoryActions.DEDUCT,
                quantity_kg=item.quantity_kg,
                notes=f"Deducted for Order {order.order_number}"
            )
            db.add(transaction)

    order.order_status = new_status
    db.commit()
    logger.info(f"Order {order.order_number} status updated to {order.order_status}")
    return {"message": "Status updated successfully", "status": order.order_status}

@router.patch("/{order_id}/payment-status/", response_model=dict)
def update_payment_status(order_id: str, payload: dict, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    order = db.query(Orders).filter(Orders.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    new_status_str = payload.get("status")
    try:
        new_status = PaymentStatus[new_status_str.upper()]
    except (KeyError, AttributeError):
        raise HTTPException(status_code=400, detail=f"Invalid payment status: {new_status_str}")

    if order.payment_status == new_status:
        return {"message": "Payment status is already set to this value"}

    # Lock cancelled orders
    if order.order_status == OrderStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cancelled orders cannot change payment status"
        )

    # Lock PAID (no refund flows implemented)
    if order.payment_status == PaymentStatus.PAID:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payment status is locked (paid)"
        )

    order.payment_status = new_status
    db.commit()
    logger.info(f"Order {order.order_number} payment status updated to {order.payment_status}")
    return {"message": "Payment status updated successfully", "status": order.payment_status}

@router.get('/{order_id}/invoice.pdf')
def download_invoice(order_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    logger.info(f"PDF download requested for order {order_id}")

    order = db.query(Orders).filter(Orders.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if not order.invoice_number:
        order.invoice_number = generate_invoice_number(db)
        db.commit()

    download_filename = f"{order.invoice_number}.pdf"
    storage_filename = f"{order.invoice_number}.pdf"
    
    existing_url = check_invoice_exists(storage_filename)
    if existing_url:
        logger.info(f"Found existing PDF in storage: {existing_url}")
        resp = requests.get(existing_url)
        return Response(content=resp.content, media_type="application/pdf", headers={
            "Content-Disposition": f"attachment; filename={download_filename}"
        })

    invoice_data = get_invoice(order_id, db)
    pdf_bytes = generate_invoice_pdf_content(invoice_data)
    if not pdf_bytes:
        raise HTTPException(status_code=500, detail="Failed to generate PDF")

    try:
        public_url = upload_pdf_bytes(pdf_bytes, storage_filename)
        logger.info(f"New PDF generated and uploaded: {public_url}")
    except Exception as e:
        logger.error(f"Failed to upload PDF: {str(e)}")

    return Response(content=pdf_bytes, media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename={download_filename}"
    })
