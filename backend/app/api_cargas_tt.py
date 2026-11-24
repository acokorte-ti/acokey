"""Cargas de tratamento térmico: lotes que entram juntos no forno (legado/app.py, /cargas-tt).

Regras do sistema antigo:
- Um lote pode estar em várias cargas (têmpera numa, revenimento noutra). PIN e BOX podem ir juntos; ARK separado é
  recomendação (o sistema avisa, não bloqueia).
- Só entram na carga lotes que estão aguardando o tratamento térmico (os que já estavam na carga continuam).
- Situação: planejada -> em andamento -> concluída; planejada ou em andamento -> cancelada. Gerar o relatório de TT
  a partir da carga (api_relatorios) conclui a carga e replica o PDF em todos os lotes dela.
Diferenças:
- Nada é apagado: "Excluir" virou "Cancelar", com motivo escrito.
- O número (TT-AAAA-NNN) é sempre gerado pelo sistema na hora de gravar (o antigo deixava digitar e fazia
  "último + 1", que repetia número com duas pessoas ao mesmo tempo).
"""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import fluxo, parametros
from app.config import agora_local
from app.db import get_db
from app.estado import estado_lotes, ultimos_registros
from app.historico import registrar_evento
from app.lotes import buscar_lote
from app.models import Anexo, CargaTT, CargaTTLote, Equipamento, Lote, Sequencia
from app.numeracao import proximo_numero
from app.relatorios_dados import cadastros_op, cliente_da_op, equipamento, equipamento_dict, fornos
from app.seguranca import Contexto, auditar, diferencas, exigir, limpar_texto

rota = APIRouter()

TT = exigir("producao_tt", "qualidade")
ROTULO_STATUS = {"planejada": "planejada", "em_andamento": "em andamento", "concluida": "concluída", "cancelada": "cancelada"}
ABAS = {"ativas": ("planejada", "em_andamento"), "concluidas": ("concluida",), "canceladas": ("cancelada",)}
INDICE_TT = fluxo.INDICE["trat_termico"]


class CargaEntrada(BaseModel):
    forno_tempera_codigo: str = Field("", max_length=30)
    forno_revenimento_codigo: str = Field("", max_length=30)
    data_planejada: date | None = None
    observacoes: str = Field("", max_length=4000)
    lote_ids: list[int] = Field(default_factory=list, max_length=200)


class StatusEntrada(BaseModel):
    status: Literal["em_andamento", "concluida", "cancelada"]
    motivo: str = Field("", max_length=2000)


# ---------------------------------------------------------------- consultas usadas também por outros módulos


def lotes_das_cargas(db: Session, carga_ids: list[int]) -> dict[int, list[Lote]]:
    """{carga_id: [lotes na ordem da carga]}"""
    saida: dict[int, list[Lote]] = {i: [] for i in carga_ids}
    if not carga_ids:
        return saida
    consulta = (
        select(CargaTTLote.carga_id, Lote)
        .join(Lote, Lote.id == CargaTTLote.lote_id)
        .where(CargaTTLote.carga_id.in_(carga_ids))
        .order_by(CargaTTLote.ordem, CargaTTLote.id)
    )
    for carga_id, lote in db.execute(consulta):
        saida[carga_id].append(lote)
    return saida


def carga_ativa_do_lote(db: Session, lote_id: int) -> CargaTT | None:
    """Última carga não cancelada que inclui o lote (o antigo usava no selo da página do lote e no RIP-35)."""
    return db.scalar(
        select(CargaTT)
        .join(CargaTTLote, CargaTTLote.carga_id == CargaTT.id)
        .where(CargaTTLote.lote_id == lote_id, CargaTT.status != "cancelada")
        .order_by(CargaTT.id.desc())
    )


def _quantas_cargas(db: Session, lote_ids: list[int]) -> dict[int, int]:
    if not lote_ids:
        return {}
    consulta = (
        select(CargaTTLote.lote_id, func.count())
        .join(CargaTT, CargaTT.id == CargaTTLote.carga_id)
        .where(CargaTTLote.lote_id.in_(lote_ids), CargaTT.status != "cancelada")
        .group_by(CargaTTLote.lote_id)
    )
    return dict(db.execute(consulta).all())


