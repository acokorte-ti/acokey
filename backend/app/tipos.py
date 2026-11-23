"""Tipos de coluna que funcionam igual no PostgreSQL (produção) e no SQLite (desenvolvimento e testes)."""
from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator

# JSONB no PostgreSQL; JSON comum no SQLite
Json = JSON().with_variant(JSONB(), "postgresql")
# Chave BIGINT no PostgreSQL; no SQLite só INTEGER é numerado automaticamente
IdGrande = BigInteger().with_variant(Integer(), "sqlite")


class DataHoraFuso(TypeDecorator):
    """Data e hora de SISTEMA (sessões, auditoria), sempre com fuso.

    O SQLite não guarda o fuso: na leitura ele é recolocado (UTC), para que as comparações com
    datetime.now(UTC) funcionem igual nos dois bancos.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, valor: datetime | None, dialect):
        if valor is not None and valor.tzinfo is not None and dialect.name == "sqlite":
            return valor.astimezone(UTC).replace(tzinfo=None)
        return valor

    def process_result_value(self, valor: datetime | None, dialect):
        if valor is not None and valor.tzinfo is None:
            return valor.replace(tzinfo=UTC)
        return valor
