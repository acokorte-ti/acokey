"""Início, alertas, dashboard, Gantt, KPIs, indicadores, busca e exportações.

Regras e números trazidos de legado/app.py (home_pagina, painel, _calcular_pendencias, dashboard, gantt,
kpis_pagina, indicadores, api_buscar, exportar_painel_xlsx, auditoria_exportar). As contas ficam em
paineis.py e alertas.py; as planilhas em exportacoes.py.
"""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import alertas, exportacoes, fluxo, paineis, parametros
from app.config import FUSO, agora_local
from app.db import get_db
from app.models import TIPOS_LOTE, Auditoria, DatabookEnviado, Lote, MateriaPrima
from app.seguranca import AUDITORIA, QUALIDADE, QUALQUER, Contexto, auditar, exigir

rota = APIRouter()
KPIS = exigir("qualidade", "producao_tt")
LIMITE_BUSCA = 40
LIMITE_AUDITORIA = 50_000


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _datas_envio(db: Session, tipo: str | None = None) -> list[date | None]:
    # Envio desfeito não conta (a linha fica no banco, marcada em desfeito_em)
    consulta = select(DatabookEnviado.data_envio, DatabookEnviado.tipo).where(DatabookEnviado.desfeito_em.is_(None))
    return [d for d, t in db.execute(consulta) if tipo is None or (t or "").strip().upper() == tipo]


# ---------------------------------------------------------------- início


@rota.get("/inicio")
def inicio(ctx: Contexto = Depends(QUALQUER), db: Session = Depends(get_db)) -> dict:
    """Cartões por módulo, só os que o usuário pode abrir, com os números de hoje."""
    itens = paineis.retratos(db)
    andamento = [r for r in itens if not r.concluido]
    em_tt = sum(1 for r in andamento if r.etapa.chave == "trat_termico")
    inspecao = {"dureza", "dim_final", "lp", "visual"}  # etapas de inspeção da Qualidade
    aguardando = sum(1 for r in andamento if r.etapa.chave in inspecao)
    vencidas, vencendo = alertas.contar_calibracoes(db, agora_local().date())
    if vencidas:
        texto_equip = _plural(vencidas, "calibração vencida", "calibrações vencidas")
    elif vencendo:
        texto_equip = f"{_plural(vencendo, 'calibração', 'calibrações')} a vencer em {alertas.DIAS_CALIBRACAO} dias"
    else:
        texto_equip = "Calibrações em dia"

    cartoes = [
        # Produção aparece para todos: é o painel operacional
        {"chave": "producao", "nome": "Produção", "texto": f"{_plural(len(andamento), 'lote', 'lotes')} em andamento",
         "link": "/", "alerta": False, "mostrar": True},
        {"chave": "qualidade", "nome": "Qualidade", "texto": f"{aguardando} aguardando inspeção",
         "link": "/indicadores", "alerta": False, "mostrar": ctx.tem_modulo("qualidade")},
        {"chave": "tt", "nome": "Tratamento Térmico", "texto": f"{_plural(em_tt, 'lote', 'lotes')} em TT",
         "link": "/#etapa-trat_termico", "alerta": False, "mostrar": ctx.tem_modulo("qualidade", "producao_tt")},
        {"chave": "equipamentos", "nome": "Equipamentos", "texto": texto_equip,
         "link": "/equipamentos", "alerta": vencidas > 0, "mostrar": ctx.tem_modulo("qualidade", "cadastros")},
        {"chave": "cadastros", "nome": "Cadastros", "texto": "Fornecedores, prestadores, especificações",
         "link": "/especificacoes", "alerta": False, "mostrar": ctx.tem_modulo("cadastros")},
    ]  # fmt: skip
    return {
        "nome": ctx.usuario.nome,
        # Banner "Quer uma visita guiada?" até a pessoa responder (sim ou agora não)
        "mostrar_tutorial": ctx.usuario.tutorial_visto_em is None,
        "cartoes": [{k: v for k, v in c.items() if k != "mostrar"} for c in cartoes if c["mostrar"]],
    }


