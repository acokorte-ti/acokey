"""Testes rodam em SQLite temporário, com pasta de arquivos temporária. Nada de dado real.

No CI, TESTE_DATABASE_URL aponta para um PostgreSQL descartável, para os mesmos testes rodarem no banco de produção.
"""
import os
import shutil
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="acokey_testes_"))
os.environ.update(
    APP_ENV="teste",
    DATABASE_URL=os.environ.get("TESTE_DATABASE_URL") or f"sqlite:///{(_TMP / 'teste.db').as_posix()}",
    ARQUIVOS_DIR=str(_TMP / "arquivos"),
    ADMIN_LOGIN="admin",
    ADMIN_NOME="Administrador",
    ADMIN_SENHA_INICIAL="Senha-Inicial-2026",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402, F401
from app.db import Base, SessionLocal, engine  # noqa: E402

SENHA_ADMIN_NOVA = "Nova-Senha-Gestor-77"


@pytest.fixture(autouse=True)
def banco_limpo():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    pasta = _TMP / "arquivos"
    shutil.rmtree(pasta, ignore_errors=True)
    pasta.mkdir(parents=True)
    yield


@pytest.fixture
def db():
    with SessionLocal() as sessao:
        yield sessao


@pytest.fixture
def pasta_arquivos() -> Path:
    return _TMP / "arquivos"


@pytest.fixture
def cliente():
    from app.main import app

    with TestClient(app) as c:  # o "with" roda a subida da API, que cria o administrador inicial
        yield c


def entrar(cliente: TestClient, login: str, senha: str) -> str:
    """Faz login e devolve o token CSRF (o cookie de sessão fica no cliente)."""
    r = cliente.post("/api/auth/login", json={"login": login, "senha": senha})
    assert r.status_code == 200, r.text
    return r.json()["csrf"]


def admin_pronto(cliente: TestClient) -> str:
    """Administrador inicial já com a senha trocada. Devolve o CSRF."""
    csrf = entrar(cliente, "admin", "Senha-Inicial-2026")
    r = cliente.post(
        "/api/auth/trocar-senha",
        json={"senha_atual": "Senha-Inicial-2026", "senha_nova": SENHA_ADMIN_NOVA},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200, r.text
    return csrf
