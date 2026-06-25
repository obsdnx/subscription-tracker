"""Database engine and session factory.

DATABASE_URL is read from the environment so the same codebase runs against
Postgres in production (via docker-compose / cloud) and SQLite locally with
zero extra setup.  The default falls back to a local SQLite file so `uvicorn
app.main:app` works out of the box without any environment variables.
"""

from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL: str = os.getenv(
    "DATABASE_URL", "sqlite:///./subscriptions.db"
)

# SQLite needs check_same_thread=False because FastAPI may hand a session to a
# different thread between the dependency creation and the route handler.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session and closes it on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
