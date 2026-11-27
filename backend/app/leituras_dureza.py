"""Leituras de dureza (HRC) gravadas em um registro da etapa "dureza".

Os registros guardam as leituras em DOIS formatos (legado/app.py, _extrair_leituras_dureza):
1. Relatório gerado pelo sistema (RIP-35): `dados["leituras"] = [{"cp", "valores", "status"}, ...]`.
2. Registro antigo, feito pelo formulário livre: `dados["report"]["tabelas"]`, numa tabela cujo título contém
   "leitura", com linhas `[peça, hrc, resultado]` (uma leitura por linha; linhas da mesma peça se juntam).
Quem reprocessa `dados` de um registro de dureza precisa tratar os dois.
"""
import math
from typing import Any


def numero(valor: Any) -> float | None:
    """'36,5' -> 36.5; vazio ou inválido -> None."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int | float):
        return float(valor) if math.isfinite(valor) else None
    texto = str(valor or "").strip().replace(",", ".")
    if not texto:
        return None
    try:
        convertido = float(texto)
    except ValueError:
        return None
    return convertido if math.isfinite(convertido) else None


def extrair_leituras(dados: Any) -> list[dict]:
    """Normaliza as leituras de qualquer registro de dureza para [{"cp", "peca", "valores": [float], "status"}].

    "peca" (o "Num. Peça" do papel) só existe nos RIP-35 gravados a partir de 26/11/2026; nos outros vem "".
    """
    if not isinstance(dados, dict):
        return []
    leituras = dados.get("leituras")
    if isinstance(leituras, list) and leituras:
        saida = []
        for item in leituras:
            if not isinstance(item, dict):
                continue
            valores = [v for v in (numero(x) for x in item.get("valores") or []) if v is not None]
            saida.append({"cp": str(item.get("cp") or "").strip(), "peca": str(item.get("peca") or "").strip(),
                          "valores": valores, "status": str(item.get("status") or "")})  # fmt: skip
        return saida
    relatorio = dados.get("report") if isinstance(dados.get("report"), dict) else {}
    for tabela in relatorio.get("tabelas") or []:
        if not isinstance(tabela, dict) or "leitura" not in str(tabela.get("titulo") or "").lower():
            continue
        por_peca: dict[str, list[float]] = {}
        for linha in tabela.get("linhas") or []:
            if not linha:
                continue
            peca = str(linha[0]).strip() or "CP"
            por_peca.setdefault(peca, [])
            if len(linha) > 1:
                valor = numero(linha[1])
                if valor is not None:
                    por_peca[peca].append(valor)
        return [{"cp": peca, "peca": "", "valores": valores, "status": ""} for peca, valores in por_peca.items()]
    return []


def status_dureza(valores: list[float], esp_min: float | None, esp_max: float | None) -> str:
    """'APROVADO' só se todas as leituras ficarem dentro da faixa; '' sem leituras ou sem especificação
    (legado/relatorios_sistema.py, calcular_status_dureza)."""
    if not valores or esp_min is None or esp_max is None:
        return ""
    return "APROVADO" if min(valores) >= esp_min and max(valores) <= esp_max else "REPROVADO"


def formatar(valor: float) -> str:
    """36.0 -> '36'; 36.25 -> '36.25' (como o sistema antigo gravava nas tabelas do relatório)."""
    return f"{valor:.6g}"


def texto_leituras(leituras: list[dict]) -> str:
    """'CP1: 2,5 / 36 / 35; CP2: 34 / 35' — para observação e linha do tempo."""
    partes = []
    for item in leituras:
        valores = " / ".join(formatar(v).replace(".", ",") for v in item.get("valores") or [])
        peca = f" (peça {item['peca']})" if item.get("peca") else ""
        partes.append(f"{item.get('cp') or 'CP'}{peca}: {valores or '—'}")
    return "; ".join(partes)