@rota.post("/inicio/tutorial-visto")
def tutorial_visto(ctx: Contexto = Depends(QUALQUER), db: Session = Depends(get_db)) -> dict:
    """Marca que o usuário já respondeu ao convite da visita guiada (não aparece mais)."""
    usuario = ctx.usuario
    if usuario.tutorial_visto_em is None:
        usuario.tutorial_visto_em = datetime.now(UTC)
        auditar(db, ctx, "ALTERAR", "usuario", usuario.id, {"tutorial_visto": [False, True]})
        db.commit()
    return {"ok": True, "tutorial_visto_em": usuario.tutorial_visto_em}


# ---------------------------------------------------------------- painel de lotes


@rota.get("/painel")
def painel(ctx: Contexto = Depends(QUALQUER), db: Session = Depends(get_db)) -> dict:
    """O que o painel mostra além do quadro: alertas, resumo, coluna Enviado-DB e lotes prontos para avançar."""
    itens = paineis.retratos(db)
    enviados = [r for r in itens if r.enviado]
    return {
        "pendencias": alertas.pendencias(db, ctx, itens),
        "resumo": {
            "total": len(itens),
            "andamento": sum(1 for r in itens if not r.concluido),
            "concluidos": sum(1 for r in itens if r.concluido and not r.enviado),
            "enviados": len(enviados),
            "nc": sum(1 for r in itens if r.nc),
        },
        "enviados": {
            "lote_ids": [r.lote.id for r in enviados],
            "pecas": paineis.soma_pecas(enviados),
            **{t.lower(): sum(1 for r in enviados if r.lote.tipo == t) for t in TIPOS_LOTE},
        },
        "prontos": [r.lote.id for r in itens if r.pronto],
    }


def _anexo(conteudo: bytes, nome: str) -> Response:
    return Response(conteudo, media_type=exportacoes.TIPO_XLSX, headers={"Content-Disposition": f'attachment; filename="{nome}"'})


@rota.get("/painel/exportar.xlsx")
def exportar_painel(_: Contexto = Depends(QUALQUER), db: Session = Depends(get_db)) -> Response:
    """Lista completa de lotes em Excel (para reunião gerencial). Documento interno."""
    agora = agora_local()
    wb = exportacoes.planilha_painel(paineis.retratos(db), paineis.cadastro_ops(db), parametros.ler(db, "cliente_nome_curto"), agora)
    return _anexo(exportacoes.em_bytes(wb), f"Painel_Lotes_{agora:%Y%m%d_%H%M}.xlsx")


# ---------------------------------------------------------------- dashboard


def _lote_dashboard(r: paineis.Retrato, descricao: str) -> dict:
    lote = r.lote
    return {
        "id": lote.id,
        "numero": lote.numero,
        "op": lote.op,
        "tipo": lote.tipo,
        "qtd": lote.qtd or 0,
        "coditem": lote.coditem,
        "descricao": descricao,
        "setor": r.setor,
        "etapa": r.etapa_curto,
        "dias": r.dias,
        "situacao": r.situacao,
        "nc": r.nc,
    }


def _ops_para_filtro(cadastro: dict) -> list[dict]:
    return [
        {"op": op, "tipo": o.tipo or "", "coditem": o.coditem, "descricao": paineis.descricao_curta(o.descricao)}
        for op, o in cadastro.items()
    ]


def _resumo_kpis(itens: list[paineis.Retrato], datas_envio: list[date | None]) -> dict:
    geral, por_tipo = paineis.funil(itens)
    return {
        "funil": geral,
        "funil_tipo": por_tipo,
        "setores": paineis.gargalos(itens),
        "linha_do_tempo": paineis.linha_do_tempo(datas_envio),
    }


