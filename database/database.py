from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from settings import settings

db_url = settings.DATABASE_URL
if not db_url:
    raise RuntimeError("DATABASE_URL is not set")

engine = create_engine(
    db_url,
    pool_pre_ping=settings.DB_POOL_PRE_PING,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
