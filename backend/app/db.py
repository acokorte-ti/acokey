from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import config


def criar_engine(url: str) -> Engine:
    """PostgreSQL em produção. SQLite só no desenvolvimento local e nos testes (mesma DATABASE_URL)."""
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _ligar_chaves_estrangeiras(conexao, _registro) -> None:
            conexao.execute("PRAGMA foreign_keys=ON")  # o SQLite não confere FK por padrão

        return engine
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


engine = criar_engine(config().database_url)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    with SessionLocal() as sessao:
        yield sessao
