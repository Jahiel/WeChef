"""Configuration de la base de données WeChef.

Supporte SQLite (dev) et PostgreSQL (prod) via la variable DATABASE_URL.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from models import Base

load_dotenv()

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./recipes.db")

# SQLite : on active le WAL mode et les foreign keys
_is_sqlite = DATABASE_URL.startswith("sqlite")

connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    # Pool sizing pour PostgreSQL
    pool_pre_ping=True,
    **({} if _is_sqlite else {"pool_size": 5, "max_overflow": 10}),
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")   # meilleures perf. en lecture concurrente
        cur.execute("PRAGMA foreign_keys=ON")    # enforce ON DELETE CASCADE
        cur.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Crée les tables si elles n'existent pas (dev / premier lancement)."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency FastAPI : fournit une session SQLAlchemy."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
