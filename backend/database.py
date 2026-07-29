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


def _migrate_sqlite():
    """
    Additive column migrations. create_all() only creates missing TABLES —
    it never adds columns to existing ones, so model changes silently no-op
    against a live database without this.
    """
    from sqlalchemy import text
    wanted = {
        "trades": [
            ("initial_stop_loss", "FLOAT"),   # immutable structural stop at entry
            ("r_multiple", "FLOAT"),          # gross P&L / initial risk
            ("session", "VARCHAR(20)"),       # ASIA / LONDON / NEW_YORK at entry
        ],
    }
    with engine.connect() as conn:
        for table, cols in wanted.items():
            try:
                existing = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
            except Exception:
                continue
            for name, ctype in cols:
                if existing and name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ctype}"))
        conn.commit()


def init_db():
    Base.metadata.create_all(bind=engine)
    if "sqlite" in DATABASE_URL:
        _migrate_sqlite()


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
