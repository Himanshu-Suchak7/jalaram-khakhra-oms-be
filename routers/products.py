from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, status, HTTPException, Request, UploadFile
from fastapi.params import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from core.logger import get_logger
from database.database import get_db
from database.database_models import Products
from dependencies.auth import get_current_user
from schemas.pydantic_models import AddProductModel, EditProductModel
from utils.storage import upload_image_to_supabase

logger = get_logger(__name__)

router = APIRouter(prefix="/products", tags=["products"])

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


def _extract_upload(field) -> UploadFile | None:
    if isinstance(field, UploadFile):
        return field
    if isinstance(field, StarletteUploadFile):
        return field  # pragma: no cover - type check guard
    return None


def _parse_price(value: str | None) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=422, detail="Invalid product price")


def _validate_name(name: str | None, required: bool) -> str | None:
    if name is None or name == "":
        if required:
            raise HTTPException(status_code=422, detail="Product name is required")
        return None
    if len(name) < 2 or len(name) > 100:
        raise HTTPException(status_code=422, detail="Product name must be 2-100 characters")
    return name


def _validate_price(price: Decimal | None, required: bool) -> Decimal | None:
    if price is None:
        if required:
            raise HTTPException(status_code=422, detail="Product price is required")
        return None
    if price <= 0:
        raise HTTPException(status_code=422, detail="Product price must be greater than 0")
    return price


def _upload_image_if_present(upload: UploadFile | None) -> str | None:
    if not upload:
        return None
    if upload.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Invalid image type. Allowed: png, jpg, jpeg, webp",
        )
    return upload_image_to_supabase(upload, folder="products")


@router.get('/')
def get_products(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    logger.info(f"Fetching products list | requested_by={current_user['sub']}")

    products = db.query(Products).all()

    response = [
        {
            "id": str(product.id),
            "name": product.product_name,
            "price": product.price_per_kg,
            "image": product.product_image,
            "is_active": product.is_active,
        }
        for product in products
    ]
    logger.info(f"Products list fetched successfully | count={len(response)}")

    return {
        "products": response,
        "total": len(response),
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
async def add_product(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    logger.info(f"Adding New Product | requested_by={current_user['sub']}")

    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        payload = await request.json()
        data = AddProductModel(**payload)
        product_name = data.product_name
        product_price = data.product_price
        product_image = data.product_image
    else:
        form = await request.form()
        raw_name = form.get("name") or form.get("product_name")
        raw_price = form.get("price") or form.get("product_price")
        raw_image = form.get("image") or form.get("product_image")

        upload = _extract_upload(raw_image)
        product_name = _validate_name(raw_name, required=True)
        product_price = _validate_price(_parse_price(raw_price), required=True)

        product_image = None
        if upload:
            product_image = _upload_image_if_present(upload)
        elif isinstance(raw_image, str) and raw_image.strip():
            product_image = raw_image.strip()

        if not product_image:
            raise HTTPException(status_code=422, detail="Product image is required")

    existing_product = db.query(Products).filter(Products.product_name.ilike(product_name)).first()

    if existing_product:
        logger.warning(f"Product already exists | name={product_name}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Product with this name already exists')

    product = Products(
        product_name=product_name,
        price_per_kg=product_price,
        product_image=product_image
    )

    try:
        db.add(product)
        db.commit()
        db.refresh(product)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Database Error while adding product')

    logger.info(f'Product created successfully | id={product.id}')

    return {
        "message": "Product created successfully",
        "product": {
            "id": str(product.id),
            "product_name": product.product_name,
            "product_price": product.price_per_kg,
            "product_image": product.product_image,
            "is_active": product.is_active,
        }
    }

@router.patch("/{product_id}", status_code=status.HTTP_200_OK)
async def edit_product(product_id: str, request: Request, db: Session = Depends(get_db),
                       current_user=Depends(get_current_user)):
    logger.info(f"Product update initiated | product_id={product_id} | by_user={current_user['sub']}")

    product = db.query(Products).filter(Products.id == product_id).first()

    if not product:
        logger.warning(f"Product not found | product_id={product_id}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    if not product.is_active:
        logger.warning(f"Product is not active | product_id={product_id}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive product")

    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        payload = await request.json()
        data = EditProductModel(**payload)
        product_name = data.product_name
        product_price = data.product_price
        product_image = data.product_image
    else:
        form = await request.form()
        raw_name = form.get("name") or form.get("product_name")
        raw_price = form.get("price") or form.get("product_price")
        raw_image = form.get("image") or form.get("product_image")

        upload = _extract_upload(raw_image)
        product_name = _validate_name(raw_name, required=False)
        product_price = _validate_price(_parse_price(raw_price), required=False)

        product_image = None
        if upload:
            product_image = _upload_image_if_present(upload)
        elif isinstance(raw_image, str) and raw_image.strip():
            product_image = raw_image.strip()

    if product_name is not None:
        existing = db.query(Products).filter(
            Products.product_name.ilike(product_name),
            Products.id != product.id
        ).first()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Product with this name already exists"
            )

        product.product_name = product_name

    if product_price is not None:
        product.price_per_kg = product_price

    if product_image is not None:
        product.product_image = product_image

    try:
        db.commit()
        db.refresh(product)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database error while updating product"
        )

    logger.info(f"Customer updated successfully | product_id={product.id}")
    return {
        "message": "Product updated successfully",
        "product": {
            "id": str(product.id),
            "product_name": product.product_name,
            "product_price": product.price_per_kg,
        }
    }

@router.delete("/{product_id}", status_code=status.HTTP_200_OK)
def delete_product(product_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    logger.warning(f"Soft delete product request | target_product={product_id}")
    product = db.query(Products).filter(Products.id == product_id).first()
    if not product:
        logger.warning(f"Delete product failed | reason=product_not_found | product_id={product_id}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    if not product.is_active:
        return {
            "message": "Product already deactivated/deleted",
        }
    product.is_active = False
    try:
        db.commit()
        db.refresh(product)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database error while deleting product"
        )
    logger.info(f"Product soft deleted | product_id={product.id} | by_user={current_user['sub']}")

    return {
        "message": "Product deleted/deactivated successfully",
        "product": {
            "id": str(product.id),
            "product_name": product.product_name,
        }
    }

@router.post('/{product_id}/min-stock', status_code=status.HTTP_200_OK)
def update_min_stock(product_id: str, payload: dict, db: Session = Depends(get_db)):
    try:
        logger.info(f"Product minimum stock update initiated | product_id={product_id}")
        min_stock = payload.get("min_stock_kg")

        if min_stock is None:
            logger.warning(f"Min stock missing | product_id={product_id}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Minimum stock is required')

        if float(min_stock) < 0:
            logger.warning(f"Invalid min stock (negative) | product_id={product_id} | value={min_stock}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Minimum stock cannot be negative')

        product = db.query(Products).filter(Products.id == product_id).first()

        if not product:
            logger.warning(f"Product not found | product_id={product_id}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

        old_value = product.min_stock_kg
        product.min_stock_kg = min_stock

        db.commit()
        db.refresh(product)

        logger.info(
            f"Min stock updated successfully | product_id={product_id} | old={old_value} | new={min_stock}"
        )

        return {
            "message": "Product minimum stock updated successfully",
            "product_id": str(product.id),
            "min_stock_kg": float(product.min_stock_kg),
        }
    except HTTPException:
        # 🔥 Important: re-raise without logging again
        raise

    except Exception as e:
        logger.error(
            f"Error updating min stock | product_id={product_id}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Failed to update minimum stock'
        )