"""Abertura e encerramento AUTOMÁTICOS de não conformidade (regras do sistema antigo:
legado/app.py, _abrir_nc_automatica e _fechar_nc_se_aberta).

- Todo registro salvo como "reprovado" abre uma NC (não existe reprovação sem rastro formal).
- Quando um registro NOVO da mesma etapa/sub é aprovado e havia NC aberta ou em tratamento (retrabalho),
  a NC se encerra sozinha. NC já encerrada como sucata/uso como está/anulada não é tocada.
A decisão da disposição (tela de NC) fica em api_nc.py.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import fluxo
from app.config import agora_local
from app.historico import registrar_evento
from app.models import Lote, NaoConformidade, Registro
from app.numeracao import proximo_numero
from app.seguranca import Contexto, auditar


def nome_etapa(etapa: str, sub: str, tipo: str) -> str:
    """'Dureza HRC', 'Tração / Charpy - Ensaio de tração'..."""
    curto = fluxo.POR_CHAVE[etapa].curto_de(tipo) if etapa in fluxo.POR_CHAVE else etapa
    return f"{curto} - {fluxo.SUB_NOME.get(sub, sub)}" if sub else curto


def abrir_nc_automatica(db: Session, ctx: Contexto | None, lote: Lote, registro: Registro, descricao: str) -> NaoConformidade:
    nc = NaoConformidade(
        numero=proximo_numero(db, "NC"),
        lote_id=lote.id,
        etapa=registro.etapa,
        sub=registro.sub,
        registro_id=registro.id,
        descricao=descricao,
        qtd_lote_na_abertura=lote.qtd or 0,
        status="aberta",
        aberta_em=agora_local(),
        aberta_por=ctx.usuario.nome if ctx else "",
    )
    db.add(nc)
    db.flush()
    registrar_evento(
        db, lote.id,
        f"NC {nc.numero} aberta automaticamente ({nome_etapa(registro.etapa, registro.sub, lote.tipo)}) — aguardando decisão de disposição",
    )  # fmt: skip
    auditar(db, ctx, "ABRIR", "nc", nc.id, {"numero": nc.numero, "etapa": nc.etapa, "sub": nc.sub,
                                            "registro_id": registro.id, "descricao": descricao}, lote_id=lote.id)  # fmt: skip
    return nc


def fechar_nc_se_aberta(db: Session, ctx: Contexto | None, lote_id: int, etapa: str, sub: str) -> NaoConformidade | None:
    """Chamar quando um registro NOVO desta etapa/sub for aprovado."""
    nc = db.scalar(
        select(NaoConformidade)
        .where(NaoConformidade.lote_id == lote_id, NaoConformidade.etapa == etapa, NaoConformidade.sub == sub,
               NaoConformidade.status.in_(fluxo.NC_EM_ABERTO))
        .order_by(NaoConformidade.id.desc())
    )  # fmt: skip
    if not nc:
        return None
    antes = nc.status
    nc.status = "encerrada"
    nc.disposicao = nc.disposicao or "retrabalho"
    nc.encerrada_em = agora_local()
    nc.encerrada_por = ctx.usuario.nome if ctx else ""
    registrar_evento(db, lote_id, f"NC {nc.numero} encerrada automaticamente — novo registro aprovado após retrabalho")
    auditar(db, ctx, "ENCERRAR", "nc", nc.id, {"status": [antes, "encerrada"], "disposicao": nc.disposicao,
                                               "via": "retrabalho aprovado"}, lote_id=lote_id)  # fmt: skip
    return nc