@rota.get("/dashboard")
def dashboard(ctx: Contexto = Depends(QUALQUER), db: Session = Depends(get_db)) -> dict:
    """A fábrica em um relance: lotes agrupados por setor (bolhas), totais e tendência mês a mês."""
    itens = paineis.retratos(db)
    cadastro = paineis.cadastro_ops(db)
    datas_envio = _datas_envio(db)
    # Setores na ordem do processo; "Concluído" e "Enviado-DB" por último
    presentes = {r.setor for r in itens}
    setores = sorted(
        (s for s in presentes if s not in (paineis.CONCLUIDO, paineis.ENVIADO_DB)), key=lambda s: (paineis.ORDEM_SETOR.get(s, 99), s)
    ) + [s for s in (paineis.CONCLUIDO, paineis.ENVIADO_DB) if s in presentes]

    def descricao(op: str) -> str:
        o = cadastro.get(op.strip())
        return paineis.descricao_curta(o.descricao) if o else ""

    return {
        "setores": setores,
        "lotes": [_lote_dashboard(r, descricao(r.lote.op)) for r in itens],
        "totais": paineis.totais(itens),
        "tendencias": paineis.tendencias(itens, datas_envio),
        "maior_qtd": max((r.lote.qtd or 0 for r in itens), default=1) or 1,
        "ops": _ops_para_filtro(cadastro),
        # Os gráficos gerenciais só para quem vê os KPIs (Qualidade ou Produção TT), como no antigo
        "kpis": _resumo_kpis(itens, datas_envio) if ctx.tem_modulo("qualidade", "producao_tt") else None,
    }


# ---------------------------------------------------------------- Gantt


def _celulas(r: paineis.Retrato | None, tipo: str) -> list[dict]:
    """Uma célula por etapa: aprovada (com a data), reprovada, atual, pulada, futura, não iniciado ou não se aplica."""
    celulas = []
    for indice, etapa in enumerate(fluxo.ETAPAS):
        if not etapa.aplicavel(tipo):
            celulas.append({"s": "na", "rotulo": ""})
        elif r is None:
            celulas.append({"s": "nao_iniciado", "rotulo": ""})
        elif fluxo.etapa_resolvida(etapa, tipo, r.estado):
            registro = r.registros.get((etapa.chave, etapa.subs_de(tipo)[0]))
            quando = registro.quando if registro else None
            celulas.append({"s": "aprovada", "rotulo": quando.strftime("%d/%m/%Y") if quando else "Aprovada"})
        elif fluxo.nc_pendente_etapa(etapa, tipo, r.estado):
            celulas.append({"s": "reprovada", "rotulo": "Reprovada"})
        elif indice == r.indice:
            celulas.append({"s": "atual", "rotulo": "Em andamento"})
        elif indice < r.lote.etapa:  # o lote já foi passado adiante sem esta etapa resolvida
            celulas.append({"s": "pulada", "rotulo": "Pulada"})
        else:
            celulas.append({"s": "futura", "rotulo": ""})
    return celulas


