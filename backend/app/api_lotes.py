"""Etapas do processo, lotes e anexos (somente leitura nesta fase)."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import fluxo
from app.config import agora_local, config
from app.db import get_db
from app.estado import estado_lotes, lotes_com_nc_aberta
from app.models import TIPOS_LOTE, Anexo, Evento, Lote, NaoConformidade
from app.seguranca import QUALQUER, Contexto

rota = APIRouter()

TIPOS_ARQUIVO = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def _resumo(lote: Lote, estado: fluxo.Estado, nc_aberta: bool) -> dict:
    indice = fluxo.etapa_real(lote.tipo, estado)
    concluido = indice >= fluxo.CONCLUIDO
    atual = None
    if not concluido:
        etapa = fluxo.ETAPAS[indice]
        atual = {"indice": indice, "chave": etapa.chave, "curto": etapa.curto_de(lote.tipo), "setor": etapa.setor}
        nc_aberta = nc_aberta or fluxo.nc_pendente_etapa(etapa, lote.tipo, estado)
    aprovadas, total = fluxo.progresso(lote.tipo, estado)
    return {
        "id": lote.id,
        "numero": lote.numero,
        "op": lote.op,
        "tipo": lote.tipo,
        "qtd": lote.qtd,
        "corrida": lote.corrida,
        "coditem": lote.coditem,
        "criado_em": lote.criado_em,
        "etapa_desde": lote.etapa_desde,
        "dias_na_etapa": (agora_local() - lote.etapa_desde).days if lote.etapa_desde else None,
        "concluido": concluido,
        "etapa_atual": atual,
        "progresso": {"aprovadas": aprovadas, "total": total},
        "nc_aberta": nc_aberta,
    }


@rota.get("/etapas")
def listar_etapas(_: Contexto = Depends(QUALQUER)) -> list[dict]:
    return [
        {
            "chave": e.chave,
            "nome": e.nome,
            "curto": e.curto,
            "setor": e.setor,
            "tipos": [t for t in TIPOS_LOTE if t in e.tipos],
            "exige_anexo": e.exige_anexo,
        }
        for e in fluxo.ETAPAS
    ]


@rota.get("/lotes")
def listar_lotes(_: Contexto = Depends(QUALQUER), db: Session = Depends(get_db)) -> dict:
    lotes = list(db.scalars(select(Lote).order_by(Lote.id.desc())))
    estados, _ultimos = estado_lotes(db)
    com_nc = lotes_com_nc_aberta(db)
    return {"itens": [_resumo(lote, estados.get(lote.id, {}), lote.id in com_nc) for lote in lotes]}


@rota.get("/lotes/{lote_id}")
def ver_lote(lote_id: int, _: Contexto = Depends(QUALQUER), db: Session = Depends(get_db)) -> dict:
    lote = db.get(Lote, lote_id)
    if not lote:
        raise HTTPException(404, "Lote não encontrado.")
    estados, ultimos = estado_lotes(db, [lote_id])
    estado = estados.get(lote_id, {})
    com_nc = lotes_com_nc_aberta(db, [lote_id])
    indice_real = fluxo.etapa_real(lote.tipo, estado)

    anexos_por_etapa: dict[str, list[dict]] = {}
    for a in db.scalars(select(Anexo).where(Anexo.lote_id == lote_id).order_by(Anexo.id)):
        anexos_por_etapa.setdefault(a.etapa, []).append(
            {"id": a.id, "sub": a.sub, "nome": a.nome, "quando": a.quando, "apenas_registro": a.apenas_registro}
        )

    etapas = []
    for indice, e in enumerate(fluxo.ETAPAS):
        aplicavel = e.aplicavel(lote.tipo)
        subs = []
        for s in e.subs_de(lote.tipo) if aplicavel else ():
            r = ultimos.get((lote_id, e.chave, s))
            subs.append(
                {
                    "sub": s,
                    "nome": fluxo.SUB_NOME.get(s, s),
                    "registro": (
                        {"id": r.id, "status": r.status, "quando": r.quando, "responsavel": r.responsavel} if r else None
                    ),
                }
            )
        etapas.append(
            {
                "chave": e.chave,
                "nome": e.nome_de(lote.tipo),
                "curto": e.curto_de(lote.tipo),
                "setor": e.setor,
                "aplicavel": aplicavel,
                "situacao": fluxo.situacao_etapa(indice, lote.tipo, estado, indice_real),
                "subs": subs,
                "anexos": anexos_por_etapa.get(e.chave, []),
            }
        )

    eventos = db.scalars(select(Evento).where(Evento.lote_id == lote_id).order_by(Evento.id.desc()))
    ncs = db.scalars(select(NaoConformidade).where(NaoConformidade.lote_id == lote_id).order_by(NaoConformidade.id))
    return {
        "lote": _resumo(lote, estado, lote_id in com_nc),
        "etapas": etapas,
        "eventos": [{"quando": ev.quando, "texto": ev.texto} for ev in eventos],
        "ncs": [
            {"id": n.id, "numero": n.numero, "etapa": n.etapa, "sub": n.sub, "status": n.status, "disposicao": n.disposicao}
            for n in ncs
        ],
    }


def caminho_seguro(relativo: str) -> Path | None:
    """Caminho do arquivo dentro da pasta de arquivos; None se ele tentar sair dela ou não existir."""
    base = config().pasta_arquivos
    if not relativo:
        return None
    caminho = (base / relativo).resolve()
    if base != caminho and base not in caminho.parents:
        return None
    return caminho if caminho.is_file() else None


@rota.get("/anexos/{anexo_id}/arquivo")
def baixar_anexo(anexo_id: int, _: Contexto = Depends(QUALQUER), db: Session = Depends(get_db)) -> FileResponse:
    anexo = db.get(Anexo, anexo_id)
    if not anexo:
        raise HTTPException(404, "Anexo não encontrado.")
    caminho = caminho_seguro(anexo.arquivo)
    if not caminho:
        raise HTTPException(404, f"O arquivo '{anexo.nome}' não foi encontrado no servidor.")
    tipo = TIPOS_ARQUIVO.get(caminho.suffix.lower())
    # PDF e imagem abrem no navegador; qualquer outra coisa só é baixada (nunca interpretada)
    return FileResponse(
        caminho,
        media_type=tipo or "application/octet-stream",
        filename=anexo.nome,
        content_disposition_type="inline" if tipo else "attachment",
    )
