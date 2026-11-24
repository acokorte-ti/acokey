"""Matéria-prima: corridas recebidas, certificados, carimbo de aprovação, criar e vincular lotes.

Regras do sistema antigo (legado/app.py, seção "MATÉRIA-PRIMA", e legado/CLAUDE.md 7.4):
- Saldo = QT-OK menos os corpos de prova (QT-CP-T.T., usados em ensaios) menos o que os lotes da corrida já usaram.
- Uma corrida pode alimentar várias OPs (nunca o contrário).
- "Carimbar e aprovar": carimbo APROVADO + assinatura em todas as páginas do certificado, a corrida fica aprovada e o
  PDF carimbado vai para a etapa Receb. MP de todos os lotes da corrida.
- O lote criado a partir da corrida já recebe os certificados na etapa Receb. MP.

O que mudou em relação ao antigo:
- Nada é apagado: a corrida é cancelada (com motivo) e o anexo é removido (com motivo), o arquivo fica.
- Quem lança, aprova e carimba é sempre o usuário logado (o antigo aceitava um nome digitado).
- Aprovar, reprovar, carimbar e reabrir exigem "pode aprovar"; cancelar exige "pode aprovar" ou administrador
  (no antigo era a senha administrativa compartilhada).
- O lote se liga à corrida pelo id da matéria-prima. O texto da corrida só vale para lotes antigos sem esse vínculo.
"""
import logging
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import Session

from app import arquivos, fluxo, mega
from app.arquivos import DOCUMENTOS, resposta_arquivo, salvar_upload
from app.carimbo import ErroCarimbo, carimbar_pdf
from app.config import agora_local
from app.db import get_db
from app.estado import estado_lotes
from app.historico import registrar_evento
from app.lotes import buscar_lote, criar_lote
from app.models import TIPOS_LOTE, Anexo, FornecedorMP, Lote, MateriaPrima, MateriaPrimaAnexo, OrdemProducao
from app.pdf_comum import caminho_assinatura
from app.seguranca import APROVADOR, QUALIDADE, QUALQUER, Contexto, auditar, diferencas, limpar_texto

rota = APIRouter()

MARCA_CARIMBO = "_APROVADO"  # sufixo do nome do PDF carimbado (o mesmo do sistema antigo)
QUANTIDADES = ("qt_fund", "qt_real", "qt_ok", "qt_rej", "qt_retrab", "qt_cp_tt")
_PREFIXO_DESCRICAO = re.compile(r"INSTR\.?\s*CONTROLE\s*TRAVAMENTO\s*(?:DES\s+)?", re.IGNORECASE)


# ---------------------------------------------------------------- cálculos (iguais aos do sistema antigo)


def _pct(numerador: int, denominador: int) -> float:
    return round(numerador / denominador * 100, 1) if denominador else 0.0


def calcular(mp: MateriaPrima, consumida: int) -> dict:
    """Linha da corrida com percentuais, disponível e saldo (legado: _mp_calcular)."""
    disponivel = max(mp.qt_ok - mp.qt_cp_tt, 0)  # corpos de prova saem do total aprovado
    return {
        "id": mp.id,
        "nf_entrada": mp.nf_entrada,
        "corrida": mp.corrida,
        "fornecedor": mp.fornecedor,
        "tipo_destino": mp.tipo_destino,
        "data_recebimento": mp.data_recebimento,
        **{q: getattr(mp, q) for q in QUANTIDADES},
        "observacoes": mp.observacoes,
        "criado_em": mp.criado_em,
        "responsavel": mp.responsavel,
        "status": mp.status,
        "aprovado_por": mp.aprovado_por,
        "aprovado_em": mp.aprovado_em,
        "obs_aprovacao": mp.obs_aprovacao,
        "pct_refugo": _pct(mp.qt_rej, mp.qt_real),
        "pct_retrab": _pct(mp.qt_retrab, mp.qt_real),
        "pct_aprov": _pct(mp.qt_ok, mp.qt_real),
        "rendimento": _pct(mp.qt_ok, mp.qt_fund),
        "qt_disponivel": disponivel,
        "qt_consumida": consumida,
        "qt_saldo": max(disponivel - consumida, 0),
    }


def _chave_corrida(corrida: str | None) -> str:
    return (corrida or "").strip().lower()