@rota.get("/gantt")
def gantt(_: Contexto = Depends(QUALQUER), db: Session = Depends(get_db)) -> dict:
    """Linha do processo por OP: cada linha é uma OP do cadastro (com o último lote dela), cada coluna uma etapa."""
    itens = paineis.retratos(db)
    cadastro = paineis.cadastro_ops(db)
    ultimo_da_op: dict[str, paineis.Retrato] = {}
    for r in itens:  # em ordem de criação: o mais novo de cada OP fica
        ultimo_da_op[r.lote.op.strip()] = r
    # OPs do cadastro, na ordem dele, e depois as OPs que têm lote mas não estão no cadastro
    ops = list(cadastro) + [op for op in ultimo_da_op if op not in cadastro]

    linhas = []
    for op in ops:
        r = ultimo_da_op.get(op)
        cad = cadastro.get(op)
        tipo = r.lote.tipo if r else ((cad.tipo or "").strip().upper() if cad else "")
        if tipo not in TIPOS_LOTE:
            tipo = "PIN"  # OP sem classificação no cadastro: mostra a rota completa, como no antigo
        celulas = _celulas(r, tipo)
        aplicaveis = [c for c in celulas if c["s"] != "na"]
        aprovadas = sum(1 for c in aplicaveis if c["s"] == "aprovada")
        linhas.append(
            {
                "op": op,
                "tipo": tipo,
                "coditem": (r.lote.coditem if r and r.lote.coditem else (cad.coditem if cad else "")),
                "descricao": paineis.descricao_curta(cad.descricao) if cad else "",
                "qtd": (r.lote.qtd if r else (cad.qt_lote if cad else None)),
                "lote": {"id": r.lote.id, "numero": r.lote.numero} if r else None,
                "situacao": r.situacao if r else "semlote",
                "pct": int(aprovadas / len(aplicaveis) * 100) if aplicaveis else 0,
                "celulas": celulas,
            }
        )
    # Em andamento primeiro; depois concluídos sem envio, Enviados-DB e, no fim, OPs sem lote
    ordem = {"andamento": 0, "concluido": 1, "enviado": 2, "semlote": 3}
    linhas.sort(key=lambda linha: ordem[linha["situacao"]])
    com_lote = list(ultimo_da_op.values())
    return {
        "etapas": [{"chave": e.chave, "curto": e.curto_gantt or e.curto, "nome": e.nome} for e in fluxo.ETAPAS],
        "linhas": linhas,
        "totais": {**paineis.totais(com_lote), "ops": len(linhas), "sem_lote": sum(1 for x in linhas if x["lote"] is None)},
        "tendencias": paineis.tendencias(itens, _datas_envio(db)),
        "ops": _ops_para_filtro(cadastro),
    }


# ---------------------------------------------------------------- KPIs

PERIODOS = {"3m": "Últimos 3 meses", "6m": "Últimos 6 meses", "12m": "Últimos 12 meses", "ano": "Ano atual", "tudo": "Todo o histórico"}
_DIAS_PERIODO = {"3m": 90, "6m": 180, "12m": 365}


def _corte(periodo: str, hoje: date) -> date | None:
    if periodo in _DIAS_PERIODO:
        return hoje - timedelta(days=_DIAS_PERIODO[periodo])
    if periodo == "ano":
        return date(hoje.year, 1, 1)
    return None


def _pecas_por_mes(itens: list[paineis.Retrato]) -> list[dict]:
    """Peças de cada tipo por mês de criação do lote, sem buracos entre o primeiro e o último mês."""
    por_mes: dict[date, dict[str, int]] = defaultdict(lambda: dict.fromkeys(TIPOS_LOTE, 0))
    for r in itens:
        if r.lote.criado_em:
            por_mes[date(r.lote.criado_em.year, r.lote.criado_em.month, 1)][r.lote.tipo] += r.lote.qtd or 0
    if not por_mes:
        return []
    saida = []
    cursor, fim = min(por_mes), max(por_mes)
    while cursor <= fim:
        v = por_mes.get(cursor, dict.fromkeys(TIPOS_LOTE, 0))
        saida.append({"mes": f"{cursor.month:02d}/{cursor.year}", "chave": f"{cursor.year}-{cursor.month:02d}",
                      "pin": v["PIN"], "box": v["BOX"], "ark": v["ARK"], "total": sum(v.values())})  # fmt: skip
        cursor = date(cursor.year + 1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)
    return saida


