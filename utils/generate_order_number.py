from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from database.database_models import Orders

def generate_order_number(db: Session) -> str:
    """
    Generates order number in format: ORD-YYMM-####
    Example: ORD-2604-0001
    """
    now = datetime.now()
    prefix = f"ORD-{now.strftime('%y%m')}-"
    
    # Find the latest order number with this prefix
    last_order = (
        db.query(Orders.order_number)
        .filter(Orders.order_number.like(f"{prefix}%"))
        .order_by(Orders.order_number.desc())
        .first()
    )
    
    if last_order:
        last_num = int(last_order[0].split('-')[-1])
        new_num = last_num + 1
    else:
        new_num = 1
        
    return f"{prefix}{new_num:04d}"