class _LotesPorCorrida:
    """Lotes ativos agrupados pela matéria-prima (uma consulta só, para a lista inteira)."""

    def __init__(self, db: Session):
        self.por_id: dict[int, list[Lote]] = defaultdict(list)
        self.por_texto: dict[str, list[Lote]] = defaultdict(list)
        for lote in db.scalars(select(Lote).where(Lote.cancelado_em.is_(None)).order_by(Lote.id.desc())):
            if lote.materia_prima_id:
                self.por_id[lote.materia_prima_id].append(lote)
            elif _chave_corrida(lote.corrida):
                # Lote antigo sem vínculo pelo id: vale o texto da corrida, como no sistema antigo
                self.por_texto[_chave_corrida(lote.corrida)].append(lote)

    def de(self, mp: MateriaPrima) -> list[Lote]:
        texto = _chave_corrida(mp.corrida)
        return self.por_id.get(mp.id, []) + (self.por_texto.get(texto, []) if texto else [])


def lotes_da_corrida(db: Session, mp: MateriaPrima) -> list[Lote]:
    texto = _chave_corrida(mp.corrida)
    pelo_texto = Lote.materia_prima_id.is_(None) & (func.lower(func.trim(Lote.corrida)) == texto) if texto else false()
    consulta = select(Lote).where(Lote.cancelado_em.is_(None), or_(Lote.materia_prima_id == mp.id, pelo_texto))
    return list(db.scalars(consulta.order_by(Lote.id.desc())))


def _buscar(db: Session, mp_id: int) -> MateriaPrima:
    mp = db.get(MateriaPrima, mp_id)
    if not mp or mp.cancelado_em:
        raise HTTPException(404, "Corrida de matéria-prima não encontrada.")
    return mp


def _calculada(db: Session, mp: MateriaPrima) -> dict:
    return calcular(mp, sum(lote.qtd for lote in lotes_da_corrida(db, mp)))


def _carimbado(nome: str) -> bool:
    return MARCA_CARIMBO in (nome or "").upper()


def _nome_carimbado(nome: str) -> str:
    return Path(nome).stem + MARCA_CARIMBO + ".pdf"


def _anexos_ativos(db: Session, mp_id: int) -> list[MateriaPrimaAnexo]:
    consulta = select(MateriaPrimaAnexo).where(
        MateriaPrimaAnexo.materia_prima_id == mp_id, MateriaPrimaAnexo.removido_em.is_(None)
    )
    return list(db.scalars(consulta.order_by(MateriaPrimaAnexo.id.desc())))


def _anexo_dict(a: MateriaPrimaAnexo) -> dict:
    pdf = a.nome.lower().endswith(".pdf")
    return {"id": a.id, "nome": a.nome, "quando": a.quando, "pdf": pdf, "carimbado": _carimbado(a.nome)}


def descricao_curta(descricao: str) -> str:
    """'INSTR. CONTROLE TRAVAMENTO ARK 18-24 ...' -> 'ARK 18-24 ...' (legado: _produto_sem_instr)."""
    achado = _PREFIXO_DESCRICAO.search(descricao or "")
    return descricao[achado.end() :].strip() if achado else (descricao or "").strip()


# ---------------------------------------------------------------- entradas


class CorridaEntrada(BaseModel):
    nf_entrada: str = Field("", max_length=40)
    corrida: str = Field(max_length=60)
    fornecedor: str = Field("", max_length=160)
    tipo_destino: str = Field(max_length=3)
    data_recebimento: date | None = None
    qt_fund: int = Field(0, ge=0, le=10_000_000)
    qt_real: int = Field(0, ge=0, le=10_000_000)
    qt_ok: int = Field(0, ge=0, le=10_000_000)
    qt_rej: int = Field(0, ge=0, le=10_000_000)
    qt_retrab: int = Field(0, ge=0, le=10_000_000)
    qt_cp_tt: int = Field(0, ge=0, le=10_000_000)
    observacoes: str = Field("", max_length=4000)


class Motivo(BaseModel):
    motivo: str = Field(max_length=2000)


class Decisao(BaseModel):
    decisao: Literal["aprovada", "reprovada"]
    observacao: str = Field("", max_length=2000)


class LoteDaCorrida(BaseModel):
    op: str = Field(max_length=20)
    numero: str = Field(max_length=40)
    qtd: int = Field(ge=0, le=10_000_000)
    coditem: str = Field("", max_length=40)
    tipo: str | None = Field(None, max_length=3)


class Vinculo(BaseModel):
    lote_id: int