@rota.get("/kpis")
def kpis(
    periodo: str = Query("tudo", max_length=10),
    tipo: str = Query("todos", max_length=10),
    _: Contexto = Depends(KPIS),
    db: Session = Depends(get_db),
) -> dict:
    """Indicadores gerenciais de produção. Filtros: período (pela data de criação do lote) e tipo."""
    periodo = periodo.strip().lower()
    if periodo not in PERIODOS:
        periodo = "tudo"
    tipo_filtro = tipo.strip().upper()
    if tipo_filtro not in TIPOS_LOTE:
        tipo_filtro = None
    agora = agora_local()
    hoje = agora.date()
    corte = _corte(periodo, hoje)
    itens = [
        r
        for r in paineis.retratos(db)
        if (tipo_filtro is None or r.lote.tipo == tipo_filtro)
        and (corte is None or (r.lote.criado_em is not None and r.lote.criado_em.date() >= corte))
    ]
    # Databooks enviados: filtrados pelo tipo (o histórico mensal mostra todos os meses)
    datas_envio = _datas_envio(db, tipo_filtro)
    ano = hoje.year
    do_ano = [r for r in itens if r.lote.criado_em and r.lote.criado_em.year == ano]
    return {
        "periodo": periodo,
        "rotulo_periodo": PERIODOS[periodo],
        "tipo": tipo_filtro or "todos",
        "totais": paineis.totais(itens),
        "tendencias": paineis.tendencias(itens, datas_envio, hoje),
        **_resumo_kpis(itens, datas_envio),
        "pecas_mes": _pecas_por_mes(itens),
        "ano": ano,
        "soma_anual": {
            "total": paineis.soma_pecas(do_ano),
            **{t.lower(): paineis.soma_pecas(r for r in do_ano if r.lote.tipo == t) for t in TIPOS_LOTE},
        },
        "gerado_em": agora,
    }


# ---------------------------------------------------------------- indicadores (matéria-prima)


def _percentuais(d: dict) -> dict:
    return {
        **d,
        "pct_refugo": paineis.pct(d["qt_rej"], d["qt_real"]),
        "pct_retrab": paineis.pct(d["qt_retrab"], d["qt_real"]),
        "pct_aprov": paineis.pct(d["qt_ok"], d["qt_real"]),
        "rendimento": paineis.pct(d["qt_ok"], d["qt_fund"]),
    }


_CAMPOS_MP = ("qt_fund", "qt_real", "qt_ok", "qt_rej", "qt_retrab")


def _somar(mps: list[MateriaPrima]) -> dict:
    return {"corridas": len(mps), **{c: sum(getattr(m, c) or 0 for m in mps) for c in _CAMPOS_MP}}


