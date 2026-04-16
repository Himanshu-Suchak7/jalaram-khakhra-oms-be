from fastapi import APIRouter, HTTPException, status
from fastapi.params import Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from core.logger import get_logger
from database.database import get_db
from database.database_models import Customers
from dependencies.auth import get_current_user
from dependencies.roles import admin_required
from schemas.pydantic_models import CreateCustomerModel, EditCustomerModel

logger = get_logger(__name__)

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.get('/')
def get_customers(
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    logger.info(f"Fetching Customers list | requested_by={current_user['sub']}")

    customers = db.query(Customers).all()

    response = [
        {
            'id': str(customer.id),
            'customer_name': customer.customer_name,
            'customer_phone_number': customer.customer_phone_number,
            'is_active': customer.is_active,
        } for customer in customers
    ]
    logger.info(f"Fetched Customers list successfully | count={len(response)}")

    return {
        "customers": response,
        "total": len(response),
    }


@router.post("/")
def create_customer(data: CreateCustomerModel, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    logger.info(f"Creating new customer | requested_by={current_user['sub']}")

    existing_phone_number = db.query(Customers).filter(
        Customers.customer_phone_number == data.customer_phone_number).first()
    if existing_phone_number:
        logger.warning(f"Create customer failed | reason=phone_exists | phone={data.customer_phone_number}")
        raise HTTPException(status_code=400, detail="Customer with this phone number already exists")

    new_customer = Customers(
        customer_name=data.customer_name,
        customer_phone_number=data.customer_phone_number,
        is_active=True,
    )

    db.add(new_customer)
    db.commit()
    db.refresh(new_customer)
    logger.info(f"Customer created successfully | customer_id={new_customer.id}")

    return {
        "message": "Customer created successfully",
        "customer": {
            "id": str(new_customer.id),
            "customer_name": new_customer.customer_name,
            "customer_phone_number": new_customer.customer_phone_number,
            "is_active": new_customer.is_active,
        }
    }


@router.get('/{customer_id}', status_code=status.HTTP_200_OK)
def get_customer(customer_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    logger.info(f"Fetching customer | customer_id={customer_id}")
    customer = db.query(Customers).filter(Customers.id == customer_id).first()
    if not customer:
        # Edge case: user deleted after token issued
        logger.warning(f"Customer not found | customer_id={customer_id}")
        raise HTTPException(status_code=404, detail="Customer not found")

    if not customer.is_active:
        logger.warning(f"Tried to access inactive customer | customer_id={customer_id}")
        raise HTTPException(status_code=403, detail="Inactive customer")

    return {
        "id": str(customer.id),
        "customer_name": customer.customer_name,
        "customer_phone_number": customer.customer_phone_number,
        "is_active": customer.is_active,
    }


@router.delete("/{customer_id}", status_code=status.HTTP_200_OK)
def delete_customer(customer_id: str, db: Session = Depends(get_db), current_user=Depends(admin_required)):
    logger.warning(f"Soft delete customer request | target_customer={customer_id} | by_user={current_user['sub']}")
    customer = db.query(Customers).filter(Customers.id == customer_id).first()
    if not customer:
        logger.warning(f"Delete customer failed | reason=customer_not_found | customer_id={customer_id}")
        raise HTTPException(status_code=404, detail="Customer not found")

    if not customer.is_active:
        return {
            "message": "Customer already deactivated/deleted"
        }
    customer.is_active = False
    db.commit()
    logger.warning(f"Customer soft deleted | customer_id={customer.id} | by_user={current_user['sub']}")

    return {
        "message": "Customer deleted/deactivated successfully",
        "customer": {
            "id": str(customer.id),
            "customer_name": customer.customer_name,
            "customer_phone_number": customer.customer_phone_number,
        }
    }


@router.patch("/{customer_id}", status_code=status.HTTP_200_OK)
def edit_customer(customer_id: str, data: EditCustomerModel, db: Session = Depends(get_db),
                  current_user=Depends(admin_required)):
    user_id = current_user['sub']
    logger.info(f"Customer update initiated | customer_id={customer_id} | by_user={user_id}")

    customer = db.query(Customers).filter(Customers.id == customer_id).first()

    if not customer:
        logger.warning(f"Customer not found | customer_id={customer_id}")
        raise HTTPException(status_code=404, detail="Customer not found")

    if not customer.is_active:
        logger.warning(f"Customer is not active | customer_id={customer_id}")
        raise HTTPException(status_code=403, detail="Inactive customer")

    if data.customer_phone_number:
        existing = db.query(Customers).filter(Customers.id != customer_id,
                                              or_(
                                                  Customers.customer_phone_number == data.customer_phone_number
                                                  if data.customer_phone_number else False
                                              )).first()
        if existing:
            raise HTTPException(status_code=400, detail="Customer with this phone number already exists")

    if data.customer_phone_number is not None:
        customer.customer_phone_number = data.customer_phone_number

    if data.customer_name is not None:
        customer.customer_name = data.customer_name

    db.commit()
    db.refresh(customer)

    logger.info(f"Customer updated successfully | customer_id={customer.id}")
    return {
        "message": "Customer updated successfully",
        "customer": {
            "id": str(customer.id),
            "customer_name": customer.customer_name,
            "customer_phone_number": customer.customer_phone_number,
        }
    }
