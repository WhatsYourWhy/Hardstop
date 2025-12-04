from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .schema import create_all


def get_engine(sqlite_path: str):
    engine_url = f"sqlite:///{sqlite_path}"
    engine = create_engine(engine_url, future=True)
    create_all(engine_url)
    return engine


def get_session(sqlite_path: str):
    engine = get_engine(sqlite_path)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()