@rota.get("/indicadores")
def indicadores(_: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> dict:
    """% de refugo, retrabalho e aprovação e rendimento, de todas as corridas lançadas (as canceladas não contam)."""
    mps = list(db.scalars(select(MateriaPrima).where(MateriaPrima.cancelado_em.is_(None)).order_by(MateriaPrima.id.desc())))
    por_fornecedor: dict[str, list[MateriaPrima]] = defaultdict(list)
    por_tipo: dict[str, list[MateriaPrima]] = defaultdict(list)
    for m in mps:
        por_fornecedor[m.fornecedor.strip() or "(sem fornecedor)"].append(m)
        por_tipo[m.tipo_destino.strip().upper() or "(sem tipo)"].append(m)
    fornecedores = [{"fornecedor": nome, **_percentuais(_somar(lista))} for nome, lista in por_fornecedor.items()]
    fornecedores.sort(key=lambda f: -f["qt_real"])
    corridas = [
        _percentuais({"id": m.id, "nf_entrada": m.nf_entrada, "corrida": m.corrida, "fornecedor": m.fornecedor,
                      "tipo_destino": m.tipo_destino, **{c: getattr(m, c) or 0 for c in _CAMPOS_MP}})
        for m in mps
    ]  # fmt: skip
    corridas.sort(key=lambda c: -c["pct_refugo"])
    return {
        "total": len(mps),
        "geral": _percentuais(_somar(mps)),
        "por_fornecedor": fornecedores,
        "por_tipo": [{"tipo": nome, **_percentuais(_somar(lista))} for nome, lista in por_tipo.items()],
        "top_refugo": corridas[:10],
    }


# ---------------------------------------------------------------- busca global de lote (Ctrl+K)


def _item_lote(r: paineis.Retrato, descricao: str) -> dict:
    lote = r.lote
    return {
        "tipo": "lote",
        "id": lote.id,
        "op": lote.op,
        "numero": lote.numero,
        "formato": lote.tipo,
        "qtd": lote.qtd,
        "coditem": lote.coditem,
        "descricao": descricao,
        "etapa": paineis.CONCLUIDO if r.concluido else r.etapa.curto_de(lote.tipo),
        "enviado": r.enviado,
        "nc": r.nc,
    }


@rota.get("/buscar")
def buscar(
    q: str = Query("", max_length=100),
    ids: str = Query("", max_length=200),
    _: Contexto = Depends(QUALQUER),
    db: Session = Depends(get_db),
) -> dict:
    """Lotes (e OPs do cadastro ainda sem lote) por OP, número do lote, tipo, CODITEM ou descrição.

    `ids=3,8,5` devolve esses lotes nessa ordem (os "últimos lotes abertos" da busca).
    """
    cadastro = paineis.cadastro_ops(db)

    def descricao(op: str) -> str:
        o = cadastro.get(op.strip())
        return paineis.descricao_curta(o.descricao) if o else ""

    if ids.strip():
        pedidos = [int(p) for p in ids.split(",") if p.strip().isdigit()][:10]
        por_id = {r.lote.id: r for r in paineis.retratos(db, pedidos)}
        itens = [_item_lote(por_id[i], descricao(por_id[i].lote.op)) for i in pedidos if i in por_id]
        return {"total": len(itens), "itens": itens}

    termo = q.strip()
    lotes = list(db.scalars(select(Lote).where(Lote.cancelado_em.is_(None)).order_by(Lote.id.desc())))
    achados = [lote for lote in lotes if contem(f"{lote.op} {lote.numero} {lote.tipo} {lote.coditem} {descricao(lote.op)}", termo)]
    ops_sem_lote = []
    if termo:
        com_lote = {lote.op.strip() for lote in lotes}
        for op, o in cadastro.items():
            if op not in com_lote and contem(f"{op} {o.tipo or ''} {o.coditem} {paineis.descricao_curta(o.descricao)}", termo):
                ops_sem_lote.append(
                    {
                        "tipo": "op",
                        "id": None,
                        "op": op,
                        "numero": "",
                        "formato": (o.tipo or "").strip().upper(),
                        "qtd": o.qt_lote,
                        "coditem": o.coditem,
                        "descricao": paineis.descricao_curta(o.descricao),
                        "etapa": "Sem lote iniciado",
                        "enviado": False,
                        "nc": False,
                    }  # fmt: skip
                )
    # O estado (etapa atual) só é calculado para os lotes que vão aparecer
    mostrar = [lote.id for lote in achados[:LIMITE_BUSCA]]
    por_id = {r.lote.id: r for r in paineis.retratos(db, mostrar)}
    itens = [_item_lote(por_id[i], descricao(por_id[i].lote.op)) for i in mostrar if i in por_id]
    itens += ops_sem_lote[: max(0, LIMITE_BUSCA - len(itens))]
    return {"total": len(achados) + len(ops_sem_lote), "itens": itens}


def contem(alvo: str, termo: str) -> bool:
    return not termo or paineis.contem_termos(alvo, termo)


# ---------------------------------------------------------------- exportação da auditoria


@rota.get("/auditoria/exportar.xlsx")
def exportar_auditoria(
    de: date | None = None,
    ate: date | None = None,
    login: str | None = Query(None, max_length=60),
    acao: str | None = Query(None, max_length=30),
    entidade: str | None = Query(None, max_length=40),
    lote_id: int | None = None,
    _: Contexto = Depends(AUDITORIA),
    db: Session = Depends(get_db),
) -> Response:
    """A auditoria em Excel, com os MESMOS filtros da lista (GET /auditoria, em api_auth.py)."""
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
    registros = list(db.scalars(select(Auditoria).where(*filtros).order_by(Auditoria.id.desc()).limit(LIMITE_AUDITORIA)))
    ids = {a.lote_id for a in registros if a.lote_id}
    numeros = {i: n for i, n in db.execute(select(Lote.id, Lote.numero).where(Lote.id.in_(ids)))} if ids else {}
    wb = exportacoes.planilha_auditoria(registros, numeros)
    return _anexo(exportacoes.em_bytes(wb), f"Auditoria_{agora_local():%Y%m%d_%H%M}.xlsx")
