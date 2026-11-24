"""Números sequenciais por ano: NC-2026-001 (não conformidade), TT-2026-001 (carga de forno),
EP-2026-001 (envio a prestador), OF-2026-001 (ordem de faturamento).

O sistema antigo fazia "maior número + 1" com uma consulta, e duas pessoas ao mesmo tempo podiam receber o
mesmo número. Aqui a linha da tabela `sequencias` é travada até o fim da transação de quem pediu o número.
"""
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import agora_local
from app.models import CargaTT, EnvioPrestador, NaoConformidade, OrdemFaturamento, Sequencia

# prefixo -> coluna onde os números já gravados (inclusive os migrados) estão
COLUNAS = {
    "NC": NaoConformidade.numero,
    "TT": CargaTT.numero,
    "EP": EnvioPrestador.numero,
    "OF": OrdemFaturamento.numero,
}


def _maior_existente(db: Session, prefixo: str, ano: int) -> int:
    """Maior número já usado no ano (vale para o primeiro número do ano depois da carga do sistema antigo)."""
    padrao = re.compile(rf"^{prefixo}-{ano}-(\d+)$")
    maior = 0
    for numero in db.scalars(select(COLUNAS[prefixo]).where(COLUNAS[prefixo].like(f"{prefixo}-{ano}-%"))):
        achado = padrao.match(numero or "")
        if achado:
            maior = max(maior, int(achado.group(1)))
    return maior


def proximo_numero(db: Session, prefixo: str, ano: int | None = None) -> str:
    """Reserva e devolve o próximo número. Quem chama grava o registro na MESMA transação e faz o commit."""
    if prefixo not in COLUNAS:
        raise ValueError(f"Prefixo de numeração desconhecido: {prefixo}")
    ano = ano or agora_local().year
    linha = db.get(Sequencia, (prefixo, ano), with_for_update=True)
    if linha is None:
        try:
            with db.begin_nested():  # duas primeiras do ano ao mesmo tempo: uma cria, a outra relê
                linha = Sequencia(prefixo=prefixo, ano=ano, ultimo=_maior_existente(db, prefixo, ano))
                db.add(linha)
        except IntegrityError:
            linha = db.get(Sequencia, (prefixo, ano), with_for_update=True, populate_existing=True)
    linha.ultimo += 1
    db.flush()
    return f"{prefixo}-{ano}-{linha.ultimo:03d}"
