"""Senhas, sessões, permissões, proteção CSRF e auditoria."""
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import config
from app.db import get_db
from app.models import MODULOS, Auditoria, Sessao, Usuario

_hasher = PasswordHasher()  # Argon2id
_HASH_FALSO = _hasher.hash("senha-que-nao-existe")  # iguala o tempo de resposta quando o login não existe
METODOS_LEITURA = {"GET", "HEAD", "OPTIONS"}
# Caracteres de controle (ex.: a "quebra de linha manual" colada do Word) derrubam o PostgreSQL (\x00)
# e a exportação para Excel. Tab, LF e CR são mantidos.
_CONTROLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def limpar_texto(valor):
    """Tira caracteres de controle de um texto digitado; outros tipos passam como estão."""
    return _CONTROLE.sub("", valor) if isinstance(valor, str) else valor


def celula_segura(valor):
    """Valor pronto para uma planilha exportada: sem caractere inválido e sem virar fórmula."""
    if isinstance(valor, str):
        valor = _CONTROLE.sub("", valor)
        if valor.startswith("="):  # o openpyxl gravaria como fórmula, que executa ao abrir o arquivo
            return "'" + valor
    return valor


def nome_cookie() -> str:
    # O prefixo __Host- obriga o navegador a aceitar o cookie só em HTTPS, sem domínio e com path "/"
    return "__Host-sessao" if config().producao else "sessao"


def hash_senha(senha: str) -> str:
    return _hasher.hash(senha)


def verificar_senha(hash_gravado: str | None, senha: str) -> bool:
    """Só aceita hash Argon2. As senhas do sistema antigo (pbkdf2/scrypt) não são migradas:
    na carga, todos recebem senha provisória e trocam no primeiro acesso."""
    try:
        return _hasher.verify(hash_gravado or _HASH_FALSO, senha) and hash_gravado is not None
    except (VerificationError, InvalidHashError):
        return False


def validar_senha_nova(senha: str, login: str) -> None:
    minimo = config().senha_tamanho_minimo
    if len(senha) < minimo:
        raise HTTPException(422, f"A senha precisa ter pelo menos {minimo} caracteres.")
    if senha.isdigit() or senha.isalpha():
        raise HTTPException(422, "A senha precisa misturar letras e números.")
    if login.lower() in senha.lower():
        raise HTTPException(422, "A senha não pode conter o seu login.")


def _resumo(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def ip_cliente(request: Request) -> str | None:
    # X-Real-IP é gravado pelo nginx do servidor (o cliente não consegue forjar)
    ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "")
    return ip[:45] or None


def criar_sessao(db: Session, usuario: Usuario, request: Request, response: Response) -> str:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    db.add(
        Sessao(
            token_hash=_resumo(token),
            csrf=csrf,
            usuario_id=usuario.id,
            expira_em=datetime.now(UTC) + timedelta(hours=config().sessao_horas),
            ip=ip_cliente(request),
            agente=(request.headers.get("user-agent") or "")[:300],
        )
    )
    # Cookie de sessão do navegador: quem manda na validade é o servidor (expira_em)
    response.set_cookie(nome_cookie(), token, httponly=True, secure=config().producao, samesite="strict", path="/")
    return csrf


def encerrar_sessao(db: Session, request: Request, response: Response) -> None:
    token = request.cookies.get(nome_cookie())
    if token:
        sessao = db.scalar(select(Sessao).where(Sessao.token_hash == _resumo(token)))
        if sessao:
            db.delete(sessao)
    response.delete_cookie(nome_cookie(), path="/", secure=config().producao, httponly=True, samesite="strict")


@dataclass
class Contexto:
    usuario: Usuario
    sessao: Sessao
    ip: str | None

    def tem_modulo(self, *modulos: str) -> bool:
        """Administrador enxerga todos os módulos."""
        return self.usuario.admin or any(getattr(self.usuario, f"mod_{m}") for m in modulos)


