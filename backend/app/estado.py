"""Lê do banco o estado que as regras de fluxo.py precisam, para muitos lotes de uma vez (sem N+1)."""
from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.fluxo import NC_EM_ABERTO, SituacaoSub
from app.models import NaoConformidade, Registro


def ultimos_registros(db: Session, lote_ids: Iterable[int] | None = None) -> dict[tuple[int, str, str], Registro]:
    """Último registro NÃO anulado de cada (lote, etapa, sub).

    Registro anulado (erro de digitação reconhecido numa NC) é invisível para o fluxo, como se nunca
    tivesse existido: o anterior a ele volta a valer.
    """
    consulta = select(Registro).where(Registro.anulado.is_(False)).order_by(Registro.id)
    if lote_ids is not None:
        consulta = consulta.where(Registro.lote_id.in_(list(lote_ids)))
    ultimos: dict[tuple[int, str, str], Registro] = {}
    for r in db.scalars(consulta):
        ultimos[(r.lote_id, r.etapa, r.sub)] = r  # em ordem de id: o mais novo sobrescreve
    return ultimos


def estado_lotes(
    db: Session, lote_ids: Iterable[int] | None = None
) -> tuple[dict[int, dict[tuple[str, str], SituacaoSub]], dict[tuple[int, str, str], Registro]]:
    """{lote_id: {(etapa, sub): SituacaoSub}} e os registros usados, para quem precisar mostrar detalhes."""
    ids = list(lote_ids) if lote_ids is not None else None
    ultimos = ultimos_registros(db, ids)
    reprovados = [r.id for r in ultimos.values() if r.status == "reprovado"]
    nc_do_registro: dict[int, NaoConformidade] = {}
    if reprovados:
        for nc in db.scalars(
            select(NaoConformidade).where(NaoConformidade.registro_id.in_(reprovados)).order_by(NaoConformidade.id)
        ):
            nc_do_registro[nc.registro_id] = nc  # vale a NC mais recente do registro
    estados: dict[int, dict[tuple[str, str], SituacaoSub]] = defaultdict(dict)
    for (lote_id, etapa, sub), r in ultimos.items():
        nc = nc_do_registro.get(r.id)
        estados[lote_id][(etapa, sub)] = SituacaoSub(
            registro_status=r.status,
            nc_status=nc.status if nc else None,
            nc_disposicao=nc.disposicao if nc else None,
        )
    return estados, ultimos


def lotes_com_nc_aberta(db: Session, lote_ids: Iterable[int] | None = None) -> set[int]:
    consulta = select(NaoConformidade.lote_id).where(NaoConformidade.status.in_(NC_EM_ABERTO))
    if lote_ids is not None:
        consulta = consulta.where(NaoConformidade.lote_id.in_(list(lote_ids)))
    return set(db.scalars(consulta))
