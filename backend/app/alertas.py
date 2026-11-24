"""Alertas automáticos do topo do painel ("Ações pendentes").

Trazido de legado/app.py, _calcular_pendencias. Cada alerta diz o que precisa de atenção, para onde ir e o
que fazer lá. As consultas leem as tabelas de cada módulo diretamente (não dependem do código deles).

Diferença do antigo: cada alerta só aparece para quem pode abrir a tela para onde ele leva (ex.: corridas
de matéria-prima pendentes só para a Qualidade), como o menu.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import paineis
from app.config import agora_local, config
from app.models import CargaTT, EnvioPrestador, Equipamento, MateriaPrima
from app.seguranca import Contexto

DIAS_PARADO = 7  # lote na mesma etapa há 7 dias ou mais
DIAS_DATABOOK_SEM_ENVIO = 3  # databook gerado e ainda não enviado ao cliente
DIAS_CALIBRACAO = 30  # calibração que vence nos próximos 30 dias
HORAS_CARGA_TT = 24  # carga de TT "em andamento" há 24 horas ou mais (possível carga esquecida)
DIAS_ENVIO_PRESTADOR = 10  # envio a prestador sem retorno há 10 dias ou mais


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _alerta(chave: str, nivel: str, texto: str, link: str, acao: str, quantidade: int) -> dict:
    """nivel: erro | alerta | info | ok (a tela escolhe cor e ícone por ele e pela chave)."""
    return {"chave": chave, "nivel": nivel, "texto": texto, "link": link, "acao": acao, "quantidade": quantidade}


def databooks_gerados(lote_id: int) -> list[float]:
    """Data de modificação (timestamp) de cada PDF de databook gerado para o lote."""
    pasta = config().pasta_arquivos / "lotes" / str(lote_id) / "databook" / "saida"
    if not pasta.is_dir():
        return []
    return [p.stat().st_mtime for p in pasta.glob("*.pdf") if p.is_file()]


def pendencias(db: Session, ctx: Contexto, itens: list[paineis.Retrato], agora: datetime | None = None) -> list[dict]:
    agora = agora or agora_local()
    hoje = agora.date()
    qualidade = ctx.tem_modulo("qualidade")
    saida: list[dict] = []

    # Corridas de matéria-prima aguardando aprovação da Qualidade
    if qualidade:
        pendentes = list(
            db.scalars(
                select(MateriaPrima.id)
                .where(MateriaPrima.status == "pendente", MateriaPrima.cancelado_em.is_(None))
                .order_by(MateriaPrima.id)
            )
        )
        if pendentes:
            n = len(pendentes)
            saida.append(
                _alerta(
                    "materia_prima",
                    "alerta",
                    f"{_plural(n, 'corrida', 'corridas')} de matéria-prima aguardando aprovação",
                    f"/materia-prima/{pendentes[0]}" if n == 1 else "/materia-prima",
                    "Revisar corrida" if n == 1 else "Revisar corridas",
                    n,
                )
            )

    # Lotes parados na mesma etapa (os que têm NC aberta entram no alerta da NC)
    parados = [r for r in itens if not r.concluido and not r.nc and r.dias is not None and r.dias >= DIAS_PARADO]
    if parados:
        exemplo = max(parados, key=lambda r: r.dias or 0)  # o que está parado há mais tempo
        n = len(parados)
        saida.append(
            _alerta(
                "parados",
                "alerta",
                f"{_plural(n, 'lote parado', 'lotes parados')} na mesma etapa há {DIAS_PARADO} dias ou mais "
                f"(o mais antigo: OP {exemplo.lote.op}, {exemplo.dias} dias)",
                f"/lotes/{exemplo.lote.id}",
                "Abrir o mais antigo",
                n,
            )
        )

    # Não conformidade aberta aguardando decisão
    com_nc = [r for r in itens if r.nc]
    if com_nc and qualidade:
        n = len(com_nc)
        saida.append(
            _alerta(
                "nc",
                "erro",
                f"{_plural(n, 'lote', 'lotes')} com não conformidade aberta aguardando decisão",
                "/nao-conformidades",
                "Ver não conformidades",
                n,
            )
        )

    # Lotes prontos para avançar de etapa
    prontos = [r for r in itens if r.pronto]
    if prontos:
        n = len(prontos)
        saida.append(
            _alerta(
                "prontos",
                "ok",
                f"{_plural(n, 'lote pronto', 'lotes prontos')} para avançar de etapa",
                f"/lotes/{prontos[-1].lote.id}",  # o mais recente, como no antigo
                "Avançar",
                n,
            )
        )

    # Databooks: concluídos sem databook gerado e gerados há dias sem envio ao cliente
    if qualidade:
        sem_databook: list[paineis.Retrato] = []
        sem_envio = 0
        limite = agora.timestamp() - DIAS_DATABOOK_SEM_ENVIO * 86400
        for r in itens:
            if not r.concluido or r.enviado:
                continue
            gerados = databooks_gerados(r.lote.id)
            if not gerados:
                sem_databook.append(r)
            elif max(gerados) <= limite:
                sem_envio += 1
        if sem_databook:
            n = len(sem_databook)
            exemplo = sem_databook[-1]
            saida.append(
                _alerta(
                    "sem_databook",
                    "info",
                    f"{_plural(n, 'lote concluído', 'lotes concluídos')} aguardando a geração do databook",
                    f"/lotes/{exemplo.lote.id}#databook",
                    "Gerar databook",
                    n,
                )
            )
        if sem_envio:
            saida.append(
                _alerta(
                    "databook_sem_envio",
                    "alerta",
                    f"{_plural(sem_envio, 'databook gerado', 'databooks gerados')} há {DIAS_DATABOOK_SEM_ENVIO} dias ou mais "
                    "e ainda não enviado(s) ao cliente",
                    "/databooks",
                    "Ir para Databooks",
                    sem_envio,
                )
            )

    # Calibração de equipamentos: vencida e vencendo nos próximos 30 dias
    if ctx.tem_modulo("qualidade", "cadastros"):
        saida.extend(_calibracoes(db, hoje))

    # Carga de tratamento térmico em andamento há muito tempo (possível carga esquecida)
    if ctx.tem_modulo("qualidade", "producao_tt"):
        esquecidas = list(
            db.execute(
                select(CargaTT.id, CargaTT.numero)
                .where(
                    CargaTT.status == "em_andamento",
                    CargaTT.data_inicio.is_not(None),
                    CargaTT.data_inicio <= agora - timedelta(hours=HORAS_CARGA_TT),
                )
                .order_by(CargaTT.data_inicio, CargaTT.id)
            )
        )
        if esquecidas:
            n = len(esquecidas)
            saida.append(
                _alerta(
                    "carga_tt",
                    "alerta",
                    f"{_plural(n, 'carga', 'cargas')} de TT em andamento há {HORAS_CARGA_TT} horas ou mais "
                    f"(ex.: {esquecidas[0].numero})",
                    f"/cargas-tt/{esquecidas[0].id}",
                    "Abrir carga",
                    n,
                )
            )

    # Envio a prestador externo sem retorno
    if ctx.tem_modulo("qualidade", "producao_tt", "producao_usinagem"):
        sem_retorno = list(
            db.execute(
                select(EnvioPrestador.id, EnvioPrestador.numero)
                .where(
                    EnvioPrestador.status == "enviado",
                    EnvioPrestador.data_envio.is_not(None),
                    EnvioPrestador.data_envio <= hoje - timedelta(days=DIAS_ENVIO_PRESTADOR),
                )
                .order_by(EnvioPrestador.data_envio, EnvioPrestador.id)
            )
        )
        if sem_retorno:
            n = len(sem_retorno)
            saida.append(
                _alerta(
                    "envio_prestador",
                    "alerta",
                    f"{_plural(n, 'envio', 'envios')} a prestador externo aguardando retorno há {DIAS_ENVIO_PRESTADOR} dias "
                    f"ou mais (ex.: {sem_retorno[0].numero})",
                    f"/envios/{sem_retorno[0].id}",
                    "Abrir envio",
                    n,
                )
            )

    return saida


def contar_calibracoes(db: Session, hoje: date) -> tuple[int, int]:
    """(vencidas, vencendo nos próximos 30 dias) entre os equipamentos ativos."""
    ativos = Equipamento.ativo.is_(True), Equipamento.validade_calibracao.is_not(None)
    vencidas = db.scalar(select(func.count(Equipamento.id)).where(*ativos, Equipamento.validade_calibracao < hoje)) or 0
    vencendo = db.scalar(
        select(func.count(Equipamento.id)).where(
            *ativos,
            Equipamento.validade_calibracao >= hoje,
            Equipamento.validade_calibracao <= hoje + timedelta(days=DIAS_CALIBRACAO),
        )
    )
    return vencidas, vencendo or 0


def _calibracoes(db: Session, hoje: date) -> list[dict]:
    vencidas, vencendo = contar_calibracoes(db, hoje)
    saida = []
    if vencidas:
        saida.append(
            _alerta(
                "calibracao_vencida",
                "erro",
                f"{_plural(vencidas, 'equipamento', 'equipamentos')} com a calibração vencida",
                "/equipamentos",
                "Ver equipamentos",
                vencidas,
            )
        )
    if vencendo:
        saida.append(
            _alerta(
                "calibracao",
                "alerta",
                f"{_plural(vencendo, 'equipamento', 'equipamentos')} com a calibração vencendo em até {DIAS_CALIBRACAO} dias",
                "/equipamentos",
                "Ver equipamentos",
                vencendo,
            )
        )
    return saida
