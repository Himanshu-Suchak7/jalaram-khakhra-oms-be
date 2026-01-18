from getpass import getpass

from sqlalchemy.orm import Session

from database.database import SessionLocal
from database.database_models import Users, UserRole
from utils.security import hash_password


def reset_admin_password():
    session: Session = SessionLocal()

    try:
        print("🔐 Reset Admin Password")

        phone_number = input("Enter admin phone number: ").strip()

        admin = session.query(Users).filter(
            Users.phone_number == phone_number,
            Users.role == UserRole.ADMIN
        ).first()

        if not admin:
            print("❌ Admin user not found")
            return

        new_password = getpass("Enter new password: ")
        confirm_password = getpass("Confirm new password: ")

        if new_password != confirm_password:
            print("❌ Passwords do not match")
            return

        admin.password = hash_password(new_password)
        session.commit()

        print("✅ Admin password reset successfully")

    finally:
        session.close()

if __name__ == "__main__":
    reset_admin_password()