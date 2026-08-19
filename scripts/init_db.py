"""Create all tables defined in app.models against the configured database.
Run after `docker compose up -d`:  python scripts/init_db.py
"""

from app.database import Base, engine
from app import models  # noqa: F401  (imported so models register on Base.metadata)


def main():
    Base.metadata.create_all(bind=engine)
    print("Tables created:", list(Base.metadata.tables.keys()))


if __name__ == "__main__":
    main()
