from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from settings import settings

db_url = settings.DATABASE_URL
engine = create_engine(db_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
