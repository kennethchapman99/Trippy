"""Database package — models, engine factory, session."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from trippy import config


def get_engine(url: str | None = None):  # type: ignore[no-untyped-def]
    from sqlalchemy import Engine

    target = url or config.DATABASE_URL
    engine: Engine = create_engine(target, echo=False)
    return engine


def make_session_factory(url: str | None = None) -> sessionmaker[Session]:
    engine = get_engine(url)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)
