from functools import lru_cache
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from backend.app.config import settings, cipher


@lru_cache
def engine():
    cipher()  # initialize key BEFORE Alembic creates database
    url = settings().database_url
    db = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):

        @event.listens_for(db, "connect")
        def pragmas(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")

    return db


def session():
    return sessionmaker(engine(), expire_on_commit=False)()
