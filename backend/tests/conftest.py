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


def _banco_e_o_de_teste() -> bool:
    """O engine só é o de teste se a configuração foi lida DEPOIS deste arquivo trocar as variáveis.

    Se algo importou o app antes (ex.: um script que chama pytest.main), o config() em cache é o do .env, e o
    drop_all abaixo apagaria o banco de desenvolvimento. Nesse caso os testes param antes de tocar no banco.
    """
    from app.config import config

    return config().app_env == "teste" and config().database_url == os.environ["DATABASE_URL"]


@pytest.fixture(autouse=True)
def banco_limpo():
    if not _banco_e_o_de_teste():
        pytest.exit("O app foi carregado antes do conftest: o banco não é o temporário de teste. Nada foi apagado.", 2)
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


# ---------------------------------------------------------------- atalhos para os testes de cada módulo

SENHA_TESTE = "Chave-Forno-2026x"


@pytest.fixture
def admin(cliente) -> str:
    """O cliente principal já entra como administrador (senha trocada). Devolve o CSRF dele."""
    return admin_pronto(cliente)


@pytest.fixture
def como(cliente, admin):
    """Fábrica de usuários logados: `outro, csrf = como(modulos=["qualidade"], pode_aprovar=True)`.

    Cria o usuário pelo administrador, entra com ele num cliente separado e troca a senha provisória.
    """
    from app.main import app

    abertos: list[TestClient] = []

    def fabrica(*, modulos=(), pode_aprovar=False, eh_admin=False, login=None, nome="Fulano de Tal"):
        login = login or f"usuario{len(abertos) + 1}"
        corpo = {"login": login, "nome": nome, "cargo": "Teste", "senha": "Provisoria-2026",
                 "modulos": list(modulos), "pode_aprovar": pode_aprovar, "admin": eh_admin}  # fmt: skip
        r = cliente.post("/api/usuarios", json=corpo, headers={"X-CSRF-Token": admin})
        assert r.status_code == 201, r.text
        outro = TestClient(app)
        abertos.append(outro)
        csrf = entrar(outro, login, "Provisoria-2026")
        r = outro.post("/api/auth/trocar-senha", json={"senha_atual": "Provisoria-2026", "senha_nova": SENHA_TESTE},
                       headers={"X-CSRF-Token": csrf})  # fmt: skip
        assert r.status_code == 200, r.text
        return outro, csrf

    yield fabrica
    for outro in abertos:
        outro.close()


def lote_exemplo(db, numero="26-4-900001", tipo="PIN", op="900001", qtd=72, **extra):
    """Lote fictício gravado direto no banco (com commit)."""
    from datetime import datetime

    from app.models import Lote

    lote = Lote(numero=numero, op=op, tipo=tipo, qtd=qtd, etapa_desde=datetime(2026, 11, 20, 8, 0),
                criado_em=datetime(2026, 11, 20, 8, 0), **extra)  # fmt: skip
    db.add(lote)
    db.commit()
    return lote