def _valores(dados: CorridaEntrada) -> dict:
    valores = {k: limpar_texto(v).strip() if isinstance(v, str) else v for k, v in dados.model_dump().items()}
    valores["tipo_destino"] = valores["tipo_destino"].upper()
    if not valores["corrida"]:
        raise HTTPException(422, "Informe a corrida.")
    if valores["tipo_destino"] not in TIPOS_LOTE:
        raise HTTPException(422, "Escolha o tipo destino: PIN, BOX ou ARK.")
    return valores


def _motivo(dados: Motivo, o_que: str = "o motivo") -> str:
    texto = limpar_texto(dados.motivo).strip()
    if len(texto) < 3:
        raise HTTPException(422, f"Escreva {o_que} (pelo menos 3 letras).")
    return texto


def _repetida(db: Session, valores: dict, exceto: int | None = None) -> MateriaPrima | None:
    """Mesma corrida com a mesma NF já lançada (evita o lançamento em dobro)."""
    consulta = select(MateriaPrima).where(
        MateriaPrima.cancelado_em.is_(None),
        func.lower(MateriaPrima.corrida) == valores["corrida"].lower(),
        func.lower(MateriaPrima.nf_entrada) == valores["nf_entrada"].lower(),
    )
    if exceto:
        consulta = consulta.where(MateriaPrima.id != exceto)
    return db.scalar(consulta.limit(1))


# ---------------------------------------------------------------- consulta


