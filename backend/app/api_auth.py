"""Login, troca de senha, usuários e consulta da auditoria."""
from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import FUSO, config
from app.db import get_db
from app.models import MODULOS, Auditoria, Sessao, Usuario
from app.seguranca import (
    ADMIN,
    AUDITORIA,
    Contexto,
    auditar,
    contexto,
    criar_sessao,
    diferencas,
    encerrar_sessao,
    hash_senha,
    ip_cliente,
    validar_senha_nova,
    verificar_senha,
)

rota = APIRouter()


def _usuario(u: Usuario) -> dict:
    return {
        "id": u.id,
        "login": u.login,
        "nome": u.nome,
        "cargo": u.cargo,
        "ativo": u.ativo,
        "trocar_senha": u.trocar_senha,
        "admin": u.admin,
        "modulos": u.modulos,
        "pode_aprovar": u.pode_aprovar,
        "tem_assinatura": bool(u.assinatura_arquivo),
        "ultimo_login_em": u.ultimo_login_em,
        "bloqueado": bool(u.bloqueado_ate and u.bloqueado_ate > datetime.now(UTC)),
    }


class LoginEntrada(BaseModel):
    login: str = Field(min_length=1, max_length=60)
    senha: str = Field(min_length=1, max_length=200)


@rota.post("/auth/login")
def entrar(dados: LoginEntrada, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    cfg = config()
    login = dados.login.strip().lower()
    # FOR UPDATE: tentativas simultâneas no mesmo login entram em fila, e o contador não perde contagem
    usuario = db.scalar(select(Usuario).where(func.lower(Usuario.login) == login).with_for_update())
    agora = datetime.now(UTC)
    # Uma só resposta para login inexistente, senha errada e conta bloqueada: não revela quais logins existem
    recusa = HTTPException(
        401,
        f"Usuário ou senha inválidos. Depois de {cfg.login_max_tentativas} tentativas erradas, "
        f"o acesso fica bloqueado por {cfg.login_bloqueio_minutos} minutos.",
    )
    # No registro só entra login que existe: se a pessoa digitar a senha no campo do login, ela não fica gravada
    login_registrado = usuario.login if usuario else "(desconhecido)"

    if usuario and usuario.bloqueado_ate and usuario.bloqueado_ate > agora:
        verificar_senha(None, dados.senha)  # gasta o mesmo tempo de uma conferência de senha
        auditar(db, None, "LOGIN_BLOQUEADO", login=login_registrado, ip=ip_cliente(request))
        db.commit()
        raise recusa

    senha_ok = verificar_senha(usuario.senha_hash if usuario else None, dados.senha)
    if not (usuario and usuario.ativo and senha_ok):
        if usuario:
            usuario.tentativas_falhas += 1
            if usuario.tentativas_falhas >= cfg.login_max_tentativas:
                usuario.bloqueado_ate = agora + timedelta(minutes=cfg.login_bloqueio_minutos)
                usuario.tentativas_falhas = 0
        auditar(db, None, "LOGIN_FALHA", login=login_registrado, ip=ip_cliente(request))
        db.commit()
        raise recusa

    usuario.tentativas_falhas = 0
    usuario.bloqueado_ate = None
    usuario.ultimo_login_em = agora
    db.execute(delete(Sessao).where(Sessao.usuario_id == usuario.id, Sessao.expira_em <= agora))
    csrf = criar_sessao(db, usuario, request, response)
    auditar(db, None, "LOGIN", login=usuario.login, ip=ip_cliente(request))
    db.commit()
    return {"usuario": _usuario(usuario), "csrf": csrf}


@rota.post("/auth/logout")
def sair(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    encerrar_sessao(db, request, response)
    db.commit()
    return {"ok": True}


@rota.get("/auth/eu")
def eu(ctx: Contexto = Depends(contexto)) -> dict:
    return {"usuario": _usuario(ctx.usuario), "csrf": ctx.sessao.csrf}


class TrocaSenha(BaseModel):
    senha_atual: str = Field(min_length=1, max_length=200)
    senha_nova: str = Field(min_length=1, max_length=200)


@rota.post("/auth/trocar-senha")
def trocar_senha(dados: TrocaSenha, ctx: Contexto = Depends(contexto), db: Session = Depends(get_db)) -> dict:
    usuario = ctx.usuario
    if not verificar_senha(usuario.senha_hash, dados.senha_atual):
        raise HTTPException(422, "A senha atual não confere.")
    if dados.senha_nova == dados.senha_atual:
        raise HTTPException(422, "A senha nova precisa ser diferente da atual.")
    validar_senha_nova(dados.senha_nova, usuario.login)
    usuario.senha_hash = hash_senha(dados.senha_nova)
    usuario.trocar_senha = False
    # Derruba as outras sessões abertas com a senha antiga
    db.execute(delete(Sessao).where(Sessao.usuario_id == usuario.id, Sessao.id != ctx.sessao.id))
    auditar(db, ctx, "TROCAR_SENHA", "usuario", usuario.id)
    db.commit()
    return {"usuario": _usuario(usuario)}


# ---------------------------------------------------------------- usuários (só administrador)


class UsuarioNovo(BaseModel):
    login: str = Field(min_length=3, max_length=60, pattern=r"^[a-zA-Z0-9._-]+$")
    nome: str = Field(min_length=2, max_length=120)
    cargo: str = Field("", max_length=80)
    senha: str = Field(min_length=1, max_length=200)
    admin: bool = False
    modulos: list[str] = Field(default_factory=list, max_length=len(MODULOS))
    pode_aprovar: bool = False


class UsuarioAlteracao(BaseModel):
    nome: str | None = Field(None, min_length=2, max_length=120)
    cargo: str | None = Field(None, max_length=80)
    ativo: bool | None = None
    admin: bool | None = None
    modulos: list[str] | None = Field(None, max_length=len(MODULOS))
    pode_aprovar: bool | None = None


class SenhaProvisoria(BaseModel):
    senha: str = Field(min_length=1, max_length=200)


def _validar_modulos(modulos: list[str]) -> None:
    desconhecidos = sorted(set(modulos) - set(MODULOS))
    if desconhecidos:
        raise HTTPException(422, f"Módulo inválido: {', '.join(desconhecidos)}. Use: {', '.join(MODULOS)}.")


def _aplicar_modulos(usuario: Usuario, modulos: list[str]) -> None:
    for m in MODULOS:
        setattr(usuario, f"mod_{m}", m in modulos)


def _permissoes(u: Usuario) -> dict:
    return {"nome": u.nome, "cargo": u.cargo, "ativo": u.ativo, "admin": u.admin, "modulos": u.modulos, "pode_aprovar": u.pode_aprovar}


@rota.get("/usuarios")
def listar_usuarios(_: Contexto = Depends(ADMIN), db: Session = Depends(get_db)) -> list[dict]:
    return [_usuario(u) for u in db.scalars(select(Usuario).order_by(Usuario.nome))]


@rota.post("/usuarios", status_code=201)
def criar_usuario(dados: UsuarioNovo, ctx: Contexto = Depends(ADMIN), db: Session = Depends(get_db)) -> dict:
    _validar_modulos(dados.modulos)
    login = dados.login.strip().lower()
    validar_senha_nova(dados.senha, login)
    usuario = Usuario(
        login=login,
        nome=dados.nome.strip(),
        cargo=dados.cargo.strip(),
        senha_hash=hash_senha(dados.senha),
        trocar_senha=True,
        admin=dados.admin,
        pode_aprovar=dados.pode_aprovar,
    )
    _aplicar_modulos(usuario, dados.modulos)
    db.add(usuario)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Já existe um usuário com esse login.") from None
    auditar(db, ctx, "CRIAR", "usuario", usuario.id, {"login": login, **_permissoes(usuario)})
    db.commit()
    return _usuario(usuario)


def _contar_outros(db: Session, usuario: Usuario, *condicao) -> int:
    return db.scalar(select(func.count(Usuario.id)).where(Usuario.ativo, Usuario.id != usuario.id, *condicao)) or 0


@rota.patch("/usuarios/{usuario_id}")
def alterar_usuario(
    usuario_id: int, dados: UsuarioAlteracao, ctx: Contexto = Depends(ADMIN), db: Session = Depends(get_db)
) -> dict:
    usuario = db.get(Usuario, usuario_id)
    if not usuario:
        raise HTTPException(404, "Usuário não encontrado.")
    antes = _permissoes(usuario)
    depois = {**antes, **dados.model_dump(exclude_none=True)}
    _validar_modulos(depois["modulos"])

    if usuario.id == ctx.usuario.id and not depois["ativo"]:
        raise HTTPException(422, "Você não pode desativar o seu próprio usuário.")
    perde_admin = antes["admin"] and antes["ativo"] and not (depois["admin"] and depois["ativo"])
    if perde_admin and not _contar_outros(db, usuario, Usuario.admin):
        raise HTTPException(422, "Este é o único administrador ativo: o sistema ficaria sem ninguém para administrar.")
    perde_aprovacao = antes["pode_aprovar"] and antes["ativo"] and not (depois["pode_aprovar"] and depois["ativo"])
    if perde_aprovacao and not _contar_outros(db, usuario, Usuario.pode_aprovar):
        raise HTTPException(
            422, "Este é o único usuário ativo que pode aprovar: dê essa permissão a outra pessoa antes."
        )

    usuario.nome, usuario.cargo = depois["nome"].strip(), depois["cargo"].strip()
    usuario.ativo, usuario.admin, usuario.pode_aprovar = depois["ativo"], depois["admin"], depois["pode_aprovar"]
    _aplicar_modulos(usuario, depois["modulos"])
    mudou = diferencas(antes, _permissoes(usuario))
    reduziu_acesso = not usuario.ativo or any(k in mudou for k in ("admin", "modulos", "pode_aprovar"))
    if reduziu_acesso:  # derruba as sessões abertas: o acesso novo vale a partir do próximo login
        db.execute(delete(Sessao).where(Sessao.usuario_id == usuario.id, Sessao.id != ctx.sessao.id))
    if mudou:
        auditar(db, ctx, "ALTERAR", "usuario", usuario.id, mudou)
    db.commit()
    return _usuario(usuario)


@rota.post("/usuarios/{usuario_id}/senha")
def redefinir_senha(
    usuario_id: int, dados: SenhaProvisoria, ctx: Contexto = Depends(ADMIN), db: Session = Depends(get_db)
) -> dict:
    usuario = db.get(Usuario, usuario_id)
    if not usuario:
        raise HTTPException(404, "Usuário não encontrado.")
    validar_senha_nova(dados.senha, usuario.login)
    usuario.senha_hash = hash_senha(dados.senha)
    usuario.trocar_senha = True  # a pessoa escolhe a própria senha no próximo acesso
    usuario.tentativas_falhas = 0
    usuario.bloqueado_ate = None
    db.execute(delete(Sessao).where(Sessao.usuario_id == usuario.id, Sessao.id != ctx.sessao.id))
    auditar(db, ctx, "REDEFINIR_SENHA", "usuario", usuario.id)
    db.commit()
    return _usuario(usuario)


# ---------------------------------------------------------------- auditoria


@rota.get("/auditoria")
def listar_auditoria(
    de: date | None = None,
    ate: date | None = None,
    login: str | None = None,
    acao: str | None = None,
    entidade: str | None = None,
    lote_id: int | None = None,
    pagina: int = 1,
    tamanho: int = 50,
    _: Contexto = Depends(AUDITORIA),
    db: Session = Depends(get_db),
) -> dict:
    filtros = []
    if de:
        filtros.append(Auditoria.quando >= datetime.combine(de, time.min, FUSO))
    if ate:
        filtros.append(Auditoria.quando < datetime.combine(ate + timedelta(days=1), time.min, FUSO))
    if login:
        filtros.append(Auditoria.login.ilike(f"%{login.strip()}%"))
    if acao:
        filtros.append(Auditoria.acao == acao.strip().upper())
    if entidade:
        filtros.append(Auditoria.entidade == entidade.strip())
    if lote_id:
        filtros.append(Auditoria.lote_id == lote_id)
    tamanho = max(1, min(tamanho, 200))
    total = db.scalar(select(func.count(Auditoria.id)).where(*filtros))
    linhas = db.scalars(
        select(Auditoria).where(*filtros).order_by(Auditoria.id.desc()).offset((max(pagina, 1) - 1) * tamanho).limit(tamanho)
    )
    return {
        "total": total,
        "itens": [
            {
                "id": a.id,
                "quando": a.quando,
                "login": a.login,
                "acao": a.acao,
                "entidade": a.entidade,
                "entidade_id": a.entidade_id,
                "lote_id": a.lote_id,
                "detalhes": a.detalhes,
                "ip": a.ip,
            }
            for a in linhas
        ],
    }
