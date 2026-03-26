"""
scripts/bootstrap_db.py

Creates all database tables defined in backend/db/models.py.
Safe to run multiple times — existing tables are left untouched.

Usage:
    DATABASE_URL=postgresql://... python scripts/bootstrap_db.py
"""

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Ensure the project root is on the path when run directly
sys.path.insert(0, ".")

from backend.db.models import Base  # noqa: E402
from backend.db.session import engine  # noqa: E402


def main() -> None:
    logger.info("Creating tables on: %s", engine.url)
    Base.metadata.create_all(bind=engine)
    logger.info("Done. Tables: %s", list(Base.metadata.tables.keys()))


if __name__ == "__main__":
    main()