def aguardando_tt(db: Session, lotes: list[Lote]) -> set[int]:
    """Lotes cuja etapa verdadeira (pelos registros) é o tratamento térmico."""
    estados, _ = estado_lotes(db, [lo.id for lo in lotes])
    return {lo.id for lo in lotes if fluxo.etapa_real(lo.tipo, estados.get(lo.id, {})) == INDICE_TT}


def _lote_dict(db: Session, lote: Lote, cadastros: dict) -> dict:
    return {
        "id": lote.id,
        "numero": lote.numero,
        "op": lote.op,
        "tipo": lote.tipo,
        "qtd": lote.qtd,
        "corrida": lote.corrida,
        "cliente": cliente_da_op(db, cadastros.get(lote.op)).upper(),
    }


def _forno_desc(codigo: str, por_codigo: dict[str, Equipamento]) -> str:
    e = por_codigo.get(codigo)
    return (e.descricao if e else codigo) or "—"


def _resumo(db: Session, carga: CargaTT, lotes: list[Lote], por_codigo: dict[str, Equipamento]) -> dict:
    return {
        "id": carga.id,
        "numero": carga.numero,
        "status": carga.status,
        "data_planejada": carga.data_planejada,
        "data_inicio": carga.data_inicio,
        "data_fim": carga.data_fim,
        "forno_tempera_codigo": carga.forno_tempera_codigo,
        "forno_revenimento_codigo": carga.forno_revenimento_codigo,
        "forno_tempera_desc": _forno_desc(carga.forno_tempera_codigo, por_codigo),
        "forno_revenimento_desc": _forno_desc(carga.forno_revenimento_codigo, por_codigo),
        "observacoes": carga.observacoes,
        "criado_em": carga.criado_em,
        "criado_por": carga.criado_por,
        "cancelado_em": carga.cancelado_em,
        "cancelado_por": carga.cancelado_por,
        "cancelado_motivo": carga.cancelado_motivo,
        "n_lotes": len(lotes),
        "total_pecas": sum(lo.qtd or 0 for lo in lotes),
        "lotes": [{"id": lo.id, "numero": lo.numero, "op": lo.op, "tipo": lo.tipo, "qtd": lo.qtd} for lo in lotes],
    }


def _equipamentos_por_codigo(db: Session) -> dict[str, Equipamento]:
    return {e.codigo: e for e in db.scalars(select(Equipamento))}


def _buscar_carga(db: Session, carga_id: int) -> CargaTT:
    carga = db.get(CargaTT, carga_id)
    if not carga:
        raise HTTPException(404, "Carga de tratamento térmico não encontrada.")
    return carga


def previsao_numero(db: Session) -> str:
    """Próximo número provável, só para mostrar (o número de verdade é reservado ao gravar)."""
    ano = agora_local().year
    linha = db.get(Sequencia, ("TT", ano))
    if linha is not None:
        return f"TT-{ano}-{linha.ultimo + 1:03d}"
    maior = 0
    for numero in db.scalars(select(CargaTT.numero).where(CargaTT.numero.like(f"TT-{ano}-%"))):
        cauda = numero.rsplit("-", 1)[-1]
        maior = max(maior, int(cauda)) if cauda.isdigit() else maior
    return f"TT-{ano}-{maior + 1:03d}"


# ---------------------------------------------------------------- validação da entrada


def _validar(db: Session, dados: CargaEntrada, ja_na_carga: set[int], carga: CargaTT | None = None) -> tuple[list[Lote], str]:
    """Confere fornos e lotes. Devolve (lotes na ordem escolhida, aviso de mistura com ARK)."""
    for campo, rotulo in (("forno_tempera_codigo", "têmpera"), ("forno_revenimento_codigo", "revenimento")):
        codigo = getattr(dados, campo).strip()
        anterior = getattr(carga, campo) if carga else ""
        if codigo and codigo != anterior:
            e = equipamento(db, codigo)
            if not e or not e.ativo:
                raise HTTPException(422, f"O forno de {rotulo} '{codigo}' não está no cadastro de equipamentos.")
    ids = list(dict.fromkeys(dados.lote_ids))
    if not ids:
        raise HTTPException(422, "Selecione ao menos um lote para a carga.")
    lotes = {lo.id: lo for lo in db.scalars(select(Lote).where(Lote.id.in_(ids)))}
    faltando = [i for i in ids if i not in lotes or lotes[i].cancelado_em]
    if faltando:
        raise HTTPException(422, "Um dos lotes escolhidos não existe mais ou foi cancelado. Recarregue a tela.")
    novos = [lotes[i] for i in ids if i not in ja_na_carga]
    aguardando = aguardando_tt(db, novos)
    fora = [lo.numero for lo in novos if lo.id not in aguardando]
    if fora:
        raise HTTPException(422, f"O lote {', '.join(fora)} não está aguardando o tratamento térmico.")
    escolhidos = [lotes[i] for i in ids]
    tipos = {lo.tipo for lo in escolhidos}
    aviso = ""
    if "ARK" in tipos and tipos & {"PIN", "BOX"}:
        aviso = "Esta carga mistura ARK com PIN/BOX. O ARK tem ciclo e material diferentes: o recomendado é carga separada."
    return escolhidos, aviso


