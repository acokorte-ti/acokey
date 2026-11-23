"""Dados mínimos criados na primeira subida: o primeiro administrador."""
import logging
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.config import config
from app.models import Sessao, Usuario
from app.seguranca import hash_senha, validar_senha_nova

log = logging.getLogger("uvicorn.error")


def semear(db: Session) -> None:
    if db.get_bind().dialect.name == "postgresql":
        # Os dois processos da API sobem juntos: a trava evita criar tudo em dobro.
        db.execute(text("SELECT pg_advisory_xact_lock(7101)"))
    db.execute(delete(Sessao).where(Sessao.expira_em <= datetime.now(UTC)))

    if not db.scalar(select(func.count(Usuario.id)).where(Usuario.admin)):
        cfg = config()
        login = cfg.admin_login.strip().lower()
        if db.scalar(select(Usuario).where(func.lower(Usuario.login) == login)):
            log.error("Nenhum administrador e o login %r já existe sem ser administrador: nada foi criado.", login)
        elif _senha_inicial_aceitavel(cfg.admin_senha_inicial, login):
            db.add(
                Usuario(
                    login=login,
                    nome=cfg.admin_nome,
                    senha_hash=hash_senha(cfg.admin_senha_inicial),
                    admin=True,
                    trocar_senha=True,
                )
            )
            log.info("Administrador inicial criado: %s (a senha deve ser trocada no primeiro acesso)", login)
        else:
            log.error(
                "Nenhum administrador cadastrado e ADMIN_SENHA_INICIAL ausente, fraca ou ainda com o valor do modelo: "
                "o administrador NÃO foi criado. Corrija o .env e reinicie a API."
            )
    db.commit()


def _senha_inicial_aceitavel(senha: str, login: str) -> bool:
    """O valor do .env.example é público: com ele, qualquer pessoa na rede tomaria a conta de administrador."""
    if not senha or "TROQUE" in senha.upper():
        return False
    try:
        validar_senha_nova(senha, login)
    except HTTPException:
        return False
    return True
