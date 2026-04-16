from typing import Optional
from pathlib import Path

from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    DATABASE_URL: str = None
    DIRECT_DATABASE_URL: Optional[str] = None
    SECRET_KEY: Optional[str] = None
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    SUPABASE_URL: Optional[str] = None
    SUPABASE_KEY: Optional[str] = None
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None
    SUPABASE_BUCKET: str = "uploads"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_POOL_PRE_PING: bool = True
    CANONICAL_HOST: Optional[str] = None
    CANONICAL_PORT: Optional[int] = None
    CANONICAL_SCHEME: str = "http"

    class Config:
        env_file = BASE_DIR / ".env"
        extra = "forbid"


settings = Settings()