# ---------------------------------------------------------------- rotas


@rota.get("/cargas-tt")
def listar(aba: Literal["ativas", "concluidas", "canceladas"] = "ativas", _: Contexto = Depends(TT),
           db: Session = Depends(get_db)) -> dict:  # fmt: skip
    cargas = list(db.scalars(select(CargaTT).where(CargaTT.status.in_(ABAS[aba])).order_by(CargaTT.id.desc())))
    lotes = lotes_das_cargas(db, [c.id for c in cargas])
    por_codigo = _equipamentos_por_codigo(db)
    contagem = dict(db.execute(select(CargaTT.status, func.count()).group_by(CargaTT.status)).all())
    return {
        "itens": [_resumo(db, c, lotes[c.id], por_codigo) for c in cargas],
        "contagens": {nome: sum(contagem.get(s, 0) for s in status) for nome, status in ABAS.items()},
    }


@rota.get("/cargas-tt/formulario")
def formulario(carga_id: int | None = None, _: Contexto = Depends(TT), db: Session = Depends(get_db)) -> dict:
    """O que a tela de nova carga (ou de edição) precisa: fornos, padrões e lotes aguardando TT."""
    carga = _buscar_carga(db, carga_id) if carga_id else None
    # lote cancelado depois de entrar na carga não aparece mais (e sai da carga ao salvar a edição)
    atuais = [lo for lo in lotes_das_cargas(db, [carga.id])[carga.id] if not lo.cancelado_em] if carga else []
    candidatos = list(db.scalars(select(Lote).where(Lote.cancelado_em.is_(None)).order_by(Lote.op, Lote.id)))
    aguardando = aguardando_tt(db, candidatos)
    ids_atuais = {lo.id for lo in atuais}
    disponiveis = [lo for lo in candidatos if lo.id in aguardando or lo.id in ids_atuais]
    cadastros = cadastros_op(db, [lo.op for lo in disponiveis])
    em_cargas = _quantas_cargas(db, [lo.id for lo in disponiveis])
    tempera, revenimento = fornos(db)
    por_codigo = _equipamentos_por_codigo(db)
    return {
        "numero_previsto": carga.numero if carga else previsao_numero(db),
        "carga": _resumo(db, carga, atuais, por_codigo) if carga else None,
        "lote_ids": [lo.id for lo in atuais],
        "fornos_tempera": [equipamento_dict(e) for e in tempera],
        "fornos_revenimento": [equipamento_dict(e) for e in revenimento],
        "forno_tempera_padrao": (carga.forno_tempera_codigo if carga else "") or parametros.ler(db, "forno_tempera_padrao"),
        "forno_revenimento_padrao": (carga.forno_revenimento_codigo if carga else "")
        or parametros.ler(db, "forno_revenimento_padrao"),
        "disponiveis": [
            _lote_dict(db, lo, cadastros)
            | {"aguardando_tt": lo.id in aguardando, "em_cargas": em_cargas.get(lo.id, 0) - (1 if lo.id in ids_atuais else 0)}
            for lo in disponiveis
        ],
        "hoje": agora_local().date(),
    }


@rota.get("/cargas-tt/do-lote/{lote_id}")
def cargas_do_lote(lote_id: int, _: Contexto = Depends(exigir()), db: Session = Depends(get_db)) -> list[dict]:
    """Cargas em que o lote está (para a página do lote). Qualquer usuário logado consulta."""
    buscar_lote(db, lote_id, incluir_cancelado=True)
    cargas = list(
        db.scalars(
            select(CargaTT).join(CargaTTLote, CargaTTLote.carga_id == CargaTT.id)
            .where(CargaTTLote.lote_id == lote_id).order_by(CargaTT.id.desc())
        )
    )  # fmt: skip
    return [{"id": c.id, "numero": c.numero, "status": c.status, "data_planejada": c.data_planejada} for c in cargas]


