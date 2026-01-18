import uuid
from getpass import getpass
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database.database import SessionLocal
from database.database_models import Users, UserRole
from utils.security import hash_password


def create_admin():
    session: Session = SessionLocal()

    try:
        print("⚠️  Only use this script to create the FIRST admin account")

        email = input("Enter email: ").strip()
        phone_number = input("Enter phone number: ").strip()
        password = getpass("Enter password: ")

        existing_user = session.query(Users).filter(
            or_(
                Users.email == email,
                Users.phone_number == phone_number
            )
        ).first()

        if existing_user:
            print("❌ User already exists")
            return

        admin = Users(
            id=uuid.uuid4(),
            name="Himanshu Suchak",
            email=email,
            phone_number=phone_number,
            password=hash_password(password),
            role=UserRole.ADMIN,
            is_active=True
        )

        session.add(admin)
        session.commit()

        print("✅ Admin user created successfully")

    finally:
        session.close()

if __name__ == "__main__":
    create_admin()
