"""Etapas do processo, lotes (lista, página, novo, editar, cancelar), sugestão de OP e download de anexo.

Regras do sistema antigo (legado/app.py: novo, lote_tem_dados_salvos, editar_lote, excluir_lote, ver_lote):
- novo lote: Qualidade ou PCP; a OP pode vir do cadastro de OPs (preenche tipo, item e quantidade);
- lote "limpo" (sem nenhum registro nem anexo) qualquer um com Qualidade ou PCP edita ou cancela;
- lote com registro ou anexo: só quem pode aprovar (ou o administrador), com motivo escrito (era a senha
  administrativa compartilhada);
- nada é apagado: o lote é CANCELADO (sai do painel, fica no banco e na auditoria) e o número fica livre para
  um lote novo; não se cancela lote cujo databook da OP/tipo já foi enviado ao cliente.
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import ciclo_lote, fluxo
from app.api_recursos import listar_desenhos
from app.arquivos import resposta_arquivo
from app.config import agora_local
from app.db import get_db
from app.estado import estado_lotes, lotes_com_nc_aberta
from app.historico import registrar_evento
from app.lotes import buscar_lote, criar_lote, numero_em_uso
from app.models import TIPOS_LOTE, Anexo, Evento, Lote, NaoConformidade, OrdemProducao
from app.seguranca import QUALQUER, Contexto, auditar, diferencas, exigir, limpar_texto

rota = APIRouter()

NOVO_LOTE = exigir("qualidade", "pcp")
_PREFIXO_INSTRUCAO = re.compile(r"INSTR\.?\s*CONTROLE\s*TRAVAMENTO\s*(?:DES\s+)?", re.IGNORECASE)


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
    lotes = list(db.scalars(select(Lote).where(Lote.cancelado_em.is_(None)).order_by(Lote.id.desc())))
    estados, _ultimos = estado_lotes(db)
    com_nc = lotes_com_nc_aberta(db)
    return {"itens": [_resumo(lote, estados.get(lote.id, {}), lote.id in com_nc) for lote in lotes]}


# ---------------------------------------------------------------- novo lote (antes de /lotes/{id}: a rota fixa vem primeiro)


def descricao_curta(descricao: str) -> str:
    """'INSTR. CONTROLE TRAVAMENTO ARK 18-24 ...' -> 'ARK 18-24 ...' (como no sistema antigo)."""
    achado = _PREFIXO_INSTRUCAO.search(descricao or "")
    return descricao[achado.end():].strip() if achado else (descricao or "").strip()


@rota.get("/lotes/sugestoes-op")
def sugestoes_op(q: str = "", _: Contexto = Depends(NOVO_LOTE), db: Session = Depends(get_db)) -> list[dict]:
    """OPs do cadastro para o autocompletar do "+ Novo lote": tipo, item e quantidade vêm junto."""
    termo = limpar_texto(q).strip()[:40]
    consulta = select(OrdemProducao)
    if termo:
        parecido = f"%{termo.lower()}%"
        consulta = consulta.where(or_(OrdemProducao.op.like(f"{termo}%"), func.lower(OrdemProducao.coditem).like(parecido),
                                      func.lower(OrdemProducao.descricao).like(parecido)))  # fmt: skip
    ordens = list(db.scalars(consulta.order_by(OrdemProducao.op.desc()).limit(20)))
    contagem = dict(
        db.execute(
            select(Lote.op, func.count(Lote.id)).where(Lote.op.in_([o.op for o in ordens]), Lote.cancelado_em.is_(None)).group_by(Lote.op)
        ).all()
    ) if ordens else {}  # fmt: skip
    return [
        {
            "op": o.op, "cliente": o.cliente, "coditem": o.coditem, "descricao": o.descricao,
            "descricao_curta": descricao_curta(o.descricao), "tipo": o.tipo if o.tipo in TIPOS_LOTE else None,
            "qtd": o.qt_lote, "lotes": contagem.get(o.op, 0),
        }  # fmt: skip
        for o in ordens
    ]


class CorpoLote(BaseModel):
    op: str = Field(min_length=1, max_length=20)
    numero: str = Field(min_length=1, max_length=40)
    tipo: str = Field(min_length=3, max_length=3)
    qtd: int = Field(gt=0, le=1_000_000)
    coditem: str = Field("", max_length=40)


@rota.post("/lotes", status_code=201)
def novo_lote(corpo: CorpoLote, ctx: Contexto = Depends(NOVO_LOTE), db: Session = Depends(get_db)) -> dict:
    lote = criar_lote(db, ctx, op=corpo.op, numero=corpo.numero, tipo=corpo.tipo, qtd=corpo.qtd, coditem=corpo.coditem)
    db.commit()
    return {"id": lote.id, "numero": lote.numero}


# ---------------------------------------------------------------- página do lote


def _nc_pendente(r, nc_do_registro: dict[int, NaoConformidade]) -> dict | None:
    if not r or r.status != "reprovado":
        return None
    nc = nc_do_registro.get(r.id)
    if nc and nc.status != "encerrada":
        return {"id": nc.id, "numero": nc.numero, "status": nc.status}
    return None


@rota.get("/lotes/{lote_id}")
def ver_lote(lote_id: int, _: Contexto = Depends(QUALQUER), db: Session = Depends(get_db)) -> dict:
    lote = buscar_lote(db, lote_id)
    estados, ultimos = estado_lotes(db, [lote_id])
    estado = estados.get(lote_id, {})
    com_nc = lotes_com_nc_aberta(db, [lote_id])
    indice_real = fluxo.etapa_real(lote.tipo, estado)

    anexos_por_etapa: dict[str, list[dict]] = {}
    for a in db.scalars(select(Anexo).where(Anexo.lote_id == lote_id, Anexo.removido_em.is_(None)).order_by(Anexo.id)):
        anexos_por_etapa.setdefault(a.etapa, []).append(
            {"id": a.id, "sub": a.sub, "nome": a.nome, "quando": a.quando, "apenas_registro": a.apenas_registro}
        )
    ids_reprovados = [r.id for r in ultimos.values() if r.status == "reprovado"]
    nc_do_registro: dict[int, NaoConformidade] = {}
    if ids_reprovados:
        for nc in db.scalars(select(NaoConformidade).where(NaoConformidade.registro_id.in_(ids_reprovados)).order_by(NaoConformidade.id)):
            nc_do_registro[nc.registro_id] = nc

    etapas = []
    for indice, e in enumerate(fluxo.ETAPAS):
        aplicavel = e.aplicavel(lote.tipo)
        subs = []
        pendente = None
        for s in e.subs_de(lote.tipo) if aplicavel else ():
            r = ultimos.get((lote_id, e.chave, s))
            pendente = pendente or _nc_pendente(r, nc_do_registro)
            subs.append(
                {
                    "sub": s,
                    "nome": fluxo.SUB_NOME.get(s, s),
                    "registro": (
                        {"id": r.id, "status": r.status, "quando": r.quando, "responsavel": r.responsavel} if r else None
                    ),
                }
            )
        anexos = anexos_por_etapa.get(e.chave, [])
        etapas.append(
            {
                "chave": e.chave,
                "indice": indice,
                "nome": e.nome_de(lote.tipo),
                "curto": e.curto_de(lote.tipo),
                "setor": e.setor,
                "aplicavel": aplicavel,
                "situacao": fluxo.situacao_etapa(indice, lote.tipo, estado, indice_real),
                "subs": subs,
                "anexos": anexos,
                "n_documentos": sum(1 for a in anexos if not a["apenas_registro"]),
                "nc_pendente": pendente,
            }
        )

    eventos = db.scalars(select(Evento).where(Evento.lote_id == lote_id).order_by(Evento.id.desc()))
    ncs = db.scalars(select(NaoConformidade).where(NaoConformidade.lote_id == lote_id).order_by(NaoConformidade.id))
    indice_importacao, checklist = ciclo_lote.checklist_importacao(lote.tipo)
    visual = ultimos.get((lote_id, "visual", ""))
    desenho = next((d for d in listar_desenhos() if d["coditem"] == lote.coditem), None) if lote.coditem else None
    return {
        "lote": _resumo(lote, estado, lote_id in com_nc),
        "etapas": etapas,
        "eventos": [{"quando": ev.quando, "texto": ev.texto} for ev in eventos],
        "ncs": [
            {"id": n.id, "numero": n.numero, "etapa": n.etapa, "sub": n.sub, "status": n.status, "disposicao": n.disposicao}
            for n in ncs
        ],
        # Cursor da etapa em que o lote foi deixado (lotes.etapa): "Concluir etapa atual" anda com ele
        "cursor": lote.etapa,
        "cursor_curto": fluxo.ETAPAS[lote.etapa].curto_de(lote.tipo) if lote.etapa < fluxo.CONCLUIDO else None,
        "pode_avancar": fluxo.pode_avancar(lote.etapa, lote.tipo, estado),
        "tem_dados": ciclo_lote.tem_dados_salvos(db, lote_id),
        "databook_enviado": ciclo_lote.databook_enviado(db, lote),
        "materia_prima": ciclo_lote.mp_json(ciclo_lote.mp_do_lote(db, lote)),
        "carga_tt": ciclo_lote.carga_tt_ativa(db, lote_id),
        "desenho": {"coditem": desenho["coditem"], "descricao": desenho["descricao"]} if desenho else None,
        "avulsos": anexos_por_etapa.get("outros", []),
        "importacao": {"indice": ciclo_lote.NOME_INDICE.get(indice_importacao, ""), "checklist": checklist},
        "laser_disponivel": bool(visual and visual.status == "aprovado"),
    }


# ---------------------------------------------------------------- editar e cancelar


def _exigir_autorizacao(db: Session, ctx: Contexto, lote: Lote, motivo: str, acao: str) -> str:
    """Lote com registro ou anexo: só quem pode aprovar (ou o administrador), com motivo. Devolve o motivo limpo."""
    motivo = limpar_texto(motivo or "").strip()
    if ciclo_lote.tem_dados_salvos(db, lote.id):
        if not (ctx.usuario.pode_aprovar or ctx.usuario.admin):
            raise HTTPException(403, f"Este lote já tem registros salvos: só quem pode aprovar (ou o administrador) pode {acao}.")
        if len(motivo) < 5:
            raise HTTPException(422, f"Este lote já tem registros salvos: escreva o motivo para {acao}.")
    return motivo


class CorpoEditarLote(CorpoLote):
    motivo: str = Field("", max_length=1000)


@rota.patch("/lotes/{lote_id}")
def editar_lote(lote_id: int, corpo: CorpoEditarLote, ctx: Contexto = Depends(NOVO_LOTE), db: Session = Depends(get_db)) -> dict:
    lote = buscar_lote(db, lote_id)
    op, numero = limpar_texto(corpo.op).strip(), limpar_texto(corpo.numero).strip()
    tipo, coditem = corpo.tipo.strip().upper(), limpar_texto(corpo.coditem).strip()
    if not op or not numero or tipo not in TIPOS_LOTE:
        raise HTTPException(422, "Preencha OP, lote, formato (PIN/BOX/ARK) e quantidade válida.")
    antes = {"op": lote.op, "numero": lote.numero, "tipo": lote.tipo, "qtd": lote.qtd, "coditem": lote.coditem or ""}
    depois = {"op": op, "numero": numero, "tipo": tipo, "qtd": corpo.qtd, "coditem": coditem}
    mudancas = diferencas(antes, depois)
    if not mudancas:
        return {"ok": True, "mudou": False}
    motivo = _exigir_autorizacao(db, ctx, lote, corpo.motivo, "editar")
    if numero_em_uso(db, numero, exceto_id=lote.id):
        raise HTTPException(409, f"Já existe outro lote com o número '{numero}'.")
    lote.op, lote.numero, lote.tipo, lote.qtd, lote.coditem = op, numero, tipo, corpo.qtd, coditem
    texto = f"Lote editado por {ctx.usuario.nome} (OP {op}, lote {numero}, {tipo}, {corpo.qtd} pç, item {coditem or '-'})"
    registrar_evento(db, lote.id, texto + (f" — {motivo}" if motivo else ""))
    auditar(db, ctx, "ALTERAR", "lote", lote.id, mudancas | ({"motivo": motivo} if motivo else {}), lote_id=lote.id)
    db.commit()
    return {"ok": True, "mudou": True}


class CorpoCancelar(BaseModel):
    motivo: str = Field("", max_length=1000)


@rota.post("/lotes/{lote_id}/cancelar")
def cancelar_lote(lote_id: int, corpo: CorpoCancelar, ctx: Contexto = Depends(NOVO_LOTE), db: Session = Depends(get_db)) -> dict:
    """No lugar do "Excluir lote" do sistema antigo. O número do lote cancelado ganha o sufixo '-CANC<id>' para ficar
    livre (quem criou com erro cria de novo com o número certo); o número original fica no histórico e na auditoria."""
    lote = buscar_lote(db, lote_id)
    motivo = _exigir_autorizacao(db, ctx, lote, corpo.motivo, "cancelar")
    if ciclo_lote.databook_enviado(db, lote):
        auditar(db, ctx, "TENTATIVA_BLOQUEADA", "lote", lote.id, {"motivo": "cancelar lote com databook enviado"}, lote_id=lote.id)
        db.commit()
        raise HTTPException(409, f"Não dá para cancelar: o databook da OP {lote.op}/{lote.tipo} já foi enviado ao cliente. Se precisar "
                                 "mesmo cancelar, desfaça o envio em Databooks primeiro.")  # fmt: skip
    original = lote.numero
    sufixo = f"-CANC{lote.id}"
    lote.numero = original[: 40 - len(sufixo)] + sufixo
    lote.cancelado_em = agora_local()
    lote.cancelado_por = ctx.usuario.nome
    lote.cancelado_motivo = motivo
    texto = f"Lote {original} (OP {lote.op}, {lote.tipo}, {lote.qtd} pç) cancelado por {ctx.usuario.nome}"
    if lote.corrida:
        texto += f" — saldo da corrida {lote.corrida} liberado"
    registrar_evento(db, lote.id, texto + (f". Motivo: {motivo}" if motivo else ""))
    auditar(db, ctx, "CANCELAR", "lote", lote.id,
            {"numero": original, "op": lote.op, "tipo": lote.tipo, "qtd": lote.qtd, "corrida": lote.corrida, "coditem": lote.coditem,
             "motivo": motivo or None}, lote_id=lote.id)  # fmt: skip
    db.commit()
    return {"ok": True, "mensagem": f"Lote {original} (OP {lote.op}) cancelado."}


@rota.get("/anexos/{anexo_id}/arquivo")
def baixar_anexo(anexo_id: int, _: Contexto = Depends(QUALQUER), db: Session = Depends(get_db)) -> FileResponse:
    anexo = db.get(Anexo, anexo_id)
    if not anexo:
        raise HTTPException(404, "Anexo não encontrado.")
    return resposta_arquivo(anexo.arquivo, anexo.nome)
