"""PDFs da Expedição: comprovante do envio a prestador externo e Ordem de Faturamento.

Mesma estrutura, textos e cálculos do sistema antigo (legado/app.py: _gerar_pdf_envio_prestador e _gerar_pdf_of).
Regras que não podem quebrar:
- O comprovante do envio pode sair junto com o material: NUNCA cita o cliente final (nem pelo parâmetro). O
  código da especificação vem do parâmetro `especificacao_codigo`.
- A OF é documento INTERNO: cita o cliente (o digitado na OF ou, sem ele, o parâmetro `cliente_nome`).
- Toda tabela da página tem a mesma largura total (LARGURA_UTIL = 186 mm).
"""
import io
from datetime import date, datetime
from xml.sax.saxutils import escape

from PIL import Image as ImagemPIL
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app import parametros
from app.arquivos import caminho_seguro
from app.expedicao import lote_com_qtd, peso, peso_sempre
from app.models import EnvioPrestadorFoto, OrdemFaturamento
from app.pdf_comum import LARGURA_UTIL, LOGO, empresa, fontes

AZUL = colors.HexColor("#5A7FA5")
CINZA_FUNDO = colors.HexColor("#F3F5F8")
CINZA_TEXTO = colors.HexColor("#555D6B")
AMARELO_TOTAL = colors.HexColor("#FFE9A8")
FUNDO_NATUREZA = {"cp": colors.HexColor("#E3F2FD"), "interno": colors.HexColor("#E8F5E9"), "pecas": colors.HexColor("#FFF3E0")}
NOME_STATUS = {
    "enviado": "ENVIADO", "retornado": "RETORNADO", "cancelado": "CANCELADO",
    "rascunho": "RASCUNHO", "emitida": "EMITIDA", "faturada": "FATURADA", "cancelada": "CANCELADA",
}  # fmt: skip


def _t(texto) -> str:
    """Texto seguro para o Paragraph do ReportLab (que interpreta marcação)."""
    return escape(str(texto if texto is not None else ""))


def _data(valor) -> str:
    if isinstance(valor, datetime | date):
        return valor.strftime("%d/%m/%Y")
    return "—"


class _Estilos:
    def __init__(self) -> None:
        f = fontes()
        # Com fonte TrueType, o <b> do Paragraph só funciona com a família registrada
        registerFontFamily(f["normal"], normal=f["normal"], bold=f["negrito"], italic=f["normal"], boldItalic=f["negrito"])
        self.n = ParagraphStyle("n", fontName=f["normal"], fontSize=8.5, leading=10)
        self.rotulo = ParagraphStyle("lb", parent=self.n, fontSize=6.3, textColor=CINZA_TEXTO, leading=7.5)
        self.valor = ParagraphStyle("vl", parent=self.n, fontSize=8, leading=9.5)
        self.titulo = ParagraphStyle("tt", parent=self.n, fontSize=11, textColor=AZUL, leading=13, alignment=1)
        self.secao = ParagraphStyle("h", parent=self.n, fontSize=8.5, textColor=AZUL, leading=10, spaceBefore=3, spaceAfter=1)
        self.nota = ParagraphStyle("nt", parent=self.n, fontSize=7.5, textColor=CINZA_TEXTO, leading=9, alignment=1)
        self.faixa = ParagraphStyle("fs", parent=self.n, fontSize=7, alignment=1)
        self.razao = ParagraphStyle("rs", parent=self.n, fontSize=7, leading=8.5)


def _grade(*extras, preenchimento: float = 3) -> TableStyle:
    return TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), preenchimento),
        ("BOTTOMPADDING", (0, 0), (-1, -1), preenchimento),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        *extras,
    ])  # fmt: skip


