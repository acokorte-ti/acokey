"""PDF genérico de um registro de etapa (o "Abrir relatório PDF" da página da etapa).

Portado de legado/app.py (grafico_png e gerar_pdf): cabeçalho com logo, empresa e título; identificação do lote;
os pares rótulo/valor do formulário; as tabelas (FORA em vermelho); a curva do forno no tratamento térmico;
observações; quem registrou e as linhas de assinatura. Documento INTERNO (não entra no databook do cliente).
Todas as tabelas da página têm a mesma largura total (LARGURA_UTIL).
"""
import io
from datetime import datetime
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from app import parametros
from app.models import Lote, Registro
from app.pdf_comum import LARGURA_UTIL, LOGO, empresa, fontes

AZUL = "#1F3A5F"


def grafico_png(grafico: dict) -> io.BytesIO:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = [p[0] for p in grafico["pts"]]
    y = [p[1] for p in grafico["pts"]]
    alvo, tol = float(grafico["alvo"]), float(grafico["tol"])
    fig, ax = plt.subplots(figsize=(7.4, 3.5), dpi=150)
    ax.plot(x, y, color=AZUL, lw=1.8, label="Temperatura do forno")
    ax.axhspan(alvo - tol, alvo + tol, color="#2e8b57", alpha=0.18, label="Faixa do patamar")
    ax.axhline(alvo, color="#2e8b57", lw=0.8, ls="--")
    ax.set_xlabel("Tempo (min)")
    ax.set_ylabel("Temperatura (°C)")
    ax.grid(alpha=0.3)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    saida = io.BytesIO()
    fig.savefig(saida, format="png")
    plt.close(fig)
    saida.seek(0)
    return saida


def _quando(valor: datetime | None) -> str:
    return valor.strftime("%d/%m/%Y %H:%M") if valor else "-"


def _larguras(colunas: int) -> list[float]:
    """Primeira coluna (nome da cota, CP, elemento) mais larga; as outras dividem o resto. Soma = LARGURA_UTIL."""
    if colunas <= 1:
        return [LARGURA_UTIL]
    from reportlab.lib.units import mm

    primeira = 50 * mm if colunas >= 5 else 46 * mm
    resto = (LARGURA_UTIL - primeira) / (colunas - 1)
    return [primeira] + [resto] * (colunas - 1)


