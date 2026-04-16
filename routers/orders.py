from fastapi import APIRouter

from core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix='/orders', tags=["orders"])