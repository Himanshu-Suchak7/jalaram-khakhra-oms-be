from fastapi import APIRouter, Query, Depends, HTTPException, status
from decimal import Decimal
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
import uuid

from core.logger import get_logger
from database.database import get_db
from database.database_models import Orders, Customers, OrderItems, BusinessSettings, Products, InventoryTransactions, InventoryActions, OrderStatus
from schemas.pydantic_models import OrdersListResponse, InvoiceResponse, CreateOrderRequest
from utils.generate_order_number import generate_order_number
from utils.generate_invoice_number import generate_invoice_number
from utils.pdf_generator import generate_invoice_pdf_content, PDF_TEMPLATE_VERSION
from utils.storage import upload_pdf_bytes, check_invoice_exists
from fastapi.responses import Response, RedirectResponse
import requests

logger = get_logger(__name__)

router = APIRouter(prefix='/orders', tags=["orders"])


@router.get('/', response_model=OrdersListResponse)
def get_orders(
    search: str = Query(None),
    status: str = Query(None),
    payment_status: str = Query(None),
    db: Session = Depends(get_db)
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
                        OrderItems.quantity_kg * OrderItems.price_per_kg
                    ),
                    0
                ).label("total_amount")
            )
            # ✅ Use OUTER JOIN so orders without items are not lost
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

        # 🔍 Search (order number OR customer name)
        if search:
            query = query.filter(
                or_(
                    Orders.order_number.ilike(f"%{search}%"),
                    Orders.customer_name.ilike(f"%{search}%")
                )
            )

        # 🔹 Status filter
        if status:
            query = query.filter(Orders.order_status == status)

        # 🔹 Payment status filter
        if payment_status:
            query = query.filter(Orders.payment_status == payment_status)

        # 🔹 Execute query
        results = query.order_by(Orders.created_at.desc()).all()

        # 🔹 Format response
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
def get_invoice(order_id: uuid.UUID, db: Session = Depends(get_db)):
    logger.info(f"Generating invoice data for order {order_id}")

    # 1. Fetch Order
    order = db.query(Orders).filter(Orders.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # 2. Fetch Business Settings (assuming single business)
    business = db.query(BusinessSettings).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business settings not found")

    # 3. Fetch Order Items
    items = db.query(OrderItems, Products.product_name).join(
        Products, Products.id == OrderItems.product_id
    ).filter(OrderItems.order_id == order_id).all()

    # 4. Calculate Summary (Tax 18%, Shipping 15%)
    subtotal = float(order.subtotal)
    tax = round(subtotal * 0.18, 2)
    shipping = round(subtotal * 0.15, 2)
    grand_total = subtotal + tax + shipping

    # 5. Format Response
    invoice_data = {
        "invoice_number": order.invoice_number or f"INV-{order.order_number}",
        "invoice_date": order.created_at.strftime("%Y-%m-%d"),
        "business": {
            "name": business.business_name,
            "address": business.business_address,
            "phone": business.business_phone_number,
            "gstin": business.gst_number,
            "upi_id": business.upi_id,
            "upi_qr_image": business.upi_qr_image
        },
        "bill_to": {
            "name": order.customer_name,
            "phone": order.customer_phone_number
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
            "subtotal": subtotal,
            "tax": tax,
            "shipping": shipping,
            "grand_total": grand_total
        },
        "notes": order.notes or "Thank You for your Business!"
    }

    return invoice_data

@router.get('/{order_id}')
def get_order(order_id: uuid.UUID, db: Session = Depends(get_db)):
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
                "line_total": float(item.OrderItems.line_total)
            }
            for item in items
        ]
    }

