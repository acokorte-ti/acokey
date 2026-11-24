"""Peças comuns aos envios a prestador externo e à ordem de faturamento (grupo Expedição).

Regras do sistema antigo (legado/app.py): material por tipo de chaveta, descrição curta do cadastro de OPs,
nome curto do cliente nas telas, número do lote "completo" (ano-trimestre-número) da OF e formatação de pesos.
"""
import re
from collections.abc import Iterable
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import fluxo, parametros
from app.config import agora_local
from app.estado import estado_lotes
from app.models import Lote, OrdemProducao, Sequencia
from app.numeracao import COLUNAS

# Material de cada tipo de chaveta (CLAUDE.md: PIN/BOX em SC 4330, ARK em H11 Modified)
_MATERIAL = {"ARK": "H11 Modified"}
_MATERIAL_ESPEC = {"ARK": "H11 Modified NADCA Grade E"}
_PREFIXO_DESCRICAO = re.compile(r"INSTR\.?\s*CONTROLE\s*TRAVAMENTO\s*(?:DES\s+)?", re.IGNORECASE)
_LOTE_COMPLETO = re.compile(r"^\d{2}-\d-\d+$")
LIMITE_PESO = Decimal("9999999")  # a coluna é Numeric(10, 3)


def material(tipo: str | None) -> str:
    """Material curto, como sai nas tabelas de lotes: 'SC 4330' ou 'H11 Modified'."""
    return _MATERIAL.get((tipo or "").upper(), "SC 4330")


def material_especificacao(tipo: str | None) -> str:
    """Material por extenso, como sai no quadro da especificação."""
    return _MATERIAL_ESPEC.get((tipo or "").upper(), "SC 4330 (ASTM A958)")


def descricao_curta(descricao: str | None) -> str:
    """Descrição do produto sem o prefixo genérico do cadastro de OPs ("INSTR. CONTROLE TRAVAMENTO ...")."""
    if not descricao:
        return ""
    achado = _PREFIXO_DESCRICAO.search(descricao)
    return descricao[achado.end() :].strip() if achado else descricao.strip()


def cadastro_ops(db: Session, ops: Iterable[str]) -> dict[str, OrdemProducao]:
    """Cadastro das OPs pedidas, por número (o antigo lia a planilha de OPs a cada tela)."""
    chaves = sorted({(op or "").strip() for op in ops if op})
    if not chaves:
        return {}
    return {o.op.strip(): o for o in db.scalars(select(OrdemProducao).where(OrdemProducao.op.in_(chaves)))}


def cliente_curto(db: Session, cliente: str | None, padrao: str | None = None) -> str:
    """Primeira palavra do cliente da OP, em maiúsculas; sem cadastro, o nome curto dos parâmetros."""
    palavras = (cliente or "").split()
    if palavras:
        return palavras[0].upper()
    if padrao is None:
        padrao = parametros.ler(db, "cliente_nome_curto")
    return padrao.upper()


def etapas_atuais(db: Session, lotes: Iterable[Lote]) -> dict[int, tuple[int, str]]:
    """{lote_id: (índice da etapa real, nome curto)}; 'Concluído' quando todas as etapas estão resolvidas."""
    lotes = list(lotes)
    if not lotes:
        return {}
    estados, _ = estado_lotes(db, [lote.id for lote in lotes])
    saida = {}
    for lote in lotes:
        indice = fluxo.etapa_real(lote.tipo, estados.get(lote.id, {}))
        rotulo = "Concluído" if indice >= fluxo.CONCLUIDO else fluxo.ETAPAS[indice].curto_de(lote.tipo)
        saida[lote.id] = (indice, rotulo)
    return saida


def numero_previsto(db: Session, prefixo: str) -> str:
    """Próximo número, só para mostrar na tela (o número de verdade é reservado ao gravar)."""
    ano = agora_local().year
    linha = db.get(Sequencia, (prefixo, ano))
    if linha is not None:
        return f"{prefixo}-{ano}-{linha.ultimo + 1:03d}"
    coluna = COLUNAS[prefixo]
    padrao = re.compile(rf"^{prefixo}-{ano}-(\d+)$")
    maior = 0
    for numero in db.scalars(select(coluna).where(coluna.like(f"{prefixo}-{ano}-%"))):
        achado = padrao.match(numero or "")
        if achado:
            maior = max(maior, int(achado.group(1)))
    return f"{prefixo}-{ano}-{maior + 1:03d}"


def trimestre(dia: date) -> int:
    return (dia.month - 1) // 3 + 1


def lote_completo(numero: str | None, referencia: date | None = None) -> str:
    """Número completo do lote (AA-T-NNNNN). Se já estiver assim, fica como está; senão, monta com o ano e o
    trimestre da data de referência (os mesmos do código gravado a laser)."""
    numero = (numero or "").strip()
    if _LOTE_COMPLETO.match(numero):
        return numero
    referencia = referencia or agora_local().date()
    return f"{referencia.year % 100:02d}-{trimestre(referencia)}-{numero}"


def lote_com_qtd(numero: str | None, qtd: int | None, referencia: date | None = None) -> str:
    """Formato exclusivo da OF: '26-4-900001 (72 Peças)'."""
    return f"{lote_completo(numero, referencia)} ({qtd or 0} Peças)"


def decimal(valor) -> Decimal:
    """Número digitado (aceita vírgula), nunca negativo; vazio ou inválido vale zero."""
    if valor is None or valor == "":
        return Decimal("0")
    try:
        numero = Decimal(str(valor).strip().replace(",", "."))
    except InvalidOperation:
        return Decimal("0")
    return max(numero, Decimal("0")) if numero.is_finite() else Decimal("0")


def numero_br(valor) -> str:
    """Decimal da especificação em pt-BR, sem zeros à toa: 517.00 -> '517'; 18.50 -> '18,5'."""
    if valor is None or valor == "":
        return ""
    if not isinstance(valor, Decimal):
        try:
            valor = Decimal(str(valor).replace(",", "."))
        except InvalidOperation:
            return str(valor)
    texto = format(valor.normalize(), "f")
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    return texto.replace(".", ",")


def peso(valor) -> str:
    """'1,50 kg'; zero ou vazio vira '—' (como no PDF do sistema antigo)."""
    numero = decimal(valor)
    return f"{numero:.2f}".replace(".", ",") + " kg" if numero else "—"


def peso_sempre(valor) -> str:
    """'0,00 kg' também quando é zero (linha de totais e tabela da OF)."""
    return f"{decimal(valor):.2f}".replace(".", ",") + " kg"


def ler_peso(valor, numero_lote: str) -> Decimal:
    """Peso digitado na tela (aceita vírgula). Vazio vale zero; texto, negativo ou absurdo é recusado."""
    if valor is None or str(valor).strip() == "":
        return Decimal("0")
    try:
        numero = Decimal(str(valor).strip().replace(",", "."))
    except InvalidOperation:
        raise HTTPException(422, f"Peso inválido no lote {numero_lote}: use só números (ex.: 12,5).") from None
    if not numero.is_finite() or numero < 0:
        raise HTTPException(422, f"Peso inválido no lote {numero_lote}: use só números (ex.: 12,5).")
    if numero > LIMITE_PESO:
        raise HTTPException(422, f"Peso grande demais no lote {numero_lote}.")
    return numero.quantize(Decimal("0.001"))
