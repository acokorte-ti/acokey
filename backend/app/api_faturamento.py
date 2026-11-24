"""Ordem de faturamento (saída física dos lotes prontos).

Trazido do sistema antigo (legado/app.py, "ORDEM DE FATURAMENTO (OF)"; telas of_* de templates_html.py).
Documento INTERNO que consolida os lotes prontos para sair fisicamente da fábrica rumo ao cliente. Lote pronto =
todas as etapas aplicáveis resolvidas e nenhuma NC aberta ou em tratamento (não depende do databook: "Enviado-DB" é
o databook mandado ao cliente, outro fluxo).

Situações: rascunho → emitida (a Expedição pode preparar) → faturada (a NF saiu; a OF fica travada) | cancelada.

Diferenças em relação ao antigo:
- número OF-AAAA-NNN reservado sem duplicidade (numeracao.py);
- "Excluir" virou cancelar com motivo (nada é apagado); faturada e cancelada não mudam mais;
- emitir confere de novo se os lotes continuam prontos (uma NC pode ter aberto depois do rascunho);
- a correção do nº do lote na OF (sem senha administrativa, como combinado com a Qualidade) só acontece quando a
  pessoa muda o número na tela; antes, salvar a OF completava sozinho o número curto com ano e trimestre.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import fluxo, parametros
from app.config import agora_local
from app.db import get_db
from app.estado import estado_lotes
from app.expedicao import cadastro_ops, cliente_curto, descricao_curta, ler_peso, lote_com_qtd, lote_completo, numero_previsto
from app.fluxo import NC_EM_ABERTO
from app.historico import registrar_evento
from app.lotes import numero_em_uso
from app.models import Lote, NaoConformidade, OrdemFaturamento, OrdemFaturamentoLote, OrdemProducao
from app.numeracao import proximo_numero
from app.pdf_expedicao import pdf_of
from app.seguranca import Contexto, auditar, diferencas, exigir, limpar_texto

rota = APIRouter()
EXPEDICAO = exigir("qualidade", "producao_tt", "producao_usinagem")

ABAS = {"ativas": ("rascunho", "emitida"), "faturadas": ("faturada",), "canceladas": ("cancelada",)}
TRANSICOES = {
    "rascunho": ("emitida", "cancelada"),
    "emitida": ("faturada", "rascunho", "cancelada"),
    "faturada": (),
    "cancelada": (),
}
EDITAVEL = frozenset({"rascunho", "emitida"})
NOME_STATUS = {"rascunho": "em rascunho", "emitida": "emitida", "faturada": "faturada", "cancelada": "cancelada"}
CAMPOS = ("data_emissao", "cliente", "pedido_cliente", "piv", "nf_saida", "destinatario", "observacoes")
TAMANHOS = {"cliente": 160, "pedido_cliente": 60, "piv": 40, "nf_saida": 40, "destinatario": 300}


# ---------------------------------------------------------------- regras


def motivos_bloqueio(db: Session, lotes: list[Lote]) -> dict[int, list[str]]:
    """O que impede cada lote de entrar numa OF (lista vazia = pronto para faturar)."""
    if not lotes:
        return {}
    ids = [lote.id for lote in lotes]
    estados, _ = estado_lotes(db, ids)
    ncs = dict(
        db.execute(
            select(NaoConformidade.lote_id, func.count())
            .where(NaoConformidade.lote_id.in_(ids), NaoConformidade.status.in_(NC_EM_ABERTO))
            .group_by(NaoConformidade.lote_id)
        ).all()
    )
    saida = {}
    for lote in lotes:
        motivos = []
        if lote.cancelado_em is not None:
            motivos.append("lote cancelado")
        indice = fluxo.etapa_real(lote.tipo, estados.get(lote.id, {}))
        if indice < fluxo.CONCLUIDO:
            motivos.append(f"etapa pendente: {fluxo.ETAPAS[indice].curto_de(lote.tipo)}")
        if ncs.get(lote.id):
            motivos.append(f"{ncs[lote.id]} NC aberta(s)")
        saida[lote.id] = motivos
    return saida


def _buscar(db: Session, of_id: int) -> OrdemFaturamento:
    of = db.get(OrdemFaturamento, of_id)
    if not of:
        raise HTTPException(404, "Ordem de faturamento não encontrada.")
    return of


def _itens_das_ofs(db: Session, ids: list[int]) -> dict[int, list[tuple[OrdemFaturamentoLote, Lote]]]:
    saida: dict[int, list[tuple[OrdemFaturamentoLote, Lote]]] = {i: [] for i in ids}
    if not ids:
        return saida
    consulta = (
        select(OrdemFaturamentoLote, Lote)
        .join(Lote, Lote.id == OrdemFaturamentoLote.lote_id)
        .where(OrdemFaturamentoLote.ordem_faturamento_id.in_(ids))
        .order_by(OrdemFaturamentoLote.ordem, OrdemFaturamentoLote.id)
    )
    for item, lote in db.execute(consulta):
        saida[item.ordem_faturamento_id].append((item, lote))
    return saida


def _itens_detalhados(db: Session, of: OrdemFaturamento) -> list[dict]:
    itens = _itens_das_ofs(db, [of.id])[of.id]
    cad = cadastro_ops(db, [lote.op for _, lote in itens])
    linhas = []
    for item, lote in itens:
        op = cad.get((lote.op or "").strip())
        linhas.append({
            "lote_id": lote.id, "op": lote.op, "tipo": lote.tipo, "numero": lote.numero,
            "lote_completo": lote_completo(lote.numero, of.data_emissao),
            "lote_com_qtd": lote_com_qtd(lote.numero, lote.qtd, of.data_emissao),
            "coditem": lote.coditem or (op.coditem if op else ""), "descricao": descricao_curta(op.descricao if op else ""),
            "qtd": lote.qtd or 0, "qtd_faturada": item.qtd_faturada or 0, "volumes": item.volumes or 0,
            "peso_liq": float(item.peso_liq or 0), "peso_bruto": float(item.peso_bruto or 0),
        })  # fmt: skip
    return linhas


def _cliente_por_piv(db: Session, piv: str) -> str:
    """Cliente da primeira OP do cadastro com esse PIV (coluna "Pedido" da antiga planilha de OPs)."""
    piv = (piv or "").strip()
    if not piv:
        return ""
    consulta = select(OrdemProducao.cliente).where(OrdemProducao.piv == piv, OrdemProducao.cliente != "").order_by(OrdemProducao.id)
    return db.scalars(consulta.limit(1)).first() or ""


# ---------------------------------------------------------------- consulta


@rota.get("/faturamento/opcoes")
def opcoes(db: Session = Depends(get_db), _: Contexto = Depends(EXPEDICAO)) -> dict:
    return {
        "numero_previsto": numero_previsto(db, "OF"),
        "hoje": agora_local().date(),
        "cliente_exemplo": parametros.ler(db, "cliente_nome_curto"),
    }


@rota.get("/faturamento")
def listar(aba: str = Query("ativas"), db: Session = Depends(get_db), _: Contexto = Depends(EXPEDICAO)) -> dict:
    status = ABAS.get(aba, ABAS["ativas"])
    ofs = db.scalars(select(OrdemFaturamento).where(OrdemFaturamento.status.in_(status)).order_by(OrdemFaturamento.id.desc())).all()
    itens = _itens_das_ofs(db, [o.id for o in ofs])
    contagem = dict(db.execute(select(OrdemFaturamento.status, func.count()).group_by(OrdemFaturamento.status)).all())
    return {
        "itens": [
            {
                "id": o.id, "numero": o.numero, "status": o.status, "cliente": o.cliente, "pedido_cliente": o.pedido_cliente,
                "piv": o.piv, "data_emissao": o.data_emissao, "nf_saida": o.nf_saida, "n_lotes": len(itens[o.id]),
                "total_pecas": sum(i.qtd_faturada or 0 for i, _ in itens[o.id]),
                "total_volumes": sum(i.volumes or 0 for i, _ in itens[o.id]),
                "lotes": [{"id": lote.id, "op": lote.op, "tipo": lote.tipo, "numero": lote.numero} for _, lote in itens[o.id]],
            }
            for o in ofs
        ],
        "contagens": {nome: sum(contagem.get(s, 0) for s in lista) for nome, lista in ABAS.items()},
    }  # fmt: skip


@rota.get("/faturamento/lotes-disponiveis")
def lotes_disponiveis(of_id: int | None = Query(None), db: Session = Depends(get_db), _: Contexto = Depends(EXPEDICAO)) -> dict:
    """Todos os lotes ativos: os prontos para marcar e os bloqueados com o motivo (como no antigo).
    Na edição, os lotes que já estão na OF vêm sempre (mesmo que agora estejam bloqueados, para poder tirar)."""
    na_of: set[int] = set()
    if of_id:
        na_of = set(db.scalars(select(OrdemFaturamentoLote.lote_id).where(OrdemFaturamentoLote.ordem_faturamento_id == of_id)))
    lotes = db.scalars(select(Lote).where((Lote.cancelado_em.is_(None)) | (Lote.id.in_(na_of))).order_by(Lote.op, Lote.id)).all()
    motivos = motivos_bloqueio(db, lotes)
    consulta = (
        select(OrdemFaturamentoLote.lote_id)
        .join(OrdemFaturamento, OrdemFaturamento.id == OrdemFaturamentoLote.ordem_faturamento_id)
        .where(OrdemFaturamento.status.in_(("emitida", "faturada")))
    )
    if of_id:
        consulta = consulta.where(OrdemFaturamento.id != of_id)
    em_outra = set(db.scalars(consulta))
    cad = cadastro_ops(db, [lote.op for lote in lotes])
    padrao_cliente = parametros.ler(db, "cliente_nome_curto")
    hoje = agora_local().date()
    saida = []
    for lote in lotes:
        op = cad.get((lote.op or "").strip())
        saida.append({
            "id": lote.id, "op": lote.op, "tipo": lote.tipo, "numero": lote.numero, "qtd": lote.qtd or 0,
            "coditem": lote.coditem or (op.coditem if op else ""), "descricao": descricao_curta(op.descricao if op else ""),
            "cliente": cliente_curto(db, op.cliente if op else "", padrao_cliente),
            "piv": op.piv if op else "", "pedido_cliente": op.po if op else "",
            "lote_completo": lote_completo(lote.numero, hoje), "lote_com_qtd": lote_com_qtd(lote.numero, lote.qtd, hoje),
            "motivos": motivos[lote.id], "pronto": not motivos[lote.id], "ja_faturado": lote.id in em_outra,
        })  # fmt: skip
    return {"lotes": saida}


@rota.get("/faturamento/cliente-por-piv")
def cliente_por_piv(piv: str = Query(""), db: Session = Depends(get_db), _: Contexto = Depends(EXPEDICAO)) -> dict:
    return {"cliente": _cliente_por_piv(db, piv)}


@rota.get("/faturamento/{of_id}")
def detalhe(of_id: int, db: Session = Depends(get_db), _: Contexto = Depends(EXPEDICAO)) -> dict:
    of = _buscar(db, of_id)
    itens = _itens_detalhados(db, of)
    return {
        "id": of.id, "numero": of.numero, "status": of.status, "data_emissao": of.data_emissao, "cliente": of.cliente,
        "pedido_cliente": of.pedido_cliente, "piv": of.piv, "nf_saida": of.nf_saida, "destinatario": of.destinatario,
        "observacoes": of.observacoes, "criado_em": of.criado_em, "criado_por": of.criado_por,
        "cancelado_em": of.cancelado_em, "cancelado_por": of.cancelado_por, "cancelado_motivo": of.cancelado_motivo,
        "itens": itens,
        "totais": {
            "qtd": sum(i["qtd"] for i in itens), "qtd_faturada": sum(i["qtd_faturada"] for i in itens),
            "volumes": sum(i["volumes"] for i in itens), "peso_liq": round(sum(i["peso_liq"] for i in itens), 3),
            "peso_bruto": round(sum(i["peso_bruto"] for i in itens), 3),
        },
        "pode_editar": of.status in EDITAVEL,
        "proximos": list(TRANSICOES.get(of.status, ())),
    }  # fmt: skip


# ---------------------------------------------------------------- gravação


class ItemOF(BaseModel):
    lote_id: int
    qtd_faturada: int | None = None  # vazio = quantidade do lote
    volumes: int = 0
    peso_liq: float | str | None = None
    peso_bruto: float | str | None = None
    numero_corrigido: str | None = None  # só quando a pessoa corrigiu o nº do lote na tela


class OFEntrada(BaseModel):
    data_emissao: date | None = None
    cliente: str = ""
    pedido_cliente: str = ""
    piv: str = ""
    nf_saida: str = ""
    destinatario: str = ""
    observacoes: str = ""
    itens: list[ItemOF] = []


def _validar(db: Session, corpo: OFEntrada) -> tuple[dict, list[tuple[ItemOF, Lote]], dict[int, str]]:
    """Confere tudo ANTES de gravar qualquer coisa (inclusive as correções de nº de lote)."""
    vistos: set[int] = set()
    itens: list[tuple[ItemOF, Lote]] = []
    for item in corpo.itens:
        if item.lote_id in vistos:
            continue
        vistos.add(item.lote_id)
        lote = db.get(Lote, item.lote_id)
        if lote is None:
            raise HTTPException(422, f"O lote #{item.lote_id} não existe.")
        itens.append((item, lote))
    if not itens:
        raise HTTPException(422, "Selecione ao menos um lote pronto para faturar.")
    motivos = motivos_bloqueio(db, [lote for _, lote in itens])
    for _, lote in itens:
        if motivos[lote.id]:
            raise HTTPException(422, f"O lote {lote.numero} ainda não está pronto: {'; '.join(motivos[lote.id])}.")
    correcoes: dict[int, str] = {}
    for item, lote in itens:
        if item.qtd_faturada is not None and item.qtd_faturada < 0:
            raise HTTPException(422, f"A quantidade liberada do lote {lote.numero} não pode ser negativa.")
        if item.volumes < 0:
            raise HTTPException(422, f"Os volumes do lote {lote.numero} não podem ser negativos.")
        if max(item.qtd_faturada or 0, item.volumes) > 1_000_000:
            raise HTTPException(422, f"Quantidade grande demais no lote {lote.numero}.")
        item.peso_liq = str(ler_peso(item.peso_liq, lote.numero))
        item.peso_bruto = str(ler_peso(item.peso_bruto, lote.numero))
        novo = limpar_texto(item.numero_corrigido or "").strip()
        if not novo or novo == lote.numero:
            continue
        if len(novo) > 40:
            raise HTTPException(422, f"O nº do lote '{novo}' é longo demais.")
        if numero_em_uso(db, novo, exceto_id=lote.id) or novo.lower() in {n.lower() for n in correcoes.values()}:
            raise HTTPException(409, f"Já existe outro lote com o número '{novo}'.")
        correcoes[lote.id] = novo
    campos = {"data_emissao": corpo.data_emissao or agora_local().date()}
    for chave in CAMPOS[1:]:
        texto = limpar_texto(getattr(corpo, chave) or "").strip()
        campos[chave] = texto[: TAMANHOS[chave]] if chave in TAMANHOS else texto
    return campos, itens, correcoes


def _corrigir_numeros(db: Session, ctx: Contexto, itens: list[tuple[ItemOF, Lote]], correcoes: dict[int, str], numero_of: str) -> None:
    """Correção rápida do nº do lote na tela da OF, sem senha administrativa (combinado com a Qualidade). Auditada."""
    for _, lote in itens:
        novo = correcoes.get(lote.id)
        if not novo:
            continue
        antigo = lote.numero
        lote.numero = novo
        registrar_evento(db, lote.id, f"Nº do lote corrigido de {antigo} para {novo} na ordem de faturamento {numero_of}")
        auditar(db, ctx, "ALTERAR", "lote", lote.id, {"numero": [antigo, novo], "motivo": f"Correção do nº do lote na OF {numero_of}"},
                lote_id=lote.id)  # fmt: skip


def _gravar_item(vinculo: OrdemFaturamentoLote, item: ItemOF, lote: Lote, ordem: int) -> None:
    vinculo.qtd_faturada = item.qtd_faturada if item.qtd_faturada is not None else (lote.qtd or 0)
    vinculo.volumes = item.volumes
    vinculo.peso_liq = item.peso_liq
    vinculo.peso_bruto = item.peso_bruto
    vinculo.ordem = ordem


def _quantidades(v: OrdemFaturamentoLote) -> dict:
    return {"qtd_faturada": v.qtd_faturada or 0, "volumes": v.volumes or 0, "peso_liq": str(ler_peso(v.peso_liq, "")),
            "peso_bruto": str(ler_peso(v.peso_bruto, ""))}  # fmt: skip


@rota.post("/faturamento", status_code=201)
def criar(corpo: OFEntrada, db: Session = Depends(get_db), ctx: Contexto = Depends(EXPEDICAO)) -> dict:
    campos, itens, correcoes = _validar(db, corpo)
    of = OrdemFaturamento(numero=proximo_numero(db, "OF"), status="rascunho", criado_em=agora_local(), criado_por=ctx.usuario.nome,
                          **campos)  # fmt: skip
    db.add(of)
    db.flush()
    _corrigir_numeros(db, ctx, itens, correcoes, of.numero)
    for ordem, (item, lote) in enumerate(itens, start=1):
        vinculo = OrdemFaturamentoLote(ordem_faturamento_id=of.id, lote_id=lote.id)
        _gravar_item(vinculo, item, lote, ordem)
        db.add(vinculo)
        registrar_evento(db, lote.id, f"Lote incluído na ordem de faturamento {of.numero} (rascunho)")
    auditar(db, ctx, "CRIAR", "ordem_faturamento", of.id,
            {"numero": of.numero, "cliente": of.cliente, "piv": of.piv, "lotes": [lote.numero for _, lote in itens]},
            lote_id=itens[0][1].id if len(itens) == 1 else None)  # fmt: skip
    db.commit()
    return {"id": of.id, "numero": of.numero}


@rota.put("/faturamento/{of_id}")
def editar(of_id: int, corpo: OFEntrada, db: Session = Depends(get_db), ctx: Contexto = Depends(EXPEDICAO)) -> dict:
    of = _buscar(db, of_id)
    if of.status not in EDITAVEL:
        raise HTTPException(409, f"Uma ordem {NOME_STATUS[of.status]} não pode mais ser alterada.")
    campos, itens, correcoes = _validar(db, corpo)
    atuais = {v.lote_id: v for v in db.scalars(select(OrdemFaturamentoLote).where(OrdemFaturamentoLote.ordem_faturamento_id == of.id))}
    numeros_antes = sorted(lote.numero for lote in (db.get(Lote, lid) for lid in atuais) if lote)
    quantidades_antes = {lid: _quantidades(v) for lid, v in atuais.items()}
    antes = {k: getattr(of, k) for k in CAMPOS}
    for chave, valor in campos.items():
        setattr(of, chave, valor)
    _corrigir_numeros(db, ctx, itens, correcoes, of.numero)
    novos_ids = {lote.id for _, lote in itens}
    for lid in set(atuais) - novos_ids:
        db.delete(atuais[lid])  # o vínculo sai da OF; a auditoria guarda o antes e o depois
        registrar_evento(db, lid, f"Lote retirado da ordem de faturamento {of.numero}")
    quantidades_depois = {}
    for ordem, (item, lote) in enumerate(itens, start=1):
        vinculo = atuais.get(lote.id)
        if vinculo is None:
            vinculo = OrdemFaturamentoLote(ordem_faturamento_id=of.id, lote_id=lote.id)
            db.add(vinculo)
            registrar_evento(db, lote.id, f"Lote incluído na ordem de faturamento {of.numero}")
        _gravar_item(vinculo, item, lote, ordem)
        quantidades_depois[lote.id] = _quantidades(vinculo)
    detalhes = diferencas(antes, {k: getattr(of, k) for k in CAMPOS})
    numeros_depois = sorted(lote.numero for _, lote in itens)
    if numeros_antes != numeros_depois:
        detalhes["lotes"] = [numeros_antes, numeros_depois]
    numero_do_lote = {lote.id: lote.numero for _, lote in itens}
    mudou = {
        numero_do_lote[lid]: [quantidades_antes.get(lid), q]
        for lid, q in quantidades_depois.items() if quantidades_antes.get(lid) != q
    }  # fmt: skip
    if mudou:
        detalhes["quantidades"] = mudou
    if detalhes:
        auditar(db, ctx, "ALTERAR", "ordem_faturamento", of.id, {"numero": of.numero, **detalhes},
                lote_id=itens[0][1].id if len(itens) == 1 else None)  # fmt: skip
    db.commit()
    return {"id": of.id, "numero": of.numero}


class MudancaStatus(BaseModel):
    status: str
    motivo: str = ""
    nf_saida: str | None = None  # ao marcar como faturada, a NF que saiu


@rota.post("/faturamento/{of_id}/status")
def mudar_status(of_id: int, corpo: MudancaStatus, db: Session = Depends(get_db), ctx: Contexto = Depends(EXPEDICAO)) -> dict:
    of = _buscar(db, of_id)
    novo = (corpo.status or "").strip()
    if novo not in TRANSICOES:
        raise HTTPException(422, "Situação inválida.")
    if novo not in TRANSICOES[of.status]:
        if of.status == "faturada":
            raise HTTPException(409, "A ordem já foi faturada e está travada. Não muda mais de situação.")
        raise HTTPException(409, f"Uma ordem {NOME_STATUS[of.status]} não pode passar para {NOME_STATUS[novo]}.")
    itens = _itens_das_ofs(db, [of.id])[of.id]
    if novo == "emitida":
        motivos = motivos_bloqueio(db, [lote for _, lote in itens])
        pendentes = [f"{lote.numero} ({'; '.join(motivos[lote.id])})" for _, lote in itens if motivos[lote.id]]
        if pendentes:
            raise HTTPException(
                409, "Não dá para emitir: lote(s) com pendência — " + ", ".join(pendentes) + ". Tire-os da OF ou resolva antes."
            )
        if not itens:
            raise HTTPException(409, "A ordem não tem nenhum lote.")
    antes = {"status": of.status, "nf_saida": of.nf_saida}
    motivo = limpar_texto(corpo.motivo or "").strip()
    if novo == "cancelada":
        if len(motivo) < 5:
            raise HTTPException(422, "Escreva o motivo do cancelamento (pelo menos 5 letras).")
        of.cancelado_em, of.cancelado_por, of.cancelado_motivo = agora_local(), ctx.usuario.nome, motivo
    if novo == "faturada" and corpo.nf_saida is not None:
        of.nf_saida = limpar_texto(corpo.nf_saida).strip()[:40]
    of.status = novo
    texto = {
        "emitida": f"Ordem de faturamento {of.numero} emitida",
        "rascunho": f"Ordem de faturamento {of.numero} voltou a rascunho",
        "faturada": f"Ordem de faturamento {of.numero} faturada" + (f" (NF {of.nf_saida})" if of.nf_saida else ""),
        "cancelada": f"Ordem de faturamento {of.numero} cancelada: {motivo}",
    }[novo]
    for _, lote in itens:
        registrar_evento(db, lote.id, texto)
    detalhes = {"numero": of.numero, **diferencas(antes, {"status": of.status, "nf_saida": of.nf_saida})}
    if motivo:
        detalhes["motivo"] = motivo
    auditar(db, ctx, "CANCELAR" if novo == "cancelada" else "STATUS", "ordem_faturamento", of.id, detalhes,
            lote_id=itens[0][1].id if len(itens) == 1 else None)  # fmt: skip
    db.commit()
    return {"id": of.id, "status": of.status}


@rota.get("/faturamento/{of_id}/pdf")
def pdf(of_id: int, db: Session = Depends(get_db), ctx: Contexto = Depends(EXPEDICAO)) -> Response:
    """Documento INTERNO (pode citar o cliente)."""
    of = _buscar(db, of_id)
    conteudo = pdf_of(db, of, _itens_detalhados(db, of))
    auditar(db, ctx, "GERAR_PDF", "ordem_faturamento", of.id, {"numero": of.numero})
    db.commit()
    return Response(conteudo, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{of.numero}.pdf"'})