@router.post('/', status_code=status.HTTP_201_CREATED)
def create_order(payload: CreateOrderRequest, db: Session = Depends(get_db)):
    logger.info(f"Creating new order for customer {payload.customer_name}")

    try:
        # 1. Generate Order Number
        order_num = generate_order_number(db)

        # 2. Calculate Subtotal
        subtotal = Decimal("0.00")
        order_items_data = []

        for item in payload.items:
            product = db.query(Products).filter(Products.id == item.product_id).first()
            if not product:
                raise HTTPException(status_code=400, detail=f"Product {item.product_id} not found")
            
            line_total = item.quantity_kg * item.price_per_kg
            subtotal += line_total
            
            order_items_data.append({
                "product_id": item.product_id,
                "quantity_kg": item.quantity_kg,
                "price_per_kg": item.price_per_kg,
                "line_total": line_total
            })

        # 3. Calculate Total (Subtotal + 18% Tax + 15% Shipping)
        tax = subtotal * Decimal("0.18")
        shipping = subtotal * Decimal("0.15")
        total = subtotal + tax + shipping

        from database.database_models import PaymentStatus
        # 4. Create Order
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
        db.flush() # Get order ID

        # 5. Create Order Items
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

@router.patch('/{order_id}')
def update_order_details():
    pass

@router.delete('/{order_id}')
def delete_order():
    pass

@router.patch('/{order_id}/status')
def update_order_status(order_id: uuid.UUID, payload: dict, db: Session = Depends(get_db)):
    new_status_str = payload.get("status")
    if not new_status_str:
        raise HTTPException(status_code=400, detail="Status is required")
    
    try:
        new_status = OrderStatus[new_status_str.upper()]
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {new_status_str}")

    order = db.query(Orders).filter(Orders.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    old_status = order.order_status
    if old_status == new_status:
        return {"message": "Status is already set to this value"}

    # --- Logic for Stock Deduction on FULFILLED ---
    if new_status == OrderStatus.FULFILLED:
        # Generate Invoice Number if not already present
        if not order.invoice_number:
            order.invoice_number = generate_invoice_number(db)
        
        # Deduct stock
        order_items = db.query(OrderItems).filter(OrderItems.order_id == order_id).all()
        for item in order_items:
            transaction = InventoryTransactions(
                product_id=item.product_id,
                action=InventoryActions.DEDUCT,
                quantity_kg=item.quantity_kg,
                notes=f"Deducted for Order {order.order_number}"
            )
            db.add(transaction)
    logger.info(f"Generating invoice data for order {order_id}")

    # 1. Fetch Order
    order = db.query(Orders).filter(Orders.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # 2. Fetch Business Settings (assuming single business)
    business = db.query(BusinessSettings).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business settings not found")

    # 3. Fetch Order Items
    items = db.query(OrderItems, Products.product_name).join(
        Products, Products.id == OrderItems.product_id
    ).filter(OrderItems.order_id == order_id).all()

    # 4. Calculate Summary (Tax 18%, Shipping 15%)
    subtotal = float(order.subtotal)
    tax = round(subtotal * 0.18, 2)
    shipping = round(subtotal * 0.15, 2)
    grand_total = subtotal + tax + shipping

    # 5. Format Response
    invoice_data = {
        "invoice_number": order.invoice_number or f"INV-{order.order_number}",
        "invoice_date": order.created_at.strftime("%Y-%m-%d"),
        "business": {
            "name": business.business_name,
            "address": business.business_address,
            "phone": business.business_phone_number,
            "gstin": business.gst_number,
            "upi_id": business.upi_id,
            "upi_qr_image": business.upi_qr_image
        },
        "bill_to": {
            "name": order.customer_name,
            "phone": order.customer_phone_number
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
            "subtotal": subtotal,
            "tax": tax,
            "shipping": shipping,
            "grand_total": grand_total
        },
        "notes": order.notes or "Thank You for your Business!"
    }

    return invoice_data

@router.get('/{order_id}')
def get_order(order_id: uuid.UUID, db: Session = Depends(get_db)):
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
                "line_total": float(item.OrderItems.line_total)
            }
            for item in items
        ]
    }

