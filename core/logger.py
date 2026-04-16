import logging
import os

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

def get_logger(name: str):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(LOG_FORMAT)

    # Console logging (works everywhere)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File logging ONLY locally
    if os.getenv("VERCEL") is None:
        try:
            from logging.handlers import RotatingFileHandler

            os.makedirs("logs", exist_ok=True)

            file_handler = RotatingFileHandler(
                "logs/app.log",
                maxBytes=5 * 1024 * 1024,
                backupCount=5
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            logger.warning(f"File logging disabled: {e}")

    return logger
