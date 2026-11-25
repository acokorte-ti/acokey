"""Criação de lote, usada pelo painel (novo lote) e pela matéria-prima (criar lote a partir da corrida).

Regras do sistema antigo (legado/app.py: /novo e /materia-prima/<id>/criar-lote).
"""
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import agora_local
from app.historico import registrar_evento
from app.models import TIPOS_LOTE, Lote, OrdemProducao
from app.seguranca import Contexto, auditar, limpar_texto


def buscar_lote(db: Session, lote_id: int, incluir_cancelado: bool = False) -> Lote:
    lote = db.get(Lote, lote_id)
    if not lote or (lote.cancelado_em and not incluir_cancelado):
        raise HTTPException(404, "Lote não encontrado.")
    return lote


def numero_em_uso(db: Session, numero: str, exceto_id: int | None = None) -> bool:
    consulta = select(Lote.id).where(func.lower(Lote.numero) == numero.strip().lower())
    if exceto_id:
        consulta = consulta.where(Lote.id != exceto_id)
    return db.scalar(consulta) is not None


def op_do_cadastro(db: Session, op: str) -> OrdemProducao:
    """A OP do lote precisa existir no cadastro de OPs (com o Mega ligado, as OPs abertas entram sozinhas)."""
    cadastro = db.scalar(select(OrdemProducao).where(OrdemProducao.op == op))
    if not cadastro:
        raise HTTPException(
            422,
            f"A OP {op} não existe no cadastro de OPs. Confira o número digitado ou cadastre a OP em "
            "Cadastros › Ordens de produção.",
        )
    return cadastro


def criar_lote(
    db: Session,
    ctx: Contexto,
    *,
    op: str,
    numero: str,
    tipo: str,
    qtd: int,
    coditem: str = "",
    corrida: str = "",
    materia_prima_id: int | None = None,
    texto_evento: str | None = None,
) -> Lote:
    """Valida e grava (flush, sem commit). O CODITEM, se vazio, vem do cadastro da OP."""
    op, numero, tipo = limpar_texto(op).strip(), limpar_texto(numero).strip(), (tipo or "").strip().upper()
    coditem, corrida = limpar_texto(coditem or "").strip(), limpar_texto(corrida or "").strip()
    if not op or not numero:
        raise HTTPException(422, "Informe a OP e o número do lote.")
    if tipo not in TIPOS_LOTE:
        raise HTTPException(422, "O formato precisa ser PIN, BOX ou ARK.")
    if qtd is None or qtd <= 0:
        raise HTTPException(422, "Informe uma quantidade de peças maior que zero.")
    if numero_em_uso(db, numero):
        raise HTTPException(409, f"O lote {numero} já existe.")
    cadastro = op_do_cadastro(db, op)
    coditem = coditem or cadastro.coditem or ""
    agora = agora_local()
    lote = Lote(
        op=op, numero=numero, tipo=tipo, qtd=qtd, coditem=coditem, corrida=corrida,
        materia_prima_id=materia_prima_id, etapa=0, etapa_desde=agora, criado_em=agora,
    )  # fmt: skip
    db.add(lote)
    db.flush()
    registrar_evento(db, lote.id, texto_evento or f"Lote criado (OP {op}, {tipo}, {qtd} peças)")
    auditar(db, ctx, "CRIAR", "lote", lote.id,
            {"op": op, "numero": numero, "tipo": tipo, "qtd": qtd, "coditem": coditem, "corrida": corrida},
            lote_id=lote.id)  # fmt: skip
    return lote