def _topo(db: Session, e: _Estilos, texto_faixa: str) -> list:
    """Faixa azul, logo e razão social/endereço (dos parâmetros)."""
    faixa = Table([[Paragraph(f'<font color="white">{texto_faixa}</font>', e.faixa)]], colWidths=[LARGURA_UTIL])
    faixa.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), AZUL), ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))  # fmt: skip
    dados_empresa = empresa(db)
    celula = [Paragraph(f"<b>{_t(dados_empresa['razao_social'])}</b>", e.razao)]
    celula += [Paragraph(_t(linha), e.rotulo) for linha in (dados_empresa["endereco"] or "").splitlines() if linha.strip()]
    if LOGO.is_file():
        cabecalho = Table([[Image(str(LOGO), width=24 * mm, height=24 * mm, kind="proportional"), celula]],
                          colWidths=[28 * mm, LARGURA_UTIL - 28 * mm])  # fmt: skip
    else:
        cabecalho = Table([[celula]], colWidths=[LARGURA_UTIL])
    cabecalho.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 1),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))  # fmt: skip
    return [faixa, Spacer(1, 1 * mm), cabecalho, Spacer(1, 2 * mm)]


def _identificacao(e: _Estilos, rotulos: list[str], valores: list[str]) -> Table:
    largura = LARGURA_UTIL / 3
    tabela = Table([[Paragraph(r, e.rotulo) for r in rotulos], [Paragraph(v, e.valor) for v in valores]],
                   colWidths=[largura] * 3)  # fmt: skip
    tabela.setStyle(_grade(("BACKGROUND", (0, 0), (-1, 0), CINZA_FUNDO), preenchimento=2))
    return tabela


def _dados(e: _Estilos, linhas: list[tuple[str, str]]) -> Table:
    tabela = Table([[Paragraph(r, e.rotulo), Paragraph(v, e.valor)] for r, v in linhas], colWidths=[45 * mm, LARGURA_UTIL - 45 * mm])
    tabela.setStyle(_grade(("BACKGROUND", (0, 0), (0, -1), CINZA_FUNDO)))
    return tabela


def _caixa(e: _Estilos, conteudo: str, fundo=None) -> Table:
    tabela = Table([[Paragraph(conteudo, e.valor)]], colWidths=[LARGURA_UTIL])
    estilo = [("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey), ("LEFTPADDING", (0, 0), (-1, -1), 8),
              ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 3),
              ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]  # fmt: skip
    if fundo is not None:
        estilo.append(("BACKGROUND", (0, 0), (-1, -1), fundo))
    tabela.setStyle(TableStyle(estilo))
    return tabela


def _tabela_lotes(linhas: list[list], larguras: list[float], ultima_mesclada: int, primeira_numerica: int) -> Table:
    """Tabela de lotes com cabeçalho cinza e linha de totais amarela (mesclada até `ultima_mesclada`)."""
    tabela = Table(linhas, colWidths=larguras)
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), CINZA_FUNDO),
        ("BACKGROUND", (0, -1), (-1, -1), AMARELO_TOTAL),
        ("SPAN", (0, -1), (ultima_mesclada, -1)),
        ("ALIGN", (0, -1), (ultima_mesclada, -1), "RIGHT"),
        ("ALIGN", (primeira_numerica, 0), (-1, -1), "CENTER"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))  # fmt: skip
    return tabela


def _documento(titulo: str, autor: str) -> tuple[io.BytesIO, SimpleDocTemplate]:
    saida = io.BytesIO()
    # 10 mm de margem + o respiro padrão do quadro (6 pt de cada lado) = os 186 mm das tabelas
    doc = SimpleDocTemplate(saida, pagesize=A4, leftMargin=10 * mm, rightMargin=10 * mm, topMargin=7 * mm, bottomMargin=6 * mm,
                            title=titulo, author=autor)  # fmt: skip
    return saida, doc


# ---------------------------------------------------------------- envio a prestador externo