@rota.post("/cargas-tt", status_code=201)
def criar(dados: CargaEntrada, ctx: Contexto = Depends(TT), db: Session = Depends(get_db)) -> dict:
    lotes, aviso = _validar(db, dados, set())
    agora = agora_local()
    carga = CargaTT(
        numero=proximo_numero(db, "TT"),
        forno_tempera_codigo=dados.forno_tempera_codigo.strip(),
        forno_revenimento_codigo=dados.forno_revenimento_codigo.strip(),
        data_planejada=dados.data_planejada,
        status="planejada",
        observacoes=limpar_texto(dados.observacoes).strip(),
        criado_em=agora,
        criado_por=ctx.usuario.nome,
    )
    db.add(carga)
    db.flush()
    for ordem, lote in enumerate(lotes, start=1):
        db.add(CargaTTLote(carga_id=carga.id, lote_id=lote.id, ordem=ordem))
        registrar_evento(db, lote.id, f"Lote incluído na carga de TT {carga.numero}")
    auditar(db, ctx, "CRIAR", "carga_tt", carga.id,
            {"numero": carga.numero, "forno_tempera": carga.forno_tempera_codigo,
             "forno_revenimento": carga.forno_revenimento_codigo, "data_planejada": carga.data_planejada,
             "lotes": [lo.numero for lo in lotes]})  # fmt: skip
    db.commit()
    return {"id": carga.id, "numero": carga.numero, "aviso": aviso,
            "mensagem": f"Carga {carga.numero} criada com {len(lotes)} lote(s)."}  # fmt: skip


@rota.get("/cargas-tt/{carga_id}")
def ver(carga_id: int, _: Contexto = Depends(TT), db: Session = Depends(get_db)) -> dict:
    carga = _buscar_carga(db, carga_id)
    lotes = lotes_das_cargas(db, [carga.id])[carga.id]
    cadastros = cadastros_op(db, [lo.op for lo in lotes])
    ultimos = ultimos_registros(db, [lo.id for lo in lotes])
    estados, _ = estado_lotes(db, [lo.id for lo in lotes])
    saida = _resumo(db, carga, lotes, _equipamentos_por_codigo(db))
    itens = []
    for lo in lotes:
        reg = ultimos.get((lo.id, "trat_termico", ""))
        indice = fluxo.etapa_real(lo.tipo, estados.get(lo.id, {}))
        itens.append(
            _lote_dict(db, lo, cadastros)
            | {
                "cancelado": lo.cancelado_em is not None,
                "tt_aprovado": bool(reg and reg.status == "aprovado"),
                "etapa_atual": fluxo.ETAPAS[indice].curto_de(lo.tipo) if indice < fluxo.CONCLUIDO else "Concluído",
            }
        )
    saida["lotes"] = itens
    anexo = db.get(Anexo, carga.relatorio_anexo_id) if carga.relatorio_anexo_id else None
    saida["relatorio"] = {"anexo_id": anexo.id, "nome": anexo.nome, "lote_id": anexo.lote_id} if anexo else None
    return saida


