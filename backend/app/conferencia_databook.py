"""Conferência automática do databook final (porte de legado/conferencia_databook.py).

Lê o texto de cada página do PDF procurando referências de OP e de lote (ex.: "OP 900001", "26-4-900001") e aponta
as páginas que citam uma OP ou um lote diferente do lote em análise. Serve para pegar documento trocado por engano
(ex.: relatório de outra OP anexado como se fosse desta). Usa só o pymupdf, sem IA.
"""
import re
from pathlib import Path

import pymupdf

# OP: 5 ou 6 dígitos, precedidos de "OP" (OP900001, OP 900001, OP-900001), "LOTE OP" ou "Nº DA OP".
# "OP" aparece em muito texto genérico (cabeçalho de certificado): por isso só vale o número logo em seguida.
_RE_OP_PREFIXADA = re.compile(r"(?:OP|LOTE[\s\-]*OP|Nº\s*DA\s*OP)[\s\-:]*(\d{5,6})", re.IGNORECASE)
# Lote completo no formato AA-T-NNNNN (ano, trimestre, OP)
_RE_LOTE_COMPLETO = re.compile(r"\b(\d{2})\s*-\s*(\d)\s*-\s*(\d{5,6})\b")
# Códigos de certificado ("1234.56789", "1234-26A") e de equipamento ("12345/26") não casam com nenhum dos dois.


def conferir_databook(caminho: Path | str, op_esperada: str, lote_esperado: str | None = None) -> dict:
    """Relatório de consistência do PDF.

    Devolve: ok, erro, total_paginas, paginas_com_referencia, paginas_ok, op_esperada, lote_esperado e
    inconsistencias = [{pagina, ops_erradas, lotes_errados, ops_todas, lotes_todos, contexto}].
    """
    try:
        doc = pymupdf.open(caminho)
    except Exception as e:
        return {"ok": False, "erro": f"Não foi possível abrir o PDF ({e}).", "inconsistencias": []}

    op_esperada = str(op_esperada or "").strip()
    lote_esperado = (lote_esperado or "").strip()
    inconsistencias = []
    paginas_com_referencia = 0
    try:
        for i, page in enumerate(doc):
            texto = page.get_text()
            ops = {m.group(1) for m in _RE_OP_PREFIXADA.finditer(texto)}
            lotes = {f"{m.group(1)}-{m.group(2)}-{m.group(3)}" for m in _RE_LOTE_COMPLETO.finditer(texto)}
            if not ops and not lotes:
                continue  # página sem menção a OP/lote (ex.: separador de seção)
            paginas_com_referencia += 1

            ops_erradas = {o for o in ops if o != op_esperada}
            lotes_errados = {lt for lt in lotes if lt != lote_esperado} if lote_esperado else set()
            if ops_erradas or lotes_errados:
                # Trecho do texto em volta do primeiro valor errado, para ajudar a achar na página
                primeiro = sorted(ops_erradas | lotes_errados)[0]
                idx = max(texto.find(primeiro), 0)
                contexto = texto[max(0, idx - 60):idx + 80].replace("\n", " ")
                inconsistencias.append({
                    "pagina": i + 1,
                    "ops_erradas": sorted(ops_erradas),
                    "lotes_errados": sorted(lotes_errados),
                    "ops_todas": sorted(ops),
                    "lotes_todos": sorted(lotes),
                    "contexto": contexto,
                })  # fmt: skip
        total = doc.page_count
    finally:
        doc.close()

    return {
        "ok": True,
        "erro": None,
        "total_paginas": total,
        "paginas_com_referencia": paginas_com_referencia,
        "paginas_ok": paginas_com_referencia - len(inconsistencias),
        "inconsistencias": inconsistencias,
        "op_esperada": op_esperada,
        "lote_esperado": lote_esperado,
    }