def _lotes_do_envio(e: _Estilos, dados: dict) -> list:
    itens = dados["itens"]
    rotulo = lambda texto: Paragraph(f"<b>{texto}</b>", e.rotulo)  # noqa: E731
    v = lambda texto: Paragraph(_t(texto), e.valor)  # noqa: E731
    if dados["modo_pecas"]:
        # Revestimento / NDT / outro: 10 colunas e totais para o transporte
        titulos = ("OP", "Tipo", "Lote", "COD.", "Descrição", "Material", "Qtd lib.", "Vol.", "Peso líq.", "Peso bruto")
        linhas = [[rotulo(t) for t in titulos]]
        larguras = [14 * mm, 10 * mm, 22 * mm, 16 * mm, 36 * mm, 26 * mm, 14 * mm, 10 * mm, 18 * mm, 20 * mm]  # 186 mm
        total_qtd = total_vol = 0
        total_liq = total_bruto = 0.0
        for item in itens:
            qtd = item["qt_liberar"] or item["qtd"]  # sem qtd liberada, vale o lote inteiro
            total_qtd += qtd
            total_vol += item["volumes"]
            total_liq += item["peso_liq"]
            total_bruto += item["peso_bruto"]
            linhas.append([v(item["op"]), v(item["tipo"]), v(item["numero"] or "—"), v(item["coditem"] or "—"),
                           Paragraph(_t(item["descricao"] or "—"), e.rotulo), v(item["material"]), v(qtd), v(item["volumes"]),
                           v(peso(item["peso_liq"])), v(peso(item["peso_bruto"]))])  # fmt: skip
        b = lambda texto: Paragraph(f"<b>{_t(texto)}</b>", e.valor)  # noqa: E731
        linhas.append([b("Total"), "", "", "", "", "", b(total_qtd), b(total_vol), b(peso(total_liq)), b(peso(total_bruto))])
        titulo = Paragraph(f"<b>Lotes incluídos ({len(itens)})</b>  <font size='7' color='#555555'>— totais ao fim para fins de "
                           "transporte</font>", e.secao)  # fmt: skip
        return [titulo, _tabela_lotes(linhas, larguras, 5, 6)]
    # Ensaios mecânicos: OP, tipo, lote, material e os CPs de cada ensaio pedido
    total_t = sum(i["qt_cp_tracao"] for i in itens)
    total_i = sum(i["qt_cp_impacto"] for i in itens)
    mostrar_t = dados["mostrar_tracao"] and total_t > 0
    mostrar_i = dados["mostrar_charpy"] and total_i > 0
    cabecalho = [rotulo(t) for t in ("OP", "Tipo", "Lote", "Material")]
    if mostrar_t and mostrar_i:
        larguras = [24 * mm, 16 * mm, 36 * mm, 54 * mm, 24 * mm, 32 * mm]
    elif mostrar_t:
        larguras = [28 * mm, 18 * mm, 42 * mm, 72 * mm, 26 * mm]
    elif mostrar_i:
        larguras = [28 * mm, 18 * mm, 42 * mm, 64 * mm, 34 * mm]
    else:
        larguras = [32 * mm, 20 * mm, 48 * mm, 86 * mm]
    if mostrar_t:
        cabecalho.append(rotulo("CP Tração"))
    if mostrar_i:
        cabecalho.append(rotulo("CP Impacto Charpy"))
    linhas = [cabecalho]
    for item in itens:
        linha = [v(item["op"]), v(item["tipo"]), v(item["numero"] or "—"), v(item["material"])]
        if mostrar_t:
            linha.append(v(item["qt_cp_tracao"]))
        if mostrar_i:
            linha.append(v(item["qt_cp_impacto"]))
        linhas.append(linha)
    titulo = Paragraph(f"<b>Lotes incluídos ({len(itens)})</b>", e.secao)
    if not (mostrar_t or mostrar_i):
        tabela = Table(linhas, colWidths=larguras)
        tabela.setStyle(_grade(("BACKGROUND", (0, 0), (-1, 0), CINZA_FUNDO)))
        return [titulo, tabela]
    b = lambda texto: Paragraph(f"<b>{_t(texto)}</b>", e.valor)  # noqa: E731
    total = [b("Total"), "", "", ""] + ([b(total_t)] if mostrar_t else []) + ([b(total_i)] if mostrar_i else [])
    linhas.append(total)
    return [titulo, _tabela_lotes(linhas, larguras, 3, 4)]


def _coluna_especificacao(e: _Estilos, titulo: str, cor: str, norma: str, linhas: list) -> Table | None:
    if not linhas:
        return None
    conteudo = [[Paragraph(f"<font color='{cor}'><b>{titulo}</b></font>", e.rotulo),
                 Paragraph(f"<font size='6' color='#555555'>Norma de execução: <b>{norma}</b></font>", e.rotulo)]]  # fmt: skip
    conteudo += [[Paragraph(_t(rotulo), e.rotulo), Paragraph(f"<b>{_t(valor)}</b>", e.valor)] for rotulo, valor in linhas]
    tabela = Table(conteudo, colWidths=[36 * mm, 55 * mm])  # 91 mm: duas colunas + 4 mm de respiro = 186 mm
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FFF3C4")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("INNERGRID", (0, 1), (-1, -1), 0.3, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))  # fmt: skip
    return tabela


def _especificacao(e: _Estilos, especificacao: list, codigo: str) -> list:
    if not especificacao:
        return []
    norma = f"  <font size='7' color='#555555'>— Norma: <b>{_t(codigo)}</b></font>" if codigo else ""
    blocos: list = [Paragraph(f"<b>Especificação solicitada</b>{norma}", e.secao)]
    for sp in especificacao:
        faixa = Table([[Paragraph(f"<b>Tipo {_t(sp.get('tipo', ''))}</b> &middot; Material: {_t(sp.get('material', ''))}", e.valor)]],
                      colWidths=[LARGURA_UTIL])  # fmt: skip
        faixa.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFE082")),
                                   ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey), ("LEFTPADDING", (0, 0), (-1, -1), 6),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 2),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))  # fmt: skip
        blocos.append(faixa)
        if sp.get("vazio") or not (sp.get("tracao") or sp.get("charpy")):
            blocos += [Paragraph("<i>Nenhuma especificação cadastrada para este tipo.</i>", e.valor), Spacer(1, 1.5 * mm)]
            continue
        tracao = _coluna_especificacao(e, "TRAÇÃO", "#1565c0", "ASTM A370", sp.get("tracao") or [])
        charpy = _coluna_especificacao(e, "IMPACTO CHARPY", "#c62828", "ASTM E23", sp.get("charpy") or [])
        if tracao and charpy:
            # Coluna de respiro de 4 mm (e não padding): a borda direita fica alinhada às outras tabelas
            duas = Table([[tracao, "", charpy]], colWidths=[91 * mm, 4 * mm, 91 * mm])
            duas.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                      ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                                      ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))  # fmt: skip
            blocos.append(duas)
        else:
            blocos.append(tracao or charpy)
        blocos.append(Spacer(1, 1.5 * mm))
    blocos.append(Spacer(1, 1 * mm))
    return blocos


def _fotos(db: Session, e: _Estilos, dados: dict) -> list:
    """Miniaturas lado a lado em 4 colunas, para caber numa página."""
    miniaturas, linha = [], []
    colunas, largura = 4, LARGURA_UTIL / 4
    for foto in dados["fotos"]:
        registro = db.get(EnvioPrestadorFoto, foto["id"])
        caminho = caminho_seguro(registro.arquivo) if registro else None
        if caminho is None:
            continue
        try:
            with ImagemPIL.open(caminho) as imagem:
                w, h = imagem.size
            proporcao = h / w if w else 0.75
        except (OSError, ValueError):
            continue
        caixa_w = 43 * mm
        caixa_h = min(caixa_w * proporcao, 32 * mm)
        linha.append(Image(str(caminho), width=caixa_w, height=caixa_h, kind="proportional"))
        if len(linha) == colunas:
            miniaturas.append(linha)
            linha = []
    if linha:
        miniaturas.append(linha + [""] * (colunas - len(linha)))
    if not miniaturas:
        return []
    tabela = Table(miniaturas, colWidths=[largura] * colunas)
    tabela.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.3, colors.lightgrey), ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
                                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 1), ("RIGHTPADDING", (0, 0), (-1, -1), 1),
                                ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))  # fmt: skip
    return [Paragraph(f"<b>{_t(dados['rotulo_fotos'])}</b>", e.secao), tabela, Spacer(1, 2 * mm)]