@router.post('/', status_code=status.HTTP_201_CREATED)
def create_order(payload: CreateOrderRequest, db: Session = Depends(get_db)):
    logger.info(f"Creating new order for customer {payload.customer_name}")

    try:
        # 1. Generate Order Number
        order_num = generate_order_number(db)

        # 2. Calculate Subtotal
        subtotal = Decimal("0.00")
        order_items_data = []

        for item in payload.items:
            product = db.query(Products).filter(Products.id == item.product_id).first()
            if not product:
                raise HTTPException(status_code=400, detail=f"Product {item.product_id} not found")
            
            line_total = item.quantity_kg * item.price_per_kg
            subtotal += line_total
            
            order_items_data.append({
                "product_id": item.product_id,
                "quantity_kg": item.quantity_kg,
                "price_per_kg": item.price_per_kg,
                "line_total": line_total
            })

        # 3. Calculate Total (Subtotal + 18% Tax + 15% Shipping)
        tax = subtotal * Decimal("0.18")
        shipping = subtotal * Decimal("0.15")
        total = subtotal + tax + shipping

        from database.database_models import PaymentStatus
        # 4. Create Order
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
        db.flush() # Get order ID

        # 5. Create Order Items
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
def update_order(order_id: str, payload: CreateOrderRequest, db: Session = Depends(get_db)):
    logger.info(f"Updating order {order_id}")
    order = db.query(Orders).filter(Orders.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    try:
        # 1. Update basic info
        order.customer_id = payload.customer_id
        order.customer_name = payload.customer_name
        order.customer_phone_number = payload.customer_phone_number
        order.notes = payload.notes

        # 2. Delete existing items
        db.query(OrderItems).filter(OrderItems.order_id == order_id).delete()

        # 3. Recalculate and add new items
        subtotal = Decimal("0.00")
        for item in payload.items:
            product = db.query(Products).filter(Products.id == item.product_id).first()
            if not product:
                raise HTTPException(status_code=400, detail=f"Product {item.product_id} not found")
            
            line_total = item.quantity_kg * item.price_per_kg
            subtotal += line_total
            
            order_item = OrderItems(
                order_id=order.id,
                product_id=item.product_id,
                quantity_kg=item.quantity_kg,
                price_per_kg=item.price_per_kg,
                line_total=line_total
            )
            db.add(order_item)

        # 4. Update totals
        tax = subtotal * Decimal("0.18")
        shipping = subtotal * Decimal("0.15")
        order.subtotal = subtotal
        order.total = subtotal + tax + shipping

        db.commit()
        logger.info(f"Order {order.order_number} updated successfully")
        return {"message": "Order updated successfully"}

    except Exception:
        db.rollback()
        logger.error("Error updating order", exc_info=True)
        raise

@router.delete('/{order_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_order(order_id: str, db: Session = Depends(get_db)):
    logger.info(f"Deleting order {order_id}")
    order = db.query(Orders).filter(Orders.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    try:
        # Delete order items first (cascading)
        db.query(OrderItems).filter(OrderItems.order_id == order_id).delete()
        db.delete(order)
        db.commit()
        return None
    except Exception:
        db.rollback()
        logger.error("Error deleting order", exc_info=True)
        raise

@router.patch("/{order_id}/status/", response_model=dict)
def update_order_status(order_id: str, payload: dict, db: Session = Depends(get_db)):
    order = db.query(Orders).filter(Orders.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order.order_status = payload.get("status")
    db.commit()
    logger.info(f"Order {order.order_number} status updated to {order.order_status}")
    return {"message": "Status updated successfully", "status": order.order_status}

@router.patch("/{order_id}/payment-status/", response_model=dict)
def update_payment_status(order_id: str, payload: dict, db: Session = Depends(get_db)):
    order = db.query(Orders).filter(Orders.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order.payment_status = payload.get("status")
    db.commit()
    logger.info(f"Order {order.order_number} payment status updated to {order.payment_status}")
    return {"message": "Payment status updated successfully", "status": order.payment_status}

@router.get('/{order_id}/invoice.pdf')
def download_invoice(order_id: str, db: Session = Depends(get_db)):
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
