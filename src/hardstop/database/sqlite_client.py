from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .schema import create_all


def get_engine(sqlite_path: str):
    engine_url = f"sqlite:///{sqlite_path}"
    engine = create_engine(engine_url, future=True)
    create_all(engine_url)
    return engine


def get_session(sqlite_path: str) -> Session:
    """Get a SQLAlchemy session (caller must close it)."""
    engine = get_engine(sqlite_path)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


@contextmanager
def session_context(sqlite_path: str) -> Generator[Session, None, None]:
    """
    Context manager for SQLAlchemy sessions.
    
    Ensures proper commit/rollback and session cleanup.
    
    Usage:
        with session_context(sqlite_path) as session:
            # use session
            session.commit()  # or let context manager handle it
    """
    session = get_session(sqlite_path)
    try:
        yield session
        # Note: We don't auto-commit here because alert_builder and other
        # functions handle their own commits. This ensures explicit control.
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