def contexto(request: Request, db: Session = Depends(get_db)) -> Contexto:
    """Identifica o usuário pelo cookie de sessão e confere o token CSRF nas gravações."""
    token = request.cookies.get(nome_cookie())
    sessao = db.scalar(select(Sessao).where(Sessao.token_hash == _resumo(token))) if token else None
    agora = datetime.now(UTC)
    # Além da validade deslizante, há um teto: um cookie esquecido em PC compartilhado não vale para sempre
    vencida = sessao is None or sessao.expira_em <= agora or agora - sessao.criada_em > timedelta(days=config().sessao_max_dias)
    if vencida or not sessao.usuario.ativo:
        raise HTTPException(401, "Sessão expirada. Entre novamente.")
    if request.method not in METODOS_LEITURA:
        enviado = request.headers.get("x-csrf-token") or ""
        if not hmac.compare_digest(enviado, sessao.csrf):
            raise HTTPException(403, "Requisição recusada. Recarregue a página e tente de novo.")
    duracao = timedelta(hours=config().sessao_horas)
    if sessao.expira_em - agora < duracao / 2:  # renova enquanto o usuário está usando
        sessao.expira_em = agora + duracao
        db.commit()
    return Contexto(usuario=sessao.usuario, sessao=sessao, ip=ip_cliente(request))


def exigir(*modulos: str, admin: bool = False, aprovador: bool = False):
    """Dependência do FastAPI: exige login, senha já trocada e a permissão pedida.

    - modulos: basta ter UM deles (ou ser administrador)
    - admin: só administrador
    - aprovador: precisa de "pode aprovar" (nem o administrador passa sem isso)
    """
    for m in modulos:
        if m not in MODULOS:
            raise ValueError(f"Módulo desconhecido: {m}")

    def dependencia(ctx: Contexto = Depends(contexto)) -> Contexto:
        if ctx.usuario.trocar_senha:
            raise HTTPException(403, "TROCAR_SENHA")
        if admin and not ctx.usuario.admin:
            raise HTTPException(403, "Só o administrador pode fazer isso.")
        if modulos and not ctx.tem_modulo(*modulos):
            raise HTTPException(403, "Seu usuário não tem acesso a este módulo.")
        if aprovador and not ctx.usuario.pode_aprovar:
            raise HTTPException(403, "Só quem pode aprovar (assinar pela Qualidade) pode fazer isso.")
        return ctx

    return dependencia


QUALQUER = exigir()
ADMIN = exigir(admin=True)
QUALIDADE = exigir("qualidade")
AUDITORIA = exigir("qualidade")  # administrador também passa (tem todos os módulos)
APROVADOR = exigir("qualidade", aprovador=True)


def _json(valor: Any) -> Any:
    if isinstance(valor, datetime | date):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, dict):
        return {k: _json(v) for k, v in valor.items()}
    if isinstance(valor, list | tuple):
        return [_json(v) for v in valor]
    return valor


def diferencas(antes: dict, depois: dict) -> dict:
    """Só os campos que mudaram: {campo: [antes, depois]}."""
    return {k: [_json(antes.get(k)), _json(v)] for k, v in depois.items() if antes.get(k) != v}


def auditar(
    db: Session,
    ctx: Contexto | None,
    acao: str,
    entidade: str | None = None,
    entidade_id: Any = None,
    detalhes: dict | None = None,
    *,
    lote_id: int | None = None,
    login: str | None = None,
    ip: str | None = None,
) -> None:
    """Grava o registro de auditoria na mesma transação da alteração (quem chama faz o commit)."""
    db.add(
        Auditoria(
            usuario_id=ctx.usuario.id if ctx else None,
            login=ctx.usuario.login if ctx else login,
            acao=acao,
            entidade=entidade,
            entidade_id=str(entidade_id) if entidade_id is not None else None,
            lote_id=lote_id,
            detalhes=_json(detalhes) if detalhes else None,
            ip=ctx.ip if ctx else ip,
        )
    )
