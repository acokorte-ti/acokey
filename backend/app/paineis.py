"""Retrato da fábrica para o início, o painel, o dashboard, o Gantt, os KPIs e a busca.

Trazido do sistema antigo (legado/app.py: home_pagina, painel, _calcular_pendencias, dashboard, gantt,
kpis_pagina, _calcular_trend, _preencher_timeline_meses, indicadores, api_buscar). Diferença de base: o
antigo misturava o cursor `lotes.etapa` com a etapa real; aqui a etapa mostrada é SEMPRE a real
(fluxo.etapa_real, calculada pelos registros), como no painel novo. O cursor só é usado para saber se o
lote está "pronto para avançar", que é exatamente o que ele significa.

"Enviado-DB" é o databook mandado ao cliente (tabela databooks_enviados, por OP + tipo). Não é a saída
física do lote (Ordem de Faturamento).
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import fluxo
from app.config import agora_local
from app.estado import estado_lotes, lotes_com_nc_aberta
from app.models import TIPOS_LOTE, DatabookEnviado, Lote, OrdemProducao, Registro

ENVIADO_DB = "Enviado-DB"
CONCLUIDO = "Concluído"
# Nome curto de cada setor nos gráficos (o mesmo do sistema antigo)
SETOR_CURTO = {
    "Inspeção de recebimento": "Insp. Recebimento",
    "Tratamento térmico": "Trat. Térmico",
    "Controle de qualidade": "Controle Qualidade",
    "Laboratório externo": "Lab Externo",
    "Laboratório interno": "Lab Interno",
    "Operação externa": "Op Externa",
}
# Posição de cada setor no processo (primeira etapa dele), para mostrar os setores na ordem da fábrica
ORDEM_SETOR: dict[str, int] = {}
for _i, _e in enumerate(fluxo.ETAPAS):
    ORDEM_SETOR.setdefault(_e.setor, _i)


def normalizar(texto: str | None) -> str:
    """Minúsculas e sem acentos: "tempera" acha "TÊMPERA"."""
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return sem_acento.lower().strip()


def contem_termos(alvo: str, busca: str) -> bool:
    """Todos os termos digitados aparecem no texto (ignorando acentos e maiúsculas)."""
    texto = normalizar(alvo)
    return all(t in texto for t in normalizar(busca).split())


_PREFIXO_DESCRICAO = re.compile(r"INSTR\.?\s*CONTROLE\s*TRAVAMENTO\s*(?:DES\s+)?", re.IGNORECASE)


def descricao_curta(descricao: str | None) -> str:
    """Descrição do produto sem o prefixo genérico do cadastro de OPs ("INSTR. CONTROLE TRAVAMENTO ...")."""
    if not descricao:
        return ""
    achado = _PREFIXO_DESCRICAO.search(descricao)
    return descricao[achado.end() :].strip() if achado else descricao.strip()


def chave_envio(op: str | None, tipo: str | None) -> tuple[str, str]:
    return (str(op or "").strip(), (tipo or "").strip().upper())


def enviados_db(db: Session) -> set[tuple[str, str]]:
    """(OP, tipo) que já têm databook enviado ao cliente (envio desfeito não conta)."""
    consulta = select(DatabookEnviado.op, DatabookEnviado.tipo).where(DatabookEnviado.desfeito_em.is_(None))
    return {chave_envio(op, tipo) for op, tipo in db.execute(consulta)}


def cadastro_ops(db: Session) -> dict[str, OrdemProducao]:
    """Cadastro mestre de OPs, na ordem em que foi lançado (a mesma da planilha antiga)."""
    return {o.op.strip(): o for o in db.scalars(select(OrdemProducao).order_by(OrdemProducao.id))}


@dataclass
class Retrato:
    """Onde um lote está, calculado pelos registros."""

    lote: Lote
    estado: fluxo.Estado
    registros: dict[tuple[str, str], Registro]  # último registro não anulado de cada (etapa, sub)
    indice: int  # etapa real (fluxo.CONCLUIDO quando todas as aplicáveis estão resolvidas)
    concluido: bool
    enviado: bool  # concluído e com databook já enviado ao cliente (Enviado-DB)
    nc: bool  # não conformidade aberta ou em tratamento (mesmo critério do painel)
    pronto: bool  # o cursor do lote pode avançar (etapa em que foi deixado já está resolvida)
    dias: int | None  # dias na etapa atual
    concluido_em: datetime | None

    @property
    def etapa(self) -> fluxo.Etapa | None:
        return None if self.concluido else fluxo.ETAPAS[self.indice]

    @property
    def situacao(self) -> str:
        """andamento | concluido | enviado"""
        if self.enviado:
            return "enviado"
        return "concluido" if self.concluido else "andamento"

    @property
    def setor(self) -> str:
        if self.enviado:
            return ENVIADO_DB
        return CONCLUIDO if self.concluido else self.etapa.setor

    @property
    def etapa_curto(self) -> str:
        if self.enviado:
            return "Enviado DB ao cliente"
        return "Databook pronto" if self.concluido else self.etapa.curto_de(self.lote.tipo)


def retratos(db: Session, lote_ids: Iterable[int] | None = None) -> list[Retrato]:
    """Retrato de cada lote não cancelado (em ordem de criação), lendo o banco poucas vezes."""
    consulta = select(Lote).where(Lote.cancelado_em.is_(None)).order_by(Lote.id)
    ids = list(lote_ids) if lote_ids is not None else None
    if ids is not None:
        if not ids:
            return []
        consulta = consulta.where(Lote.id.in_(ids))
    lotes = list(db.scalars(consulta))
    estados, ultimos = estado_lotes(db, ids)
    com_nc = lotes_com_nc_aberta(db, ids)
    enviados = enviados_db(db)
    registros: dict[int, dict[tuple[str, str], Registro]] = {}
    ultima_data: dict[int, datetime] = {}
    for (lote_id, etapa, sub), registro in ultimos.items():
        registros.setdefault(lote_id, {})[(etapa, sub)] = registro
        if registro.quando and (lote_id not in ultima_data or registro.quando > ultima_data[lote_id]):
            ultima_data[lote_id] = registro.quando
    agora = agora_local()

    resultado = []
    for lote in lotes:
        estado = estados.get(lote.id, {})
        indice = fluxo.etapa_real(lote.tipo, estado)
        concluido = indice >= fluxo.CONCLUIDO
        nc = lote.id in com_nc
        if not concluido:
            nc = nc or fluxo.nc_pendente_etapa(fluxo.ETAPAS[indice], lote.tipo, estado)
        # Data da conclusão: quando o cursor passou da última etapa; se ele ficou para trás, o último registro
        concluido_em = None
        if concluido:
            concluido_em = lote.etapa_desde if lote.etapa >= fluxo.CONCLUIDO and lote.etapa_desde else ultima_data.get(lote.id)
        resultado.append(
            Retrato(
                lote=lote,
                estado=estado,
                registros=registros.get(lote.id, {}),
                indice=indice,
                concluido=concluido,
                enviado=concluido and chave_envio(lote.op, lote.tipo) in enviados,
                nc=nc,
                pronto=not concluido and fluxo.pode_avancar(lote.etapa, lote.tipo, estado),
                dias=(agora - lote.etapa_desde).days if lote.etapa_desde else None,
                concluido_em=concluido_em,
            )
        )
    return resultado


# ---------------------------------------------------------------- contas


def soma_pecas(itens: Iterable[Retrato]) -> int:
    return sum(r.lote.qtd or 0 for r in itens)


def totais(itens: list[Retrato]) -> dict:
    """Contadores do topo do dashboard, do Gantt e dos KPIs (os mesmos nomes do sistema antigo)."""
    andamento = [r for r in itens if not r.concluido]
    concluidos = [r for r in itens if r.concluido and not r.enviado]
    enviados = [r for r in itens if r.enviado]
    saida: dict = {
        "lotes": len(itens),
        "pecas": soma_pecas(itens),
        "andamento": len(andamento),
        "pecas_andamento": soma_pecas(andamento),
        "concluidos": len(concluidos),
        "pecas_concluidos": soma_pecas(concluidos),
        "enviados": len(enviados),
        "pecas_enviados": soma_pecas(enviados),
    }
    for tipo in TIPOS_LOTE:
        t = tipo.lower()
        do_tipo = [r for r in itens if r.lote.tipo == tipo]
        enviados_tipo = sum(1 for r in do_tipo if r.enviado)
        saida[t] = len(do_tipo)
        saida[f"pecas_{t}"] = soma_pecas(do_tipo)
        saida[f"{t}_enviados"] = enviados_tipo
        saida[f"{t}_ativos"] = len(do_tipo) - enviados_tipo
    return saida


def _inicio_mes(d: date) -> date:
    return date(d.year, d.month, 1)


def _mes_seguinte(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


def _mes_anterior(d: date) -> date:
    return date(d.year - 1, 12, 1) if d.month == 1 else date(d.year, d.month - 1, 1)


def variacao(atual: int, anterior: int) -> dict | None:
    """Mês atual contra o anterior. None quando não há nada nos dois meses."""
    if atual == 0 and anterior == 0:
        return None
    base = {"atual": atual, "anterior": anterior}
    if anterior == 0:
        return {**base, "sentido": "novo", "rotulo": "novo este mês", "pct": None}
    pct = int(round((atual - anterior) / anterior * 100))
    if pct > 0:
        return {**base, "sentido": "subiu", "rotulo": f"+{pct}%", "pct": pct}
    if pct < 0:
        return {**base, "sentido": "caiu", "rotulo": f"{pct}%", "pct": pct}
    return {**base, "sentido": "igual", "rotulo": "0%", "pct": 0}


def tendencias(itens: list[Retrato], datas_envio: Iterable[date | None], hoje: date | None = None) -> dict:
    """Tendência mês a mês: lotes concluídos, databooks enviados e lotes criados de cada tipo."""
    hoje = hoje or agora_local().date()
    atual_ini = _inicio_mes(hoje)
    atual_fim = _mes_seguinte(atual_ini)
    ant_ini = _mes_anterior(atual_ini)

    def no_mes(valor: date | datetime | None, inicio: date, fim: date) -> bool:
        if valor is None:
            return False
        dia = valor.date() if isinstance(valor, datetime) else valor
        return inicio <= dia < fim

    def contar(valores: list, inicio: date, fim: date) -> int:
        return sum(1 for v in valores if no_mes(v, inicio, fim))

    concluidos = [r.concluido_em for r in itens if r.concluido]
    envios = list(datas_envio)
    saida = {
        "concluidos": variacao(contar(concluidos, atual_ini, atual_fim), contar(concluidos, ant_ini, atual_ini)),
        "enviados": variacao(contar(envios, atual_ini, atual_fim), contar(envios, ant_ini, atual_ini)),
    }
    for tipo in TIPOS_LOTE:
        criados = [r.lote.criado_em for r in itens if r.lote.tipo == tipo]
        saida[tipo.lower()] = variacao(contar(criados, atual_ini, atual_fim), contar(criados, ant_ini, atual_ini))
    return saida


def linha_do_tempo(datas: Iterable[date | None], minimo_meses: int = 6, hoje: date | None = None) -> list[dict]:
    """Databooks enviados por mês, do mês mais antigo com envio até o atual, com zeros nos meses vazios.

    Mostra pelo menos `minimo_meses` meses, para o gráfico não ficar com uma barra solitária.
    """
    hoje = hoje or agora_local().date()
    por_mes = Counter(_inicio_mes(d) for d in datas if d is not None)
    fim = _inicio_mes(hoje)
    inicio = fim
    for _ in range(minimo_meses - 1):
        inicio = _mes_anterior(inicio)
    if por_mes:
        inicio = min(inicio, min(por_mes))
    saida = []
    cursor = inicio
    while cursor <= fim:
        saida.append(
            {"mes": f"{cursor.month:02d}/{cursor.year}", "chave": f"{cursor.year}-{cursor.month:02d}", "enviados": por_mes.get(cursor, 0)}
        )
        cursor = _mes_seguinte(cursor)
    return saida


def gargalos(itens: Iterable[Retrato]) -> list[dict]:
    """Lotes em andamento por setor e dias médios parados. O setor com mais lotes (e mais dias) vem primeiro."""
    por_setor: dict[str, list[int]] = {}
    for r in itens:
        if r.concluido:
            continue
        por_setor.setdefault(r.etapa.setor, []).append(r.dias or 0)
    saida = [
        {
            "setor": SETOR_CURTO.get(setor, setor),
            "setor_completo": setor,
            "lotes": len(dias),
            "dias_medio": round(sum(dias) / len(dias), 1),
        }
        for setor, dias in por_setor.items()
    ]
    saida.sort(key=lambda s: (-s["lotes"], -s["dias_medio"], ORDEM_SETOR.get(s["setor_completo"], 99)))
    return saida


def funil(itens: list[Retrato]) -> tuple[list[dict], list[dict]]:
    """Pipeline em dois estados (Em andamento / Finalizados), no total e por tipo."""
    andamento = [r for r in itens if not r.concluido]
    finalizados = [r for r in itens if r.concluido]  # concluídos sem enviar + Enviados-DB
    geral = [
        {"nome": "Em andamento", "lotes": len(andamento), "pecas": soma_pecas(andamento)},
        {"nome": "Finalizados", "lotes": len(finalizados), "pecas": soma_pecas(finalizados)},
    ]
    por_tipo = []
    for nome, grupo in (("Em andamento", andamento), ("Finalizados", finalizados)):
        linha: dict = {"nome": nome}
        for tipo in TIPOS_LOTE:
            do_tipo = [r for r in grupo if r.lote.tipo == tipo]
            linha[tipo.lower()] = len(do_tipo)
            linha[f"pecas_{tipo.lower()}"] = soma_pecas(do_tipo)
        por_tipo.append(linha)
    return geral, por_tipo


def pct(parte: float, todo: float) -> float:
    return round(parte / todo * 100, 1) if todo else 0.0
