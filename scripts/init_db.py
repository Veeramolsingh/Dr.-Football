"""Create all tables defined in app.models against the configured database.

    python -m scripts.init_db            # create anything missing
    python -m scripts.init_db --reset    # DROP every table first, then recreate

--reset destroys all stored rows. That is safe here because the whole database
is reproducible from StatsBomb's open data via scripts/ingest_data.py, and it is
the simplest way to pick up a schema change on a project this size (the
alternative, Alembic migrations, is overkill while the schema is still moving).
"""

import argparse

from app import models  # noqa: F401  (imported so models register on Base.metadata)
from app.database import Base, engine


def main(reset: bool):
    if reset:
        Base.metadata.drop_all(bind=engine)
        print("Dropped all tables.")
    Base.metadata.create_all(bind=engine)
    print("Tables ready:", list(Base.metadata.tables.keys()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="drop all tables before creating them")
    args = parser.parse_args()
    main(reset=args.reset)