def gerar_pdf_registro(db: Session, lote: Lote, registro: Registro, report: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    f = fontes()
    azul = colors.HexColor(AZUL)
    dados_empresa = empresa(db)
    titulo = str(report.get("titulo") or "Registro de etapa")
    n = ParagraphStyle("n", fontName=f["normal"], fontSize=9, leading=11)
    h = ParagraphStyle("h", parent=n, fontName=f["negrito"], textColor=azul, fontSize=12, leading=15, spaceBefore=8, spaceAfter=4)
    branco = ParagraphStyle("b", parent=n, fontName=f["negrito"], textColor=colors.white, fontSize=12, leading=14)
    branco_dir = ParagraphStyle("bd", parent=branco, fontSize=10, leading=12, alignment=2)

    buffer = io.BytesIO()
    margem = (A4[0] - LARGURA_UTIL) / 2
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=margem, rightMargin=margem, topMargin=12 * mm, bottomMargin=15 * mm,
                            title=titulo, author=dados_empresa["razao_social"])  # fmt: skip
    partes: list = []

    celula_empresa = Paragraph(escape(dados_empresa["razao_social"]), branco)
    celula_titulo = Paragraph(escape(titulo), branco_dir)
    if LOGO.is_file():
        logo = Image(str(LOGO), width=16 * mm, height=16 * mm, kind="proportional")
        cabecalho = Table([[logo, celula_empresa, celula_titulo]], colWidths=[20 * mm, 60 * mm, LARGURA_UTIL - 80 * mm])
    else:
        cabecalho = Table([[celula_empresa, celula_titulo]], colWidths=[76 * mm, LARGURA_UTIL - 76 * mm])
    cabecalho.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), azul), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                   ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))  # fmt: skip
    partes += [cabecalho, Spacer(1, 4 * mm)]

    if registro.anulado:
        aviso = ParagraphStyle("a", parent=n, fontName=f["negrito"], textColor=colors.HexColor("#B3261E"), fontSize=10, leading=13)
        motivo = f" Motivo: {registro.anulado_motivo}" if registro.anulado_motivo else ""
        partes += [Paragraph(escape(f"REGISTRO ANULADO (não vale para o fluxo do lote).{motivo}"), aviso), Spacer(1, 3 * mm)]

    cliente = parametros.ler(db, "cliente_nome") or "-"
    identificacao = [["Cliente", cliente, "OP", lote.op], ["Lote", lote.numero, "Formato", lote.tipo],
                     ["Quantidade", f"{lote.qtd} peças", "Corrida", lote.corrida or "-"]]  # fmt: skip
    rotulo, valor = 28 * mm, LARGURA_UTIL / 2 - 28 * mm
    tabela = Table([[Paragraph(escape(str(c)), n) for c in linha] for linha in identificacao], colWidths=[rotulo, valor, rotulo, valor])
    tabela.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("FONTNAME", (0, 0), (-1, -1), f["normal"]),
                                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF2F7")),
                                ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#EEF2F7"))]))  # fmt: skip
    partes += [tabela, Spacer(1, 4 * mm)]

    pares = [p for p in report.get("kv") or [] if isinstance(p, list | tuple) and len(p) == 2]
    if pares:
        negrito = ParagraphStyle("nb", parent=n, fontName=f["negrito"])
        linhas = [[Paragraph(escape(str(a)), negrito), Paragraph(escape(str(b)) or "-", n)] for a, b in pares]
        tabela = Table(linhas, colWidths=[55 * mm, LARGURA_UTIL - 55 * mm])
        tabela.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F5F7FA"))]))  # fmt: skip
        partes.append(tabela)

    celula = ParagraphStyle("c", parent=n, fontSize=8.5, leading=10.5)
    celula_centro = ParagraphStyle("cc", parent=celula, alignment=1)
    cab_estilo = ParagraphStyle("ch", parent=celula, fontName=f["negrito"], textColor=colors.white, alignment=1)
    vermelho = ParagraphStyle("cv", parent=celula_centro, fontName=f["negrito"], textColor=colors.red)
    for tb in report.get("tabelas") or []:
        if not isinstance(tb, dict) or not tb.get("cab"):
            continue
        cab = [str(c) for c in tb["cab"]]
        corpo = []
        for linha in tb.get("linhas") or []:
            valores = [str(c) for c in linha][: len(cab)] + [""] * max(0, len(cab) - len(linha))
            corpo.append([
                Paragraph(escape(v), vermelho if j == len(cab) - 1 and v == "FORA" else (celula if j == 0 else celula_centro))
                for j, v in enumerate(valores)
            ])
        partes.append(Paragraph(escape(str(tb.get("titulo") or "")), h))
        tabela = Table([[Paragraph(escape(c), cab_estilo) for c in cab], *corpo], colWidths=_larguras(len(cab)), repeatRows=1)
        tabela.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), azul), ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))  # fmt: skip
        partes.append(tabela)

    grafico = report.get("grafico")
    if isinstance(grafico, dict) and len(grafico.get("pts") or []) >= 2:
        partes += [Paragraph("Curva do ciclo de tratamento térmico", h),
                   Image(grafico_png(grafico), width=LARGURA_UTIL, height=LARGURA_UTIL * 3.5 / 7.4)]  # fmt: skip
    if report.get("obs"):
        partes += [Paragraph("Observações", h), Paragraph(escape(str(report["obs"])).replace("\n", "<br/>"), n)]

    responsavel = registro.responsavel or "-"
    partes += [Spacer(1, 10 * mm),
               Paragraph(f"Responsável pelo registro: <font name=\"{f['negrito']}\">{escape(responsavel)}</font> - "
                         f"{_quando(registro.quando)}", n),
               Spacer(1, 12 * mm)]  # fmt: skip
    qualidade = parametros.ler(db, "qualidade_responsavel", "")
    assinaturas = Table([["_______________________________", "_______________________________"],
                         ["Responsável / Inspetor", f"Qualidade - {qualidade}" if qualidade else "Qualidade"]],
                        colWidths=[LARGURA_UTIL / 2, LARGURA_UTIL / 2])  # fmt: skip
    assinaturas.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("FONTSIZE", (0, 0), (-1, -1), 8),
                                     ("FONTNAME", (0, 0), (-1, -1), f["normal"])]))  # fmt: skip
    partes.append(assinaturas)
    doc.build(partes)
    return buffer.getvalue()