def pdf_envio(db: Session, dados: dict) -> bytes:
    """Comprovante interno do envio (não substitui a solicitação no modelo oficial do prestador). Sem o cliente final."""
    e = _Estilos()
    razao = parametros.ler(db, "empresa_razao_social")
    saida, doc = _documento(f"Envio {dados['numero']}", razao)
    st: list = _topo(db, e, "<b>DOCUMENTO CONFIDENCIAL</b> — USO INTERNO")
    emissao = dados.get("data_emissao") or (dados["criado_em"].date() if dados.get("criado_em") else None)
    st += [_identificacao(e, ["Nº DO ENVIO", "DATA DE EMISSÃO", "DATA DE ENVIO"],
                          [f"<b>{_t(dados['numero'])}</b>", _data(emissao), _data(dados.get("data_envio"))]),
           Spacer(1, 2 * mm), Paragraph("SOLICITAÇÃO DE ENVIO A PRESTADOR EXTERNO", e.titulo), Spacer(1, 2 * mm)]  # fmt: skip

    linhas = [
        ("Prestador", f"<b>{_t(dados['prestador'] or '—')}</b>"),
        ("Tipo de serviço", _t(dados["tipo_servico"] or "—")),
        ("Responsável pelo envio", _t(dados["responsavel"] or "—")),
        ("Status atual", NOME_STATUS.get(dados["status"], _t(dados["status"]))),
    ]
    if dados.get("data_retorno"):
        linhas.append(("Data de retorno", _data(dados["data_retorno"])))
    st += [Paragraph("<b>Dados do envio</b>", e.secao), _dados(e, linhas), Spacer(1, 2 * mm)]

    natureza = dados["natureza"]
    st += [_caixa(e, f"<b>Natureza do envio:</b> {_t(natureza['texto'])}", FUNDO_NATUREZA.get(natureza["classe"], CINZA_FUNDO)),
           Spacer(1, 2 * mm)]  # fmt: skip
    st += [*_lotes_do_envio(e, dados), Spacer(1, 2 * mm)]
    # Especificação congelada no envio; o código vem do parâmetro (nunca o nome do cliente)
    st += _especificacao(e, dados.get("especificacao") or [], parametros.ler(db, "especificacao_codigo").strip())
    if dados.get("observacoes"):
        st += [Paragraph("<b>Observações</b>", e.secao), _caixa(e, _t(dados["observacoes"]).replace("\n", "<br/>")), Spacer(1, 2 * mm)]
    st += _fotos(db, e, dados)

    st.append(Spacer(1, 18 * mm))
    assinaturas = Table([[
        Paragraph(f"___________________________________<br/><b>Responsável pelo envio</b><br/>{_t(dados['responsavel'])}", e.valor),
        Paragraph("___________________________________<br/><b>Recebido pelo prestador</b><br/>(data / assinatura / carimbo)", e.valor),
    ]], colWidths=[LARGURA_UTIL / 2] * 2)  # fmt: skip
    assinaturas.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                                     ("VALIGN", (0, 0), (-1, -1), "TOP")]))  # fmt: skip
    st += [assinaturas, Spacer(1, 2 * mm),
           Paragraph("Este comprovante é um registro interno da AçoKorte para rastreabilidade do envio. Não substitui a "
                     "solicitação formal do laboratório/revestedor, que é preenchida e enviada no modelo oficial do "
                     "prestador.", e.nota)]  # fmt: skip
    doc.build(st)
    return saida.getvalue()


# ---------------------------------------------------------------- ordem de faturamento


