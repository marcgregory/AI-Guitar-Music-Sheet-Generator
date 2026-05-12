# Database initialization
# Now that SQLAlchemy/Python 3.13 compatibility issues are resolved,
# actual database initialization is implemented

import logging
from .db import Base, engine
# Import models to ensure they are registered with the Base
from . import models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    """Initialize the database by creating all tables."""
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully")

if __name__ == "__main__":
    init_db()