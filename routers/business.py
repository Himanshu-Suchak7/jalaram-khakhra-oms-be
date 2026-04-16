import os
import shutil
import uuid

from fastapi import APIRouter, HTTPException, File, UploadFile, Form
from fastapi.params import Depends
from sqlalchemy.orm import Session
from starlette import status

from core.logger import get_logger
from database.database import get_db
from database.database_models import BusinessSettings
from dependencies.auth import get_current_user
from dependencies.roles import admin_required
from utils.storage import upload_image_to_supabase

logger = get_logger(__name__)
router = APIRouter(prefix="/business", tags=["Business"])

# ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


@router.get("/")
def get_business(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    logger.info(f"Fetching business details | requested_by={current_user['sub']}")

    business = db.query(BusinessSettings).first()
    if not business:
        # Business not set up yet
        logger.warning("Business details not found")
        raise HTTPException(
            status_code=404,
            detail="Business details not configured"
        )

    return {
        "id": str(business.id),
        "business_name": business.business_name,
        "business_address": business.business_address,
        "business_phone_number": business.business_phone_number,
        "business_email": business.business_email,
        "gst_number": business.gst_number,
        "upi_id": business.upi_id,
        "upi_qr_image": business.upi_qr_image,
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_business(
        business_name: str = Form(...),
        business_address: str = Form(...),
        business_phone_number: str = Form(...),
        upi_id: str = Form(...),
        upi_qr_image: UploadFile = File(...),
        business_email: str | None = Form(None),
        gst_number: str | None = Form(None),
        db: Session = Depends(get_db),
        current_user=Depends(admin_required),
):
    logger.info(f"Adding business details | requested_by={current_user['sub']}")

    existing_business = db.query(BusinessSettings).first()
    if existing_business:
        logger.warning("Adding business details failed | reason=already_exists")
        raise HTTPException(status_code=400, detail="Business details already exists")

    # Validate QR Code Image
    if upi_qr_image.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid image type")

    # Saving QR Code Image to Supabase
    qr_url = upload_image_to_supabase(upi_qr_image, folder="qr-codes")

    business = BusinessSettings(
        business_name=business_name,
        business_address=business_address,
        business_phone_number=business_phone_number,
        business_email=str(business_email) if business_email else None,
        gst_number=gst_number,
        upi_id=upi_id,
        upi_qr_image=qr_url,
    )
    db.add(business)
    db.commit()
    db.refresh(business)

    logger.info(f"Business Details Added Successfully | business_id={business.id}")

    return {
        "message": "Business details added successfully",
        "business": {
            "id": str(business.id),
            "business_name": business.business_name,
            "business_address": business.business_address,
            "business_phone_number": business.business_phone_number,
            "business_email": business.business_email,
            "gst_number": business.gst_number,
            "upi_id": business.upi_id,
            "upi_qr_image": business.upi_qr_image,
        },
    }


@router.patch("/", status_code=status.HTTP_200_OK)
def update_business(
        business_name: str | None = Form(None),
        business_address: str | None = Form(None),
        business_phone_number: str | None = Form(None),
        upi_id: str | None = Form(None),
        upi_qr_image: UploadFile | None = File(None),
        business_email: str | None = Form(None),
        gst_number: str | None = Form(None),
        db: Session = Depends(get_db),
        current_user=Depends(admin_required),
):
    logger.info(f"Updating business details | requested_by={current_user['sub']}")

    business = db.query(BusinessSettings).first()

    if not business:
        logger.warning("Update business failed | reason=not_configured")
        raise HTTPException(
            status_code=404,
            detail="Business details not configured"
        )

    if business_name is not None:
        business.business_name = business_name
    if business_address is not None:
        business.business_address = business_address
    if business_phone_number is not None:
        business.business_phone_number = business_phone_number
    if business_email is not None:
        business.business_email = business_email
    if gst_number is not None:
        business.gst_number = gst_number
    if upi_id is not None:
        business.upi_id = upi_id
        # Update QR only if new file uploaded
        if upi_qr_image:
            if upi_qr_image.content_type not in ALLOWED_IMAGE_TYPES:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid QR image type",
                )

            # Save QR to Supabase
            business.upi_qr_image = upload_image_to_supabase(upi_qr_image, folder="qr-codes")

    db.commit()
    db.refresh(business)

    logger.info(f"Business updated successfully | business_id={business.id}")

    return {
        "message": "Business details updated successfully",
        "business": {
            "id": str(business.id),
            "business_name": business.business_name,
            "business_address": business.business_address,
            "business_phone_number": business.business_phone_number,
            "business_email": business.business_email,
            "gst_number": business.gst_number,
            "upi_id": business.upi_id,
            "upi_qr_image": business.upi_qr_image,
        }
    }
