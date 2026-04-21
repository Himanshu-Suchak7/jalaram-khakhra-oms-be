from sqlalchemy.orm import Session
from datetime import datetime
from database.database_models import Orders

def generate_invoice_number(db: Session) -> str:
    """
    Generates invoice number in format: INV-YY-MM-####
    Example: INV-26-04-0005
    Resets monthly.
    """
    now = datetime.now()
    # Format according to API_REQUIREMENTS.md: INV-YY-MM-
    prefix = f"INV-{now.strftime('%y-%m')}-"
    
    # Find the latest invoice number with this prefix
    last_order = (
        db.query(Orders.invoice_number)
        .filter(Orders.invoice_number.like(f"{prefix}%"))
        .order_by(Orders.invoice_number.desc())
        .first()
    )
    
    if last_order and last_order[0]:
        try:
            last_num = int(last_order[0].split('-')[-1])
            new_num = last_num + 1
        except ValueError:
            new_num = 1
    else:
        new_num = 1
        
    return f"{prefix}{new_num:04d}"
