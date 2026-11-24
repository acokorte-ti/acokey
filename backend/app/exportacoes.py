"""Planilhas Excel do painel de lotes e da auditoria.

Trazido de legado/app.py (exportar_painel_xlsx e auditoria_exportar): mesmas colunas, cores e aba de
resumo. Todo texto passa por `celula_segura` (sem caractere inválido e sem virar fórmula ao abrir).
"""

import io
import json
from collections.abc import Iterable
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app import paineis
from app.config import FUSO
from app.models import Auditoria, OrdemProducao
from app.seguranca import celula_segura

TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_AZUL = "1F3A5F"
_FINO = Side(border_style="thin", color="BFC9D6")
_BORDA = Border(top=_FINO, bottom=_FINO, left=_FINO, right=_FINO)
_COR_TIPO = {
    "PIN": PatternFill("solid", fgColor="D6E4F2"),
    "BOX": PatternFill("solid", fgColor="FBE2D0"),
    "ARK": PatternFill("solid", fgColor="D5EBD6"),
}
_COR_ENVIADO = PatternFill("solid", fgColor="EDE1FF")
_COR_CONCLUIDO = PatternFill("solid", fgColor="E8F5E9")
_COR_ATRASADO = PatternFill("solid", fgColor="FBE7E4")
DIAS_ATRASADO = 10  # na planilha, a célula de dias fica vermelha a partir daqui
_MAX_CELULA = 32_000  # o Excel não abre célula com mais de 32.767 caracteres


def _cabecalho(ws: Worksheet, titulos: list[str], larguras: list[int]) -> None:
    ws.append(titulos)
    for celula in ws[1]:
        celula.fill = PatternFill("solid", fgColor=_AZUL)
        celula.font = Font(bold=True, color="FFFFFF", size=11)
        celula.alignment = Alignment(horizontal="center", vertical="center")
        celula.border = _BORDA
    ws.row_dimensions[1].height = 22
    for i, largura in enumerate(larguras, start=1):
        ws.column_dimensions[get_column_letter(i)].width = largura


def _linha(ws: Worksheet, valores: list) -> int:
    ws.append([celula_segura(v) for v in valores])
    return ws.max_row


def em_bytes(wb: Workbook) -> bytes:
    saida = io.BytesIO()
    wb.save(saida)
    return saida.getvalue()


def _primeiro_nome(cliente: str | None) -> str:
    """Razão social do cadastro de OPs -> só a primeira palavra, com inicial maiúscula (como no antigo)."""
    partes = (cliente or "").strip().split()
    return partes[0].capitalize() if partes else ""


def planilha_painel(itens: list[paineis.Retrato], cadastro: dict[str, OrdemProducao], cliente_padrao: str, agora: datetime) -> Workbook:
    """Uma linha por lote (do mais novo para o mais antigo) e uma aba de resumo."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Lotes"
    titulos = ["OP", "Lote", "Tipo", "Qtd (peças)", "Corrida", "CODITEM", "Cliente", "PO", "Etapa atual", "Setor",
               "Dias na etapa", "Status", "Enviado-DB", "Criado em"]  # fmt: skip
    _cabecalho(ws, titulos, [12, 14, 8, 11, 12, 16, 22, 10, 28, 20, 13, 20, 12, 18])

    for r in sorted(itens, key=lambda x: x.lote.id, reverse=True):
        lote = r.lote
        if r.concluido:
            etapa_nome = paineis.CONCLUIDO
            setor = status = paineis.ENVIADO_DB if r.enviado else paineis.CONCLUIDO
        else:
            etapa_nome = r.etapa.nome_de(lote.tipo)
            setor = r.etapa.setor
            status = "Reprovado na etapa" if r.nc else "Em andamento"
        op = cadastro.get(lote.op.strip())
        linha = _linha(
            ws,
            [lote.op, lote.numero, lote.tipo, lote.qtd or 0, lote.corrida, lote.coditem,
             _primeiro_nome(op.cliente if op else "") or cliente_padrao, op.po if op else "",
             etapa_nome, setor, r.dias, status, "Sim" if r.enviado else "Não", lote.criado_em],
        )  # fmt: skip
        ws.cell(row=linha, column=14).number_format = "dd/mm/yyyy hh:mm"
        celula_tipo = ws.cell(row=linha, column=3)
        if lote.tipo in _COR_TIPO:
            celula_tipo.fill = _COR_TIPO[lote.tipo]
        celula_tipo.alignment = Alignment(horizontal="center")
        if r.enviado:
            for coluna in range(1, len(titulos) + 1):
                ws.cell(row=linha, column=coluna).fill = _COR_ENVIADO
        elif r.concluido:
            for coluna in range(1, len(titulos) + 1):
                ws.cell(row=linha, column=coluna).fill = _COR_CONCLUIDO
        elif (r.dias or 0) >= DIAS_ATRASADO:
            ws.cell(row=linha, column=11).fill = _COR_ATRASADO
        for coluna in range(1, len(titulos) + 1):
            ws.cell(row=linha, column=coluna).border = _BORDA
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    resumo = wb.create_sheet("Resumo")
    resumo.append(["Painel de lotes — Resumo"])
    resumo["A1"].font = Font(bold=True, size=14, color=_AZUL)
    resumo.append(["Gerado em", agora.strftime("%d/%m/%Y %H:%M")])
    resumo.append([])
    totais = paineis.totais(itens)
    resumo.append(["Total de lotes", totais["lotes"]])
    resumo.append(["Em andamento", totais["andamento"]])
    resumo.append(["Concluídos (sem envio-DB)", totais["concluidos"]])
    resumo.append(["Enviado-DB", totais["enviados"]])
    resumo.append([])
    for tipo in ("PIN", "BOX", "ARK"):
        resumo.append([f"Total {tipo}", totais[tipo.lower()]])
    resumo.column_dimensions["A"].width = 32
    resumo.column_dimensions["B"].width = 16
    for linha in resumo.iter_rows(min_row=4, max_row=resumo.max_row, min_col=1, max_col=1):
        linha[0].font = Font(bold=True)
    return wb


def _json(valor) -> str:
    if valor in (None, {}, []):
        return ""
    texto = json.dumps(valor, ensure_ascii=False)
    return texto if len(texto) <= _MAX_CELULA else texto[:_MAX_CELULA] + " …(cortado)"


def planilha_auditoria(registros: Iterable[Auditoria], numero_do_lote: dict[int, str]) -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "Auditoria"
    _cabecalho(ws, ["Quando", "Usuário", "Ação", "Sobre", "ID", "Lote", "Motivo", "Detalhes (JSON)", "IP"],
               [19, 16, 18, 18, 16, 16, 30, 70, 16])  # fmt: skip
    for a in registros:
        detalhes = a.detalhes if isinstance(a.detalhes, dict) else None
        motivo = detalhes.get("motivo") if detalhes else None
        quando = a.quando.astimezone(FUSO).replace(tzinfo=None) if a.quando else None  # horário de Itu, como na tela
        linha = _linha(
            ws,
            [quando, a.login or "", a.acao, a.entidade or "", a.entidade_id or "",
             numero_do_lote.get(a.lote_id, f"#{a.lote_id}") if a.lote_id else "",
             motivo if isinstance(motivo, str) else "", _json(a.detalhes), a.ip or ""],
        )  # fmt: skip
        ws.cell(row=linha, column=1).number_format = "dd/mm/yyyy hh:mm:ss"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return wb