@rota.get("/materia-prima")
def listar(_: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> dict:
    mps = list(db.scalars(select(MateriaPrima).where(MateriaPrima.cancelado_em.is_(None)).order_by(MateriaPrima.id.desc())))
    lotes = _LotesPorCorrida(db)
    carimbadas = set(
        db.scalars(
            select(MateriaPrimaAnexo.materia_prima_id).where(
                MateriaPrimaAnexo.removido_em.is_(None), func.upper(MateriaPrimaAnexo.nome).like(f"%{MARCA_CARIMBO}%")
            )
        )
    )
    itens = []
    for mp in mps:
        usando = lotes.de(mp)
        item = calcular(mp, sum(lote.qtd for lote in usando))
        item["lotes_usando"] = len(usando)
        item["tem_carimbado"] = mp.id in carimbadas
        itens.append(item)
    return {"itens": itens, "fornecedores": _fornecedores_sugeridos(db, mps), "mega": mega.situacao()[0]}


def _fornecedores_sugeridos(db: Session, mps: list[MateriaPrima]) -> list[dict]:
    """Nomes já usados nas corridas e, depois, os fornecedores ativos do cadastro (sem repetir)."""
    vistos: set[str] = set()
    saida: list[dict] = []
    for nome in sorted({mp.fornecedor.strip() for mp in mps if mp.fornecedor.strip()}, key=str.lower):
        vistos.add(nome.lower())
        saida.append({"valor": nome, "rotulo": ""})
    for f in db.scalars(select(FornecedorMP).where(FornecedorMP.ativo).order_by(FornecedorMP.codigo)):
        if f.codigo.lower() not in vistos and f.razao_social.lower() not in vistos:
            vistos.add(f.codigo.lower())
            saida.append({"valor": f.codigo, "rotulo": f.razao_social})
    return saida


@rota.get("/materia-prima/opcoes")
def opcoes(tipo: str | None = None, _: Contexto = Depends(QUALQUER), db: Session = Depends(get_db)) -> list[dict]:
    """Corridas para escolher em outras telas (ex.: novo lote no painel). Qualquer usuário logado."""
    consulta = select(MateriaPrima).where(MateriaPrima.cancelado_em.is_(None), MateriaPrima.corrida != "")
    if tipo:
        consulta = consulta.where(MateriaPrima.tipo_destino == tipo.strip().upper())
    mps = list(db.scalars(consulta.order_by(MateriaPrima.id.desc())))
    lotes = _LotesPorCorrida(db)
    saida = []
    for mp in mps:
        c = calcular(mp, sum(lote.qtd for lote in lotes.de(mp)))
        saida.append({k: c[k] for k in ("id", "corrida", "nf_entrada", "fornecedor", "tipo_destino", "status", "qt_saldo")})
    return saida


@rota.get("/materia-prima/entradas-mega")
def entradas_mega(dias: int = 365, _: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> dict:
    """Entradas de peças fundidas no Mega (só leitura, na hora), com o que já foi lançado de cada uma. Ajuda a lançar
    a corrida: NF, fornecedor, data, tipo e quantidade vêm da nota; a corrida vem do certificado."""
    pronto, motivo = mega.situacao()
    if not pronto:
        raise HTTPException(409, motivo)
    desde = agora_local().date() - timedelta(days=max(1, min(dias, 3650)))
    try:
        entradas = mega.montar_entradas(mega.ler_entradas(desde))
    except Exception as erro:  # noqa: BLE001 — a falha vira mensagem na tela; o detalhe fica no log
        logging.getLogger("uvicorn.error").exception("Falha ao ler as entradas de matéria-prima no Mega")
        raise HTTPException(502, f"Não foi possível consultar o Mega: {mega.mensagem_para_tela(erro, 'falha na consulta')}") from None
    return {"desde": desde, "entradas": mega.entradas_para_tela(db, entradas)}


@rota.get("/materia-prima/{mp_id}")
def ver(mp_id: int, ctx: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> dict:
    mp = _buscar(db, mp_id)
    vinculados = lotes_da_corrida(db, mp)
    estados, _ultimos = estado_lotes(db, [lote.id for lote in vinculados])
    lotes = []
    for lote in vinculados:
        indice = fluxo.etapa_real(lote.tipo, estados.get(lote.id, {}))
        concluido = indice >= fluxo.CONCLUIDO
        lotes.append({
            "id": lote.id, "numero": lote.numero, "op": lote.op, "tipo": lote.tipo, "qtd": lote.qtd,
            "criado_em": lote.criado_em, "concluido": concluido,
            "etapa": None if concluido else fluxo.ETAPAS[indice].curto_de(lote.tipo),
        })  # fmt: skip

    ids_vinculados = {lote.id for lote in vinculados}
    vinculaveis = []
    if mp.tipo_destino:
        consulta = select(Lote).where(Lote.cancelado_em.is_(None), Lote.tipo == mp.tipo_destino).order_by(Lote.id.desc())
        for lote in db.scalars(consulta):
            if lote.id not in ids_vinculados:
                vinculaveis.append({"id": lote.id, "numero": lote.numero, "op": lote.op, "qtd": lote.qtd, "corrida": lote.corrida})

    consulta_ops = select(OrdemProducao).order_by(OrdemProducao.op.desc())
    if mp.tipo_destino:
        consulta_ops = consulta_ops.where(OrdemProducao.tipo == mp.tipo_destino)
    ops = [
        {"op": o.op, "coditem": o.coditem, "descricao": descricao_curta(o.descricao), "qt_lote": o.qt_lote}
        for o in db.scalars(consulta_ops)
    ]
    return {
        "corrida": calcular(mp, sum(lote.qtd for lote in vinculados)),
        "anexos": [_anexo_dict(a) for a in _anexos_ativos(db, mp.id)],
        "lotes": lotes,
        "vinculaveis": vinculaveis,
        "ops": ops,
        "tenho_assinatura": caminho_assinatura(ctx.usuario) is not None,
        "fornecedores": _fornecedores_sugeridos(db, list(db.scalars(select(MateriaPrima).where(MateriaPrima.cancelado_em.is_(None))))),
    }


# ---------------------------------------------------------------- lançar, editar, cancelar


@rota.post("/materia-prima", status_code=201)
def lancar(dados: CorridaEntrada, ctx: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> dict:
    valores = _valores(dados)
    if not valores["nf_entrada"]:
        raise HTTPException(422, "Informe a NF de entrada.")
    if _repetida(db, valores):
        raise HTTPException(409, f"A corrida {valores['corrida']} da NF {valores['nf_entrada']} já foi lançada.")
    mp = MateriaPrima(**valores, criado_em=agora_local(), responsavel=ctx.usuario.nome, status="pendente")
    db.add(mp)
    db.flush()
    auditar(db, ctx, "CRIAR", "materia_prima", mp.id, valores)
    db.commit()
    return {"id": mp.id, "mensagem": f"Corrida {mp.corrida} lançada."}


@rota.put("/materia-prima/{mp_id}")
def editar(mp_id: int, dados: CorridaEntrada, ctx: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> dict:
    mp = _buscar(db, mp_id)
    valores = _valores(dados)
    if _repetida(db, valores, exceto=mp.id):
        raise HTTPException(409, f"Já existe outra corrida {valores['corrida']} lançada com a NF {valores['nf_entrada']}.")
    vinculados = lotes_da_corrida(db, mp)
    outro_tipo = sorted({lote.tipo for lote in vinculados if lote.tipo != valores["tipo_destino"]})
    if outro_tipo:
        raise HTTPException(409, f"Há lotes {', '.join(outro_tipo)} usando esta corrida: o tipo destino não pode mudar.")
    antes = {k: getattr(mp, k) for k in valores}
    mudou = diferencas(antes, valores)
    if not mudou:
        return {"id": mp.id, "mensagem": "Nada foi alterado."}
    corrida_antiga = mp.corrida
    for campo, valor in valores.items():
        setattr(mp, campo, valor)
    auditar(db, ctx, "ALTERAR", "materia_prima", mp.id, mudou)
    if corrida_antiga != mp.corrida:
        # O número da corrida foi corrigido: os lotes ligados a esta matéria-prima acompanham
        for lote in vinculados:
            if lote.materia_prima_id == mp.id and lote.corrida != mp.corrida:
                auditar(db, ctx, "ALTERAR", "lote", lote.id, {"corrida": [lote.corrida, mp.corrida]}, lote_id=lote.id)
                registrar_evento(db, lote.id, f"Corrida corrigida de {lote.corrida or '(vazia)'} para {mp.corrida} "
                                              "no cadastro da matéria-prima")  # fmt: skip
                lote.corrida = mp.corrida
    db.commit()
    return {"id": mp.id, "mensagem": "Corrida atualizada."}


@rota.post("/materia-prima/{mp_id}/cancelar")
def cancelar(mp_id: int, dados: Motivo, ctx: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> dict:
    if not (ctx.usuario.pode_aprovar or ctx.usuario.admin):
        raise HTTPException(403, "Só quem pode aprovar ou o administrador pode cancelar uma corrida.")
    mp = _buscar(db, mp_id)
    motivo = _motivo(dados, "o motivo do cancelamento")
    vinculados = lotes_da_corrida(db, mp)
    if vinculados:
        numeros = ", ".join(lote.numero for lote in vinculados[:5])
        raise HTTPException(409, f"Há {len(vinculados)} lote(s) usando esta corrida ({numeros}). Cancele ou corrija esses lotes antes.")
    mp.cancelado_em = agora_local()
    mp.cancelado_por = ctx.usuario.nome
    mp.cancelado_motivo = motivo
    auditar(db, ctx, "CANCELAR", "materia_prima", mp.id, {"corrida": mp.corrida, "nf_entrada": mp.nf_entrada, "motivo": motivo})
    db.commit()
    return {"mensagem": f"Corrida {mp.corrida} cancelada."}


# ---------------------------------------------------------------- certificados (anexos da corrida)


def _buscar_anexo(db: Session, anexo_id: int, mp_id: int | None = None) -> MateriaPrimaAnexo:
    anexo = db.get(MateriaPrimaAnexo, anexo_id)
    if not anexo or anexo.removido_em or (mp_id is not None and anexo.materia_prima_id != mp_id):
        raise HTTPException(404, "Anexo não encontrado.")
    return anexo


@rota.post("/materia-prima/{mp_id}/anexos", status_code=201)
def anexar(
    mp_id: int,
    arquivos_enviados: list[UploadFile] = File(..., alias="arquivos"),
    ctx: Contexto = Depends(QUALIDADE),
    db: Session = Depends(get_db),
) -> dict:
    mp = _buscar(db, mp_id)
    enviados = [a for a in arquivos_enviados if a.filename]
    if not enviados:
        raise HTTPException(422, "Escolha um ou mais arquivos.")
    agora = agora_local()
    nomes = []
    for enviado in enviados:
        relativo, original = salvar_upload(enviado, f"materia_prima/{mp.id}", DOCUMENTOS)
        db.add(MateriaPrimaAnexo(materia_prima_id=mp.id, nome=original[:255], arquivo=relativo, quando=agora))
        nomes.append(original)
    auditar(db, ctx, "ANEXAR", "materia_prima", mp.id, {"arquivos": nomes})
    db.commit()
    return {"mensagem": f"{len(nomes)} arquivo(s) anexado(s)."}


@rota.get("/materia-prima/anexos/{anexo_id}/arquivo")
def abrir_anexo(anexo_id: int, _: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> FileResponse:
    anexo = db.get(MateriaPrimaAnexo, anexo_id)  # removido também abre: o arquivo continua guardado
    if not anexo:
        raise HTTPException(404, "Anexo não encontrado.")
    return resposta_arquivo(anexo.arquivo, anexo.nome)


@rota.post("/materia-prima/anexos/{anexo_id}/remover")
def remover_anexo(anexo_id: int, dados: Motivo, ctx: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> dict:
    anexo = _buscar_anexo(db, anexo_id)
    _buscar(db, anexo.materia_prima_id)
    motivo = _motivo(dados)
    anexo.removido_em = agora_local()
    anexo.removido_por = ctx.usuario.nome
    anexo.removido_motivo = motivo
    auditar(db, ctx, "REMOVER", "anexo_mp", anexo.id, {"materia_prima_id": anexo.materia_prima_id, "nome": anexo.nome, "motivo": motivo})
    db.commit()
    return {"mensagem": f"Anexo {anexo.nome} removido."}


# ---------------------------------------------------------------- decisão da Qualidade


@rota.post("/materia-prima/{mp_id}/decisao")
def decidir(mp_id: int, dados: Decisao, ctx: Contexto = Depends(APROVADOR), db: Session = Depends(get_db)) -> dict:
    mp = _buscar(db, mp_id)
    if mp.status != "pendente":
        raise HTTPException(409, f"A corrida já está {mp.status}. Para mudar a decisão, reabra antes.")
    observacao = limpar_texto(dados.observacao).strip()
    if dados.decisao == "reprovada" and len(observacao) < 3:
        raise HTTPException(422, "Informe o motivo da reprovação.")
    mp.status = dados.decisao
    mp.aprovado_por = ctx.usuario.nome
    mp.aprovado_em = agora_local()
    mp.obs_aprovacao = observacao
    acao = "APROVAR" if dados.decisao == "aprovada" else "REPROVAR"
    auditar(db, ctx, acao, "materia_prima", mp.id, {"corrida": mp.corrida, "status": ["pendente", mp.status], "observacao": observacao})
    db.commit()
    return {"mensagem": f"Corrida {mp.corrida} {mp.status}."}


@rota.post("/materia-prima/{mp_id}/reabrir")
def reabrir(mp_id: int, dados: Motivo, ctx: Contexto = Depends(APROVADOR), db: Session = Depends(get_db)) -> dict:
    mp = _buscar(db, mp_id)
    if mp.status == "pendente":
        raise HTTPException(409, "A corrida já está pendente de decisão.")
    motivo = _motivo(dados, "o motivo para reabrir")
    antes = {"status": mp.status, "aprovado_por": mp.aprovado_por, "aprovado_em": mp.aprovado_em, "obs_aprovacao": mp.obs_aprovacao}
    mp.status, mp.aprovado_por, mp.aprovado_em, mp.obs_aprovacao = "pendente", "", None, ""
    auditar(db, ctx, "REABRIR", "materia_prima", mp.id, {"corrida": mp.corrida, "antes": antes, "motivo": motivo})
    db.commit()
    return {"mensagem": "Decisão reaberta: a corrida voltou a ficar pendente de aprovação."}


@rota.post("/materia-prima/{mp_id}/anexos/{anexo_id}/carimbar")
def carimbar(mp_id: int, anexo_id: int, ctx: Contexto = Depends(APROVADOR), db: Session = Depends(get_db)) -> dict:
    """Gera a versão carimbada APROVADO do certificado, aprova a corrida e leva o PDF aos lotes dela."""
    mp = _buscar(db, mp_id)
    anexo = _buscar_anexo(db, anexo_id, mp.id)
    if not anexo.nome.lower().endswith(".pdf"):
        raise HTTPException(422, "Só dá para carimbar arquivos PDF.")
    if _carimbado(anexo.nome):
        raise HTTPException(422, "Este arquivo já é a versão carimbada. Para refazer, carimbe o certificado original.")
    if mp.status == "reprovada":
        raise HTTPException(409, "A corrida está reprovada. Reabra a decisão antes de carimbar o certificado.")
    assinatura = caminho_assinatura(ctx.usuario)
    if not assinatura:
        raise HTTPException(
            422, "Você ainda não tem assinatura digital cadastrada. Peça ao administrador para cadastrá-la em Usuários e carimbe depois."
        )
    origem = arquivos.caminho_seguro(anexo.arquivo)
    if not origem:
        raise HTTPException(404, "O arquivo original não foi encontrado no servidor.")
    try:
        carimbado = carimbar_pdf(origem.read_bytes(), ctx.usuario.nome, assinatura)
    except ErroCarimbo as erro:
        raise HTTPException(422, str(erro)) from None

    agora = agora_local()
    novo_nome = _nome_carimbado(anexo.nome)
    # Carimbo refeito: a versão carimbada anterior do mesmo certificado sai da lista (o arquivo fica)
    for anterior in _anexos_ativos(db, mp.id):
        if anterior.nome == novo_nome:
            anterior.removido_em, anterior.removido_por = agora, ctx.usuario.nome
            anterior.removido_motivo = "Substituído por um novo carimbo do mesmo certificado"
    novo = MateriaPrimaAnexo(
        materia_prima_id=mp.id, nome=novo_nome, quando=agora,
        arquivo=arquivos.salvar_bytes(carimbado, f"materia_prima/{mp.id}", novo_nome),
    )  # fmt: skip
    db.add(novo)
    db.flush()

    # Leva o PDF carimbado para a etapa Receb. MP de todos os lotes da corrida, no lugar do certificado sem carimbo
    lotes_atualizados = []
    for lote in lotes_da_corrida(db, mp):
        substituidos = list(
            db.scalars(
                select(Anexo).where(
                    Anexo.lote_id == lote.id, Anexo.etapa == "receb_mp", Anexo.removido_em.is_(None),
                    Anexo.apenas_registro.is_(False), Anexo.nome.in_([anexo.nome, novo_nome]),
                )  # fmt: skip
            )
        )
        for antigo in substituidos:
            antigo.removido_em, antigo.removido_por = agora, ctx.usuario.nome
            antigo.removido_motivo = f"Substituído pelo certificado carimbado APROVADO da corrida {mp.corrida}"
        db.add(Anexo(lote_id=lote.id, etapa="receb_mp", sub="", nome=novo_nome, quando=agora, apenas_registro=False,
                     arquivo=arquivos.salvar_bytes(carimbado, f"lotes/{lote.id}/anexos", novo_nome)))  # fmt: skip
        registrar_evento(db, lote.id, f"Certificado APROVADO da corrida {mp.corrida} propagado para Receb. MP")
        auditar(db, ctx, "ANEXAR", "anexo", None,
                {"etapa": "receb_mp", "nome": novo_nome, "origem": f"carimbo da corrida {mp.corrida}",
                 "substituidos": [a.nome for a in substituidos]}, lote_id=lote.id)  # fmt: skip
        lotes_atualizados.append(lote.numero)

    # Carimbar = aprovar a corrida, se ainda estava pendente (decisão já tomada não é sobrescrita)
    aprovou = mp.status == "pendente"
    if aprovou:
        mp.status, mp.aprovado_por, mp.aprovado_em = "aprovada", ctx.usuario.nome, agora
        mp.obs_aprovacao = f"Aprovada ao carimbar o certificado '{anexo.nome}'."
        auditar(db, ctx, "APROVAR", "materia_prima", mp.id,
                {"corrida": mp.corrida, "status": ["pendente", "aprovada"], "motivo": "aprovada ao carimbar o certificado"})  # fmt: skip
    auditar(db, ctx, "CARIMBAR", "anexo_mp", anexo.id,
            {"materia_prima_id": mp.id, "certificado": anexo.nome, "novo_anexo_id": novo.id, "aprovador": ctx.usuario.nome,
             "corrida_aprovada": aprovou, "lotes": lotes_atualizados})  # fmt: skip
    db.commit()

    mensagem = f"Certificado carimbado como APROVADO e salvo como '{novo_nome}'."
    if aprovou:
        mensagem += f" Corrida {mp.corrida} marcada como APROVADA."
    if lotes_atualizados:
        mensagem += f" Levado para Receb. MP de {len(lotes_atualizados)} lote(s)."
    return {"anexo_id": novo.id, "nome": novo_nome, "corrida_aprovada": aprovou, "lotes_atualizados": len(lotes_atualizados),
            "mensagem": mensagem}  # fmt: skip


# ---------------------------------------------------------------- lotes da corrida


def _certificados_para_lote(anexos: list[MateriaPrimaAnexo]) -> list[MateriaPrimaAnexo]:
    """Os anexos da corrida em ordem de envio; o original que já tem versão carimbada vai só como carimbado."""
    nomes = {a.nome for a in anexos}
    em_ordem = sorted(anexos, key=lambda a: a.id)
    return [a for a in em_ordem if _carimbado(a.nome) or _nome_carimbado(a.nome) not in nomes]


@rota.post("/materia-prima/{mp_id}/lotes", status_code=201)
def criar_lote_da_corrida(mp_id: int, dados: LoteDaCorrida, ctx: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> dict:
    mp = _buscar(db, mp_id)
    corrida = _calculada(db, mp)
    if dados.qtd <= 0:
        raise HTTPException(422, "Informe uma quantidade válida.")
    if not limpar_texto(dados.op).strip() or not limpar_texto(dados.numero).strip():
        raise HTTPException(422, "Informe a OP e o número do lote.")
    tipo = (dados.tipo or mp.tipo_destino or "").strip().upper()
    if mp.tipo_destino and tipo != mp.tipo_destino:
        raise HTTPException(422, f"Tipo do lote ({tipo}) diferente do destino da corrida ({mp.tipo_destino}). Operação bloqueada.")
    if dados.qtd > corrida["qt_saldo"]:
        raise HTTPException(
            422, f"Quantidade {dados.qtd} excede o saldo disponível da corrida ({corrida['qt_saldo']} pç). Operação bloqueada."
        )
    lote = criar_lote(
        db, ctx, op=dados.op, numero=dados.numero, tipo=tipo, qtd=dados.qtd, coditem=dados.coditem, corrida=mp.corrida,
        materia_prima_id=mp.id, texto_evento=f"Lote criado a partir da corrida {mp.corrida} (NF {mp.nf_entrada})",
    )  # fmt: skip
    # Os certificados já anexados na corrida entram direto na etapa Receb. MP do lote novo
    agora = agora_local()
    copiados, faltando = [], []
    for cert in _certificados_para_lote(_anexos_ativos(db, mp.id)):
        relativo = arquivos.copiar_arquivo(cert.arquivo, f"lotes/{lote.id}/anexos", arquivos.nome_seguro(cert.nome))
        if not relativo:
            faltando.append(cert.nome)
            continue
        db.add(Anexo(lote_id=lote.id, etapa="receb_mp", sub="", nome=cert.nome, arquivo=relativo, quando=agora, apenas_registro=False))
        copiados.append(cert.nome)
    if copiados:
        registrar_evento(db, lote.id, f"{len(copiados)} certificado(s) da corrida {mp.corrida} anexado(s) automaticamente em Receb. MP")
        auditar(db, ctx, "ANEXAR", "anexo", None, {"etapa": "receb_mp", "arquivos": copiados, "origem": f"corrida {mp.corrida}"},
                lote_id=lote.id)  # fmt: skip
    db.commit()

    mensagem = f"Lote {lote.numero} criado e vinculado à corrida {mp.corrida}"
    if copiados:
        mensagem += f" ({len(copiados)} certificado(s) já anexado(s) em Receb. MP)"
    mensagem += "."
    if mp.status == "pendente":
        mensagem += f" Atenção: a corrida {mp.corrida} ainda está pendente de aprovação."
    if faltando:
        mensagem += f" {len(faltando)} certificado(s) não foram encontrados no servidor e não foram copiados."
    return {"lote_id": lote.id, "numero": lote.numero, "certificados": len(copiados), "mensagem": mensagem}


@rota.post("/materia-prima/{mp_id}/vincular")
def vincular_lote(mp_id: int, dados: Vinculo, ctx: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> dict:
    """Liga um lote que já existe a esta corrida (troca a corrida do lote, se ele tinha outra)."""
    mp = _buscar(db, mp_id)
    lote = buscar_lote(db, dados.lote_id)
    if lote.materia_prima_id == mp.id:
        raise HTTPException(409, f"O lote {lote.numero} já está vinculado a esta corrida.")
    if mp.tipo_destino and lote.tipo != mp.tipo_destino:
        raise HTTPException(422, f"Tipo do lote ({lote.tipo}) diferente do destino da corrida ({mp.tipo_destino}). Operação bloqueada.")
    corrida = _calculada(db, mp)
    # Lote antigo que já usava esta corrida pelo texto não conta como consumo novo
    ja_contava = lote.materia_prima_id is None and _chave_corrida(lote.corrida) == _chave_corrida(mp.corrida)
    if not ja_contava and lote.qtd > corrida["qt_saldo"]:
        raise HTTPException(
            422, f"Quantidade do lote ({lote.qtd}) excede o saldo disponível da corrida ({corrida['qt_saldo']} pç). Operação bloqueada."
        )
    antes = {"corrida": lote.corrida, "materia_prima_id": lote.materia_prima_id}
    lote.corrida, lote.materia_prima_id = mp.corrida, mp.id
    registrar_evento(db, lote.id, f"Lote vinculado à corrida {mp.corrida} (NF {mp.nf_entrada})")
    auditar(db, ctx, "ALTERAR", "lote", lote.id, diferencas(antes, {"corrida": lote.corrida, "materia_prima_id": mp.id}),
            lote_id=lote.id)  # fmt: skip
    db.commit()
    return {"mensagem": f"Lote {lote.numero} (OP {lote.op}) vinculado à corrida {mp.corrida}."}