@rota.put("/cargas-tt/{carga_id}")
def editar(carga_id: int, dados: CargaEntrada, ctx: Contexto = Depends(TT), db: Session = Depends(get_db)) -> dict:
    """Edição em qualquer situação menos cancelada. Em carga concluída só ajusta o vínculo: não mexe nos anexos
    e registros já gerados nos lotes (para isso, gere o relatório de TT de novo a partir da carga)."""
    carga = _buscar_carga(db, carga_id)
    if carga.status == "cancelada":
        raise HTTPException(409, "Esta carga está cancelada e não pode mais ser alterada.")
    vinculos = {v.lote_id: v for v in db.scalars(select(CargaTTLote).where(CargaTTLote.carga_id == carga.id))}
    lotes, aviso = _validar(db, dados, set(vinculos), carga)
    novos_ids = [lo.id for lo in lotes]
    por_id = {lo.id: lo for lo in lotes}
    antes = {"forno_tempera_codigo": carga.forno_tempera_codigo, "forno_revenimento_codigo": carga.forno_revenimento_codigo,
             "data_planejada": carga.data_planejada, "observacoes": carga.observacoes}  # fmt: skip
    carga.forno_tempera_codigo = dados.forno_tempera_codigo.strip()
    carga.forno_revenimento_codigo = dados.forno_revenimento_codigo.strip()
    carga.data_planejada = dados.data_planejada
    carga.observacoes = limpar_texto(dados.observacoes).strip()

    removidos = [lid for lid in vinculos if lid not in por_id]
    adicionados = [lid for lid in novos_ids if lid not in vinculos]
    numeros_removidos = []
    for lid in removidos:
        lote = db.get(Lote, lid)
        numeros_removidos.append(lote.numero if lote else str(lid))
        # O vínculo sai da carga (fica na auditoria e na linha do tempo do lote); o lote não é tocado
        db.delete(vinculos[lid])
        registrar_evento(db, lid, f"Lote removido da carga de TT {carga.numero}")
    proxima = max((v.ordem for v in vinculos.values()), default=0)
    for lid in adicionados:
        proxima += 1
        db.add(CargaTTLote(carga_id=carga.id, lote_id=lid, ordem=proxima))
        registrar_evento(db, lid, f"Lote incluído na carga de TT {carga.numero}")
    depois = {"forno_tempera_codigo": carga.forno_tempera_codigo, "forno_revenimento_codigo": carga.forno_revenimento_codigo,
              "data_planejada": carga.data_planejada, "observacoes": carga.observacoes}  # fmt: skip
    detalhes = diferencas(antes, depois)
    if adicionados:
        detalhes["lotes_adicionados"] = [por_id[i].numero for i in adicionados]
    if removidos:
        detalhes["lotes_removidos"] = numeros_removidos
    auditar(db, ctx, "ALTERAR", "carga_tt", carga.id, detalhes | {"numero": carga.numero})
    db.commit()
    mensagem = f"Carga {carga.numero} atualizada."
    if adicionados or removidos:
        mensagem += f" (+{len(adicionados)}/-{len(removidos)} lotes)"
    return {"id": carga.id, "numero": carga.numero, "aviso": aviso, "mensagem": mensagem}


@rota.post("/cargas-tt/{carga_id}/status")
def mudar_status(carga_id: int, dados: StatusEntrada, ctx: Contexto = Depends(TT), db: Session = Depends(get_db)) -> dict:
    carga = _buscar_carga(db, carga_id)
    permitidos = {"em_andamento": {"planejada"}, "concluida": {"em_andamento"}, "cancelada": {"planejada", "em_andamento"}}
    if carga.status not in permitidos[dados.status]:
        raise HTTPException(
            409, f"Uma carga {ROTULO_STATUS[carga.status]} não pode passar para {ROTULO_STATUS[dados.status]}."
        )
    motivo = limpar_texto(dados.motivo).strip()
    if dados.status == "cancelada" and len(motivo) < 3:
        raise HTTPException(422, "Escreva o motivo do cancelamento.")
    antes = carga.status
    agora = agora_local()
    carga.status = dados.status
    if dados.status == "em_andamento" and not carga.data_inicio:
        carga.data_inicio = agora
    if dados.status == "concluida" and not carga.data_fim:
        carga.data_fim = agora
    if dados.status == "cancelada":
        carga.cancelado_em, carga.cancelado_por, carga.cancelado_motivo = agora, ctx.usuario.nome, motivo
    texto = f"Carga TT {carga.numero} → {ROTULO_STATUS[dados.status]}" + (f" (motivo: {motivo})" if motivo else "")
    for lote in lotes_das_cargas(db, [carga.id])[carga.id]:
        registrar_evento(db, lote.id, texto)
    acao = {"em_andamento": "INICIAR", "concluida": "CONCLUIR", "cancelada": "CANCELAR"}[dados.status]
    auditar(db, ctx, acao, "carga_tt", carga.id,
            {"numero": carga.numero, "status": [antes, carga.status], **({"motivo": motivo} if motivo else {})})  # fmt: skip
    db.commit()
    return {"id": carga.id, "status": carga.status, "mensagem": f"Carga {carga.numero} marcada como {ROTULO_STATUS[carga.status]}."}
