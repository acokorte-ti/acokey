"""Socorro do administrador pela linha de comando, para quando ninguém consegue entrar pela tela.

No servidor, dentro da pasta do sistema:

    docker compose exec api python -m app.admin desbloquear LOGIN        # tira o bloqueio por tentativas erradas
    docker compose exec api python -m app.admin senha-provisoria LOGIN   # gera uma senha provisória e a mostra uma vez

Quem roda isso já tem acesso ao servidor; mesmo assim, cada uso fica na auditoria.
"""
import argparse
import secrets
import sys

from sqlalchemy import delete, func, select

from app.db import SessionLocal
from app.models import Sessao, Usuario
from app.seguranca import auditar, hash_senha


def main() -> None:
    argumentos = argparse.ArgumentParser(description="Socorro do administrador")
    argumentos.add_argument("comando", choices=["desbloquear", "senha-provisoria"])
    argumentos.add_argument("login")
    opcoes = argumentos.parse_args()

    with SessionLocal() as db:
        usuario = db.scalar(select(Usuario).where(func.lower(Usuario.login) == opcoes.login.strip().lower()))
        if not usuario:
            sys.exit(f"Usuário {opcoes.login!r} não encontrado.")
        usuario.tentativas_falhas = 0
        usuario.bloqueado_ate = None
        if opcoes.comando == "senha-provisoria":
            senha = secrets.token_urlsafe(12)
            usuario.senha_hash = hash_senha(senha)
            usuario.trocar_senha = True
            usuario.ativo = True
            db.execute(delete(Sessao).where(Sessao.usuario_id == usuario.id))
            print(f"Senha provisória de {usuario.login}: {senha}")
            print("Ela precisa ser trocada no primeiro acesso. Não a guarde em arquivo nem a envie por mensagem.")
        else:
            print(f"Usuário {usuario.login} desbloqueado.")
        auditar(db, None, "SOCORRO_" + opcoes.comando.upper().replace("-", "_"), "usuario", usuario.id, login="(linha de comando)")
        db.commit()


if __name__ == "__main__":
    main()
