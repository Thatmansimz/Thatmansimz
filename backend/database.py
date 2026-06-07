import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from backend.models.trade import Base
from backend.models.signal import Signal  # noqa: F401 - ensure table is registered
from backend.models.account import Account  # noqa: F401

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/trading.db")

os.makedirs("data", exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