def pdf_of(db: Session, of: OrdemFaturamento, itens: list[dict]) -> bytes:
    """Ordem de Faturamento: documento INTERNO para a Expedição/Faturamento (não é NF)."""
    e = _Estilos()
    razao = parametros.ler(db, "empresa_razao_social")
    saida, doc = _documento(f"OF {of.numero}", razao)
    st: list = _topo(db, e, "<b>DOCUMENTO INTERNO</b> — ORDEM DE FATURAMENTO")
    st += [_identificacao(e, ["Nº DA OF", "DATA DE EMISSÃO", "PEDIDO DO CLIENTE"],
                          [f"<b>{_t(of.numero)}</b>", _data(of.data_emissao), _t(of.pedido_cliente or "—")]),
           Spacer(1, 2 * mm), Paragraph("ORDEM DE FATURAMENTO", e.titulo), Spacer(1, 2 * mm)]  # fmt: skip
    cliente = of.cliente or parametros.ler(db, "cliente_nome") or "—"
    st += [_dados(e, [
        ("Cliente", f"<b>{_t(cliente)}</b>"),
        ("Pedido (PIV)", f"<b>{_t(of.piv or '—')}</b>"),
        ("Destinatário / NF", f"{_t(of.destinatario or '—')} &middot; NF: {_t(of.nf_saida or '—')}"),
        ("Status", NOME_STATUS.get(of.status, _t(of.status))),
    ]), Spacer(1, 3 * mm)]  # fmt: skip

    rotulo = lambda texto: Paragraph(f"<b>{texto}</b>", e.rotulo)  # noqa: E731
    v = lambda texto: Paragraph(_t(texto), e.valor)  # noqa: E731
    b = lambda texto: Paragraph(f"<b>{_t(texto)}</b>", e.valor)  # noqa: E731
    linhas = [[rotulo(t) for t in ("OP", "Tipo", "Nº do lote", "COD.", "Descrição", "Qtd lote", "Qtd lib.", "Vol.", "Peso líq.",
                                   "Peso bruto")]]  # fmt: skip
    larguras = [14 * mm, 10 * mm, 38 * mm, 14 * mm, 34 * mm, 12 * mm, 12 * mm, 8 * mm, 20 * mm, 24 * mm]  # 186 mm
    total_lote = total_lib = total_vol = 0
    total_liq = total_bruto = 0.0
    for item in itens:
        # Nº completo do lote + quantidade total entre parênteses, com o ano/trimestre da emissão da OF
        linhas.append([v(item["op"]), v(item["tipo"]), v(lote_com_qtd(item["numero"], item["qtd"], of.data_emissao)),
                       v(item["coditem"] or "—"), Paragraph(_t(item["descricao"] or "—"), e.rotulo), v(item["qtd"]),
                       v(item["qtd_faturada"]), v(item["volumes"]), v(peso_sempre(item["peso_liq"])),
                       v(peso_sempre(item["peso_bruto"]))])  # fmt: skip
        total_lote += item["qtd"]
        total_lib += item["qtd_faturada"]
        total_vol += item["volumes"]
        total_liq += item["peso_liq"]
        total_bruto += item["peso_bruto"]
    linhas.append([b("Totais"), "", "", "", "", b(total_lote), b(total_lib), b(total_vol), b(peso_sempre(total_liq)),
                   b(peso_sempre(total_bruto))])  # fmt: skip
    tabela = Table(linhas, colWidths=larguras)
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), CINZA_FUNDO),
        ("BACKGROUND", (0, -1), (-1, -1), AMARELO_TOTAL),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("SPAN", (0, -1), (4, -1)),
        ("ALIGN", (0, -1), (4, -1), "RIGHT"),
    ]))  # fmt: skip
    st += [Paragraph(f"<b>Itens da ordem ({len(itens)})</b>", e.secao), tabela, Spacer(1, 2 * mm)]
    if of.observacoes:
        st += [Paragraph("<b>Observações</b>", e.secao), _caixa(e, _t(of.observacoes).replace("\n", "<br/>")), Spacer(1, 2 * mm)]
    st.append(Spacer(1, 18 * mm))
    assinaturas = Table([[
        Paragraph("___________________________________<br/><b>Qualidade</b> (liberação)", e.valor),
        Paragraph("___________________________________<br/><b>PCP / Expedição</b>", e.valor),
        Paragraph("___________________________________<br/><b>Faturamento</b>", e.valor),
    ]], colWidths=[LARGURA_UTIL / 3] * 3)  # fmt: skip
    assinaturas.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 4)]))
    st += [assinaturas, Spacer(1, 4 * mm),
           Paragraph("Documento interno da AçoKorte — ordem de preparação pra Expedição / Faturamento. "
                     "Não substitui a NF-e, que é emitida após esta ordem.", e.nota)]  # fmt: skip
    doc.build(st)
    return saida.getvalue()
