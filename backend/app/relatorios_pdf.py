"""PDFs dos relatórios gerados pelo próprio sistema: Dureza HRC (RIP-35), Tratamento Térmico e Inspeção Visual.

Porte de legado/relatorios_sistema.py, com o mesmo padrão visual: faixa azul de confidencialidade, logo, razão
social e endereço, caixa com Nº do laudo / data de emissão / PO, bloco de identificação, 2 assinaturas
(Executado por / Aprovado por, com a imagem da assinatura digital) e rodapé com o código do documento.

Regras (ver pdf_comum.py):
- Os códigos de documento (FOR-TT-IS.8.5-06-8, FOR-DUR-RIP-35, FOR-VIS-IS-100.1-F) são copiados EXATAMENTE.
- Todas as tabelas de uma página têm a mesma largura total (LARGURA_UTIL).
- Nada aqui lê o banco: quem chama monta os dados (cliente, especificação, assinaturas). Assim os PDFs podem ser
  testados sozinhos.
- Diferença do antigo: a razão social e o endereço vêm dos parâmetros (o antigo tinha no código) e, quando o
  conteúdo não cabe numa página (muitos corpos de prova), a tabela continua na página seguinte.
"""
import io
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.pdf_comum import LARGURA_UTIL, LOGO, fontes

# ---- Paleta (azul suave, a pedido da Qualidade: "não pesar no arquivo final") ----
AZUL = colors.HexColor("#5A7FA5")
PRETO = colors.HexColor("#1B2430")
CINZA = colors.HexColor("#555D6B")
VERDE = colors.HexColor("#1e8a4c")
VERMELHO = colors.HexColor("#c0392b")
BORDA = colors.HexColor("#C5CCD6")
CINZA_FUNDO = colors.HexColor("#F3F5F8")
FUNDO_VAZIO = colors.HexColor("#FAFAFA")
FUNDO_APROVADO = colors.HexColor("#E3F4EA")
FUNDO_REPROVADO = colors.HexColor("#FBE7E4")

# Código do formulário / revisão / procedimento interno de cada relatório (copiar exatamente, nunca "arrumar")
DOC_TT = {"codigo": "FOR-TT-IS.8.5-06-8", "rev": "00", "proc": "IT-TT-IS 8.5-06"}
DOC_DUR = {"codigo": "FOR-DUR-RIP-35", "rev": "00", "proc": "IS.8.5-06-8 Rev.00"}
DOC_VIS = {"codigo": "FOR-VIS-IS-100.1-F", "rev": "00", "proc": "IS.100.1-F Rev.00"}

LARGURA, ALTURA = A4
MARGEM = (LARGURA - LARGURA_UTIL) / 2  # ~12 mm de cada lado
X0 = MARGEM
LIMITE_RODAPE = 18 * mm  # nada desce abaixo disto (o rodapé fica em 12 mm)
TOPO_ASSINATURAS = 48 * mm  # as assinaturas ocupam de 48 mm até 20 mm, na última página

_ITALICO = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
    "C:/Windows/Fonts/ariali.ttf",
]
_fontes_relatorio: dict[str, str] | None = None


def _f() -> dict[str, str]:
    """Fontes com acento: normal, negrito e itálico (sem itálico instalado, usa a normal)."""
    global _fontes_relatorio
    if _fontes_relatorio is None:
        base = dict(fontes())
        base["italico"] = "Helvetica-Oblique" if base["normal"] == "Helvetica" else base["normal"]
        if base["normal"] != "Helvetica":
            for caminho in _ITALICO:
                if Path(caminho).is_file():
                    pdfmetrics.registerFont(TTFont("AcoKey-italico", caminho))
                    base["italico"] = "AcoKey-italico"
                    break
        _fontes_relatorio = base
    return _fontes_relatorio


def numero_br(valor: float | int | None, casas: int = 1) -> str:
    """36.0 -> '36,0'"""
    if not isinstance(valor, int | float):
        return "—"
    return f"{valor:.{casas}f}".replace(".", ",")


def calcular_status_dureza(valores: Iterable[float], esp_min: float | None, esp_max: float | None) -> str:
    """'APROVADO' / 'REPROVADO' / '' (sem leitura ou sem especificação). Todas as leituras precisam estar na faixa."""
    nums = [v for v in valores if isinstance(v, int | float)]
    if not nums or esp_min is None or esp_max is None:
        return ""
    return "APROVADO" if (min(nums) >= esp_min and max(nums) <= esp_max) else "REPROVADO"


def laudo_numero(prefixo: str, data_emissao: str, op: str) -> str:
    """Nº do laudo = PREFIXO-ANO-OP. O ano vem da data informada no formulário (dd/mm/aaaa), não do relógio."""
    cauda = (data_emissao or "")[-4:]
    ano = cauda if cauda.isdigit() and len(cauda) == 4 else str(datetime.now().year)
    return f"{prefixo}-{ano}-{op}"


# ---------------------------------------------------------------- peças de desenho


def _celula(c, x, y_topo, w, h, texto="", *, negrito=False, tamanho=9.0, fundo=None, alinhar="E", cor=PRETO,
            encolher=False, minimo=5.5, fonte=None) -> None:  # fmt: skip
    """Célula com borda. y_topo é a borda de CIMA (a célula ocupa de y_topo - h até y_topo)."""
    c.setStrokeColor(BORDA)
    c.setLineWidth(0.4)
    if fundo is not None:
        c.setFillColor(fundo)
        c.rect(x, y_topo - h, w, h, fill=1, stroke=1)
    else:
        c.rect(x, y_topo - h, w, h, fill=0, stroke=1)
    txt = str(texto if texto is not None else "")
    if not txt:
        return
    nome = fonte or (_f()["negrito"] if negrito else _f()["normal"])
    if encolher:
        while tamanho > minimo and c.stringWidth(txt, nome, tamanho) > w - 4 * mm:
            tamanho -= 0.3
    c.setFont(nome, tamanho)
    c.setFillColor(cor)
    ty = y_topo - h / 2 - tamanho * 0.35
    if alinhar == "C":
        c.drawCentredString(x + w / 2, ty, txt)
    elif alinhar == "D":
        c.drawRightString(x + w - 2 * mm, ty, txt)
    else:
        c.drawString(x + 2 * mm, ty, txt)


ENTRELINHA = 3.6 * mm


def _celula_linhas(c, x, y_topo, w, h, linhas: list[str], *, tamanho=8.5) -> None:
    """Célula com borda e várias linhas de texto (já quebradas na largura), centradas na altura."""
    _celula(c, x, y_topo, w, h)
    c.setFont(_f()["normal"], tamanho)
    c.setFillColor(PRETO)
    centro = y_topo - h / 2
    for i, linha in enumerate(linhas):
        c.drawString(x + 2 * mm, centro + (len(linhas) - 1) * ENTRELINHA / 2 - i * ENTRELINHA - tamanho * 0.35, linha)


def _titulo_secao(c, y, texto, h=7 * mm, alinhar="C") -> float:
    _celula(c, X0, y, LARGURA_UTIL, h, texto, negrito=True, tamanho=8, alinhar=alinhar, fundo=AZUL, cor=colors.white)
    return y - h


def _legenda(c, x_centro, y, texto, tamanho=8.0) -> None:
    c.setFont(_f()["italico"], tamanho)
    c.setFillColor(CINZA)
    c.drawCentredString(x_centro, y, texto)


def _imagem(c, caminho: Path | None, x, y_baixo, w, h, *, vazio: str, invalido: str, moldura=False) -> None:
    """Imagem centrada na caixa, sem distorcer. Sem imagem (ou imagem inválida): caixa com o aviso."""
    if caminho:
        try:
            c.drawImage(ImageReader(str(caminho)), x, y_baixo, w, h, preserveAspectRatio=True, anchor="c", mask="auto")
            if moldura:
                c.setStrokeColor(BORDA)
                c.setLineWidth(0.4)
                c.rect(x, y_baixo, w, h, fill=0, stroke=1)
            return
        except Exception:  # imagem corrompida não pode derrubar o relatório inteiro
            _celula(c, x, y_baixo + h, w, h, invalido, tamanho=8.5, alinhar="C", cor=CINZA)
            return
    _celula(c, x, y_baixo + h, w, h, vazio, tamanho=8.5, alinhar="C", cor=CINZA, fundo=FUNDO_VAZIO)


def cabecalho(c, empresa: dict, titulo: str, subtitulo: str, doc: dict, pagina: int, total: int | str,
              laudo: str, data_emissao: str, po: str = "—") -> float:  # fmt: skip
    """Cabeçalho padrão dos 3 relatórios. Devolve o y onde o conteúdo começa."""
    f = _f()
    w, h = LARGURA, ALTURA
    c.setFillColor(AZUL)
    c.rect(0, h - 10 * mm, w, 10 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont(f["negrito"], 8)
    c.drawString(X0, h - 7 * mm, "DOCUMENTO CONFIDENCIAL — USO INTERNO E CLIENTE")
    c.drawRightString(w - MARGEM, h - 7 * mm, f"{doc['codigo']}  |  Rev. {doc['rev']}  |  Pág. {pagina}/{total}")

    if LOGO.is_file():
        try:
            c.drawImage(ImageReader(str(LOGO)), X0, h - 30 * mm, 28 * mm, 18 * mm, preserveAspectRatio=True, anchor="w",
                        mask="auto")  # fmt: skip
        except Exception:
            pass

    caixa_w = 60 * mm
    cx = w - MARGEM - caixa_w
    x_texto = X0 + 32 * mm
    c.setFont(f["negrito"], 8.5)
    c.setFillColor(PRETO)
    c.drawString(x_texto, h - 18 * mm, empresa.get("razao_social") or "")
    linhas: list[str] = []
    for parte in (empresa.get("endereco") or "").splitlines():
        linhas += simpleSplit(parte.strip(), f["normal"], 7, cx - x_texto - 3 * mm)
    c.setFont(f["normal"], 7)
    c.setFillColor(CINZA)
    for i, linha in enumerate(linhas[:2]):
        c.drawString(x_texto, h - (22 + 3.5 * i) * mm, linha)

    topo = h - 13 * mm
    altura = 20 * mm
    c.setStrokeColor(BORDA)
    c.setLineWidth(0.4)
    c.rect(cx, topo - altura, caixa_w, altura, fill=0, stroke=1)
    c.line(cx, topo - 12 * mm, cx + caixa_w, topo - 12 * mm)
    c.line(cx + caixa_w / 2, topo, cx + caixa_w / 2, topo - 12 * mm)
    c.setFont(f["normal"], 6.5)
    c.setFillColor(CINZA)
    c.drawString(cx + 2 * mm, topo - 3 * mm, "Nº DO LAUDO")
    c.drawString(cx + caixa_w / 2 + 2 * mm, topo - 3 * mm, "DATA DE EMISSÃO")
    c.setFont(f["negrito"], 9)
    c.setFillColor(PRETO)
    tamanho = 9.0
    while tamanho > 6 and c.stringWidth(laudo, f["negrito"], tamanho) > caixa_w / 2 - 3 * mm:
        tamanho -= 0.5
    c.setFont(f["negrito"], tamanho)
    c.drawString(cx + 2 * mm, topo - 9 * mm, laudo)
    c.setFont(f["negrito"], 9)
    c.drawString(cx + caixa_w / 2 + 2 * mm, topo - 9 * mm, data_emissao or "—")
    c.setFont(f["normal"], 6.5)
    c.setFillColor(CINZA)
    c.drawString(cx + 2 * mm, topo - 15 * mm, "PEDIDO CLIENTE (PO)")
    c.setFont(f["normal"], 9)
    c.setFillColor(PRETO)
    c.drawString(cx + 2 * mm, topo - 19 * mm, po or "—")

    c.setFont(f["negrito"], 13.5)
    c.setFillColor(AZUL)
    c.drawCentredString(w / 2, h - 42 * mm, titulo)
    c.setFont(f["normal"], 10)
    c.setFillColor(CINZA)
    c.drawCentredString(w / 2, h - 47 * mm, subtitulo)
    c.setStrokeColor(AZUL)
    c.setLineWidth(1)
    c.line(X0, h - 50 * mm, w - MARGEM, h - 50 * mm)
    return h - 53 * mm


def bloco_identificacao(c, y, campos: list[tuple[str, str]]) -> float:
    """Grade de 3 colunas com os dados do lote e da peça. Valor que não cabe tem a fonte reduzida."""
    f = _f()
    lin_h = 7 * mm
    col_w = LARGURA_UTIL / 3
    y = _titulo_secao(c, y, "IDENTIFICAÇÃO")
    for i, (rotulo, valor) in enumerate(campos):
        x = X0 + (i % 3) * col_w
        topo = y - (i // 3) * lin_h
        _celula(c, x, topo, col_w, lin_h, fundo=colors.white)
        c.setFont(f["normal"], 6.5)
        c.setFillColor(CINZA)
        c.drawString(x + 2 * mm, topo - 2.5 * mm, rotulo)
        texto = str(valor) if valor not in (None, "") else "—"
        tamanho = 8.5
        while tamanho > 6 and c.stringWidth(texto, f["negrito"], tamanho) > col_w - 4 * mm:
            tamanho -= 0.5
        c.setFont(f["negrito"], tamanho)
        c.setFillColor(PRETO)
        c.drawString(x + 2 * mm, topo - lin_h + 1.5 * mm, texto)
    linhas = (len(campos) + 2) // 3
    return y - linhas * lin_h - 2 * mm


def bloco_assinaturas(c, y, executado: dict, aprovado: dict) -> None:
    """Executado por / Aprovado por (só na última página). 'assinatura' = Path da imagem, se houver."""
    f = _f()
    col_w = LARGURA_UTIL / 2
    y = _titulo_secao(c, y, "RESPONSÁVEIS", h=6 * mm)
    for i, (rotulo, dados) in enumerate([("EXECUTADO POR", executado), ("APROVADO POR", aprovado)]):
        x = X0 + i * col_w
        _celula(c, x, y, col_w, 22 * mm, fundo=colors.white)
        c.setFont(f["normal"], 6.5)
        c.setFillColor(CINZA)
        c.drawString(x + 2 * mm, y - 4 * mm, rotulo)
        caminho = dados.get("assinatura")
        if caminho and Path(caminho).is_file():
            try:
                imagem = ImageReader(str(caminho))
                iw, ih = imagem.getSize()
                escala = min((col_w - 4 * mm) / iw, 8 * mm / ih)
                tw, th = iw * escala, ih * escala
                # a base encosta na linha da assinatura, sem invadir o rótulo nem o nome
                c.drawImage(imagem, x + (col_w - tw) / 2, y - 13 * mm, width=tw, height=th, mask="auto")
            except Exception:
                pass
        c.setStrokeColor(BORDA)
        c.line(x + 3 * mm, y - 13 * mm, x + col_w - 3 * mm, y - 13 * mm)
        c.setFont(f["negrito"], 8.5)
        c.setFillColor(PRETO)
        c.drawString(x + 3 * mm, y - 16 * mm, dados.get("nome") or "—")
        c.setFont(f["normal"], 7.5)
        c.setFillColor(CINZA)
        c.drawString(x + 3 * mm, y - 19 * mm, dados.get("cargo") or "")
        c.drawString(x + 3 * mm, y - 21.5 * mm, f"Data: {dados.get('data') or ''}")


def rodape(c, doc: dict, referencia: str, data_emissao: str = "") -> None:
    f = _f()
    c.setStrokeColor(BORDA)
    c.setLineWidth(0.4)
    c.line(X0, 12 * mm, LARGURA - MARGEM, 12 * mm)
    emissao = data_emissao or datetime.now().strftime("%d/%m/%Y")
    texto = (f"Este documento é parte integrante do databook. Reprodução não autorizada vedada. "
             f"{doc['codigo']} | Rev. {doc['rev']} | Emitido em {emissao} | {referencia}")  # fmt: skip
    tamanho = 7.0
    while tamanho > 5 and c.stringWidth(texto, f["italico"], tamanho) > LARGURA_UTIL:
        tamanho -= 0.25
    c.setFont(f["italico"], tamanho)
    c.setFillColor(CINZA)
    c.drawString(X0, 8 * mm, texto)


def _gerar(desenhar: Callable[[canvas.Canvas, int | str], None]) -> bytes:
    """Desenha duas vezes: a primeira só para contar as páginas (o cabeçalho mostra 'Pág. 1/2')."""
    rascunho = canvas.Canvas(io.BytesIO(), pagesize=A4)
    desenhar(rascunho, "?")
    total = rascunho.getPageNumber() - 1  # cada desenho termina com showPage(): o contador já está na seguinte
    saida = io.BytesIO()
    c = canvas.Canvas(saida, pagesize=A4)
    c.setTitle("Relatório")
    desenhar(c, total)
    c.save()
    return saida.getvalue()


# ---------------------------------------------------------------- Dureza HRC (RIP-35)

COLUNAS_DUREZA = [("Identificação do CP", 0.20), ("Nº Peça", 0.08), ("P1", 0.08), ("P2", 0.08), ("P3", 0.08), ("P4", 0.08),
                  ("P5", 0.08), ("Média", 0.10), ("Faixa (mín–máx)", 0.11), ("Status", 0.11)]  # fmt: skip
METODO_PADRAO = "Medição direta, com carga de 150 Kg e Cone de Diamante 120°"


def _cor_status(status: str):
    s = (status or "").upper()
    return VERDE if s == "APROVADO" else (VERMELHO if s == "REPROVADO" else CINZA)


def gerar_pdf_dureza(lote: dict, dados: dict, empresa: dict, imagem_pontos: Path | None) -> bytes:
    """Relatório de Ensaio de Dureza Rockwell C (RIP-35).

    lote: op, lote (número), tipo, coditem.
    dados: cliente, padrao_aceitacao, nome_peca, desenho, material, po, especificacao, esp_min, esp_max,
        leituras [{cp, peca, valores, status}], equipamento (texto), norma/metodo/preparacao (opcionais),
        inspecionado_por, aprovado_por, data (dd/mm/aaaa = emissão), data_execucao, data_aprovacao,
        assinatura_executado / assinatura_aprovado (Path ou None).
    """
    data_emissao = dados.get("data", "")
    laudo = laudo_numero("DUR", data_emissao, lote.get("op", ""))
    referencia = f"OP {lote.get('op', '')} / Lote {lote.get('lote', '')}"
    leituras = dados.get("leituras") or []
    larguras = [LARGURA_UTIL * fr for _, fr in COLUNAS_DUREZA]
    lin_h = 6.5 * mm

    def desenhar(c: canvas.Canvas, total: int | str) -> None:
        pagina = 1

        def nova_pagina() -> float:
            nonlocal pagina
            rodape(c, DOC_DUR, referencia, data_emissao)
            c.showPage()
            pagina += 1
            return topo_pagina()

        def topo_pagina() -> float:
            return cabecalho(c, empresa, "RELATÓRIO DE ENSAIO DE DUREZA ROCKWELL C", "Formulário RIP-35 — Norma ASTM E18",
                             DOC_DUR, pagina, total, laudo, data_emissao, dados.get("po"))  # fmt: skip

        def cabecalho_tabela(y: float) -> float:
            y = _titulo_secao(c, y, "VALORES ENCONTRADOS (HRc)", h=lin_h)
            x = X0
            for (nome, _), lw in zip(COLUNAS_DUREZA, larguras, strict=True):
                _celula(c, x, y, lw, lin_h, nome, negrito=True, tamanho=7.5, alinhar="C", fundo=CINZA_FUNDO)
                x += lw
            return y - lin_h

        y = topo_pagina()
        n_pontos = sum(len(r.get("valores") or []) for r in leituras)
        y = bloco_identificacao(c, y, [
            ("Cliente", dados.get("cliente", "")),
            ("Padrão de Aceitação", dados.get("padrao_aceitacao", "")),
            ("Item", dados.get("nome_peca", "")),
            ("Código do Item", lote.get("coditem", "")),
            ("Desenho / Revisão", dados.get("desenho", "")),
            ("Material", dados.get("material", "")),
            ("OP", lote.get("op", "")),
            ("Lote", lote.get("lote", "")),
            ("Qtd. Inspecionada", f"{len(leituras) or 1} CP(s) / {n_pontos} pontos"),
        ])  # fmt: skip

        # Figura dos pontos de medição. A do ARK tem a foto e o desenho lado a lado: ocupa a largura da página.
        img_h, img_w = 30 * mm, (LARGURA_UTIL if lote.get("tipo") == "ARK" else 90 * mm)
        if imagem_pontos and imagem_pontos.is_file():
            try:
                c.drawImage(ImageReader(str(imagem_pontos)), X0 + (LARGURA_UTIL - img_w) / 2, y - img_h, img_w, img_h,
                            preserveAspectRatio=True, anchor="c", mask="auto")  # fmt: skip
            except Exception:
                pass
        y -= img_h + 2 * mm
        _legenda(c, LARGURA / 2, y - 1 * mm, "Figura 1 — Pontos de medição na peça")
        y -= 5 * mm

        y = cabecalho_tabela(y)
        todos: list[float] = []
        for indice in range(max(len(leituras), 1)):
            if y - lin_h < LIMITE_RODAPE:
                y = cabecalho_tabela(nova_pagina())
            reg = leituras[indice] if indice < len(leituras) else {}
            valores = [v for v in reg.get("valores") or [] if isinstance(v, int | float)]
            todos.extend(valores)
            x = X0
            _celula(c, x, y, larguras[0], lin_h, reg.get("cp", ""), tamanho=8.5, alinhar="C", encolher=True)
            x += larguras[0]
            _celula(c, x, y, larguras[1], lin_h, reg.get("peca", ""), tamanho=8.5, alinhar="C", encolher=True)
            x += larguras[1]
            for i in range(5):
                _celula(c, x, y, larguras[i + 2], lin_h, numero_br(valores[i]) if i < len(valores) else "", tamanho=8.5,
                        alinhar="C")  # fmt: skip
                x += larguras[i + 2]
            media = numero_br(sum(valores) / len(valores)) if valores else "—"
            faixa = f"{numero_br(min(valores))}–{numero_br(max(valores))}" if valores else "—"
            _celula(c, x, y, larguras[7], lin_h, media, negrito=True, tamanho=8.5, alinhar="C")
            x += larguras[7]
            _celula(c, x, y, larguras[8], lin_h, faixa, tamanho=8.5, alinhar="C")
            x += larguras[8]
            status = reg.get("status", "")
            _celula(c, x, y, larguras[9], lin_h, status, negrito=True, tamanho=8.5, alinhar="C", cor=_cor_status(status))
            y -= lin_h

        if todos:  # estatística da amostra: todas as leituras de todas as peças
            if y - lin_h < LIMITE_RODAPE:
                y = cabecalho_tabela(nova_pagina())
            geral = calcular_status_dureza(todos, dados.get("esp_min"), dados.get("esp_max"))
            x = X0
            _celula(c, x, y, larguras[0], lin_h, "Estatística da amostra", negrito=True, tamanho=8.5, fundo=CINZA_FUNDO,
                    encolher=True)  # fmt: skip
            x += larguras[0]
            for lw in larguras[1:7]:
                _celula(c, x, y, lw, lin_h, fundo=CINZA_FUNDO)
                x += lw
            _celula(c, x, y, larguras[7], lin_h, numero_br(sum(todos) / len(todos)), negrito=True, tamanho=8.5, alinhar="C",
                    fundo=CINZA_FUNDO)  # fmt: skip
            x += larguras[7]
            _celula(c, x, y, larguras[8], lin_h, f"{numero_br(min(todos))}–{numero_br(max(todos))}", negrito=True,
                    tamanho=8.5, alinhar="C", fundo=CINZA_FUNDO)  # fmt: skip
            x += larguras[8]
            _celula(c, x, y, larguras[9], lin_h, geral, negrito=True, tamanho=8.5, alinhar="C", cor=_cor_status(geral),
                    fundo=CINZA_FUNDO)  # fmt: skip
            y -= lin_h
        y -= 4 * mm

        especificacao = dados.get("especificacao", "")
        linhas_metodo = [
            ("Norma de referência", dados.get("norma") or "ASTM E18"),
            ("Método do ensaio", dados.get("metodo") or METODO_PADRAO),
            ("Preparação da superfície", dados.get("preparacao") or "Superfície Retificada"),
            ("Critério de aceitação", f"Especificado {especificacao}" if especificacao else "—"),
            ("Procedimento interno", DOC_DUR["proc"]),
            ("Equipamento", dados.get("equipamento") or "—"),
        ]
        col_rotulo = LARGURA_UTIL * 0.28
        col_valor = LARGURA_UTIL - col_rotulo
        blocos = [(rotulo, simpleSplit(str(valor), _f()["normal"], 8.5, col_valor - 4 * mm) or [""])
                  for rotulo, valor in linhas_metodo]  # fmt: skip
        alturas = [max(lin_h, len(linhas) * ENTRELINHA + 2.8 * mm) for _, linhas in blocos]
        if y - lin_h - sum(alturas) < TOPO_ASSINATURAS + 2 * mm:
            y = nova_pagina()
        y = _titulo_secao(c, y, "MÉTODO, CRITÉRIO E EQUIPAMENTO", h=lin_h)
        for (rotulo, linhas), altura in zip(blocos, alturas, strict=True):
            _celula(c, X0, y, col_rotulo, altura, rotulo, negrito=True, tamanho=8.5, fundo=CINZA_FUNDO)
            _celula_linhas(c, X0 + col_rotulo, y, col_valor, altura, linhas, tamanho=8.5)
            y -= altura

        bloco_assinaturas(
            c, TOPO_ASSINATURAS,
            {"nome": dados.get("inspecionado_por"), "cargo": dados.get("inspecionado_por_cargo") or "Controle de Qualidade",
             "data": dados.get("data_execucao") or data_emissao, "assinatura": dados.get("assinatura_executado")},
            {"nome": dados.get("aprovado_por"), "cargo": dados.get("aprovado_por_cargo") or "",
             "data": dados.get("data_aprovacao") or data_emissao, "assinatura": dados.get("assinatura_aprovado")},
        )  # fmt: skip
        rodape(c, DOC_DUR, referencia, data_emissao)
        c.showPage()

    return _gerar(desenhar)


# ---------------------------------------------------------------- Tratamento térmico


def _tabela_cabecalho_tt(c, y, dados: dict, lotes: list[dict]) -> float:
    """Material / Fornecedor / Procedimento / Esp. Dureza (valem para o forno todo) + uma linha por lote incluído."""
    lin_h = 7 * mm
    topo = [("Material", 0.22), ("Fornecedor", 0.26), ("Procedimento Interno", 0.27), ("Esp. Dureza", 0.25)]
    larguras = [LARGURA_UTIL * fr for _, fr in topo]
    valores = [dados.get("material", ""), dados.get("fornecedor", ""), DOC_TT["proc"], dados.get("esp_dureza", "")]
    x = X0
    for (nome, _), lw in zip(topo, larguras, strict=True):
        _celula(c, x, y, lw, lin_h, nome, negrito=True, tamanho=7.5, alinhar="C", fundo=CINZA_FUNDO)
        x += lw
    y -= lin_h
    x = X0
    for valor, lw in zip(valores, larguras, strict=True):
        _celula(c, x, y, lw, lin_h, valor, tamanho=8.5, alinhar="C", encolher=True)
        x += lw
    y -= lin_h + 2 * mm

    colunas = [("Cliente", 0.18), ("Item", 0.34), ("OP", 0.14), ("Lote TT", 0.16), ("QTD.", 0.18)]
    larguras = [LARGURA_UTIL * fr for _, fr in colunas]
    x = X0
    for (nome, _), lw in zip(colunas, larguras, strict=True):
        _celula(c, x, y, lw, lin_h, nome, negrito=True, tamanho=7.5, alinhar="C", fundo=CINZA_FUNDO)
        x += lw
    y -= lin_h
    for lo in lotes:
        x = X0
        for valor, lw in zip([lo.get("cliente", ""), lo.get("item", ""), lo.get("op", ""), lo.get("lote", ""),
                              lo.get("qtd", "")], larguras, strict=True):  # fmt: skip
            _celula(c, x, y, lw, lin_h, str(valor), tamanho=8.5, alinhar="C", encolher=True)
            x += lw
        y -= lin_h
    return y - 3 * mm


def _titulo_ciclo(c, y, texto, forno: str) -> float:
    y = _titulo_secao(c, y, texto)
    if forno:
        _legenda(c, LARGURA / 2, y - 4 * mm, f"Forno: {forno}")
        y -= 6 * mm
    return y


def gerar_pdf_tt(lote: dict, dados: dict, lotes_incluidos: list[dict], imagens: dict, empresa: dict) -> bytes:
    """Relatório de Tratamento Térmico (página 1: têmpera; página 2: revenimento).

    lote: o lote principal (op). lotes_incluidos: [{cliente, item, op, lote, qtd}] — o primeiro é o principal.
    dados: material, fornecedor, esp_dureza, po, forno_tempera_desc, forno_revenimento_desc,
        tempera {pre_temp, pre_tempo, z2_temp, z2_tempo, z3_temp, z3_tempo, resfriamento_pre/_z2/_z3},
        revenimento [{temp, tempo}], dureza_pos_tt {minimo, maximo, status} (opcional), obs,
        tecnico_nome, tecnico_cargo, aprovado_por, data_tratamento, data_registro (= emissão), data_aprovacao,
        assinatura_executado / assinatura_aprovado (Path ou None).
    imagens: {'tempera', 'rev1', 'rev2'} -> Path ou None.
    """
    data_emissao = dados.get("data_registro", "")
    laudo = laudo_numero("TT", data_emissao, lote.get("op", ""))
    referencia = f"OPs: {'/'.join(str(lo.get('op', '')) for lo in lotes_incluidos)}"
    lin_h = 7 * mm
    titulo, subtitulo = "RELATÓRIO DE TRATAMENTO TÉRMICO", "Têmpera e Revenimento"

    def desenhar(c: canvas.Canvas, total: int | str) -> None:
        # ---------- página 1: têmpera
        y = cabecalho(c, empresa, titulo, subtitulo, DOC_TT, 1, total, laudo, data_emissao, dados.get("po"))
        y = _tabela_cabecalho_tt(c, y, dados, lotes_incluidos)
        y = _titulo_ciclo(c, y, "CICLO 1 — TÊMPERA", dados.get("forno_tempera_desc", ""))
        col_rotulo = LARGURA_UTIL * 0.22
        col = (LARGURA_UTIL - col_rotulo) / 3
        _celula(c, X0, y, col_rotulo, lin_h, fundo=CINZA_FUNDO)
        for i, nome in enumerate(("Pré aquecimento", "Austenitização Z2", "Austenitização Z3")):
            _celula(c, X0 + col_rotulo + i * col, y, col, lin_h, nome, negrito=True, tamanho=8.5, alinhar="C",
                    fundo=CINZA_FUNDO)  # fmt: skip
        t = dados.get("tempera") or {}
        linhas = [
            ("Temperatura", f"{t.get('pre_temp', '')}°C", f"{t.get('z2_temp', '')}°C", f"{t.get('z3_temp', '')}°C"),
            ("Tempo", f"{t.get('pre_tempo', '')} Min", f"{t.get('z2_tempo', '')} Min", f"{t.get('z3_tempo', '')} Min"),
            ("Resfriamento", t.get("resfriamento_pre") or "-", t.get("resfriamento_z2") or "-", t.get("resfriamento_z3") or "-"),
        ]
        for rotulo, *valores in linhas:
            y -= lin_h
            _celula(c, X0, y, col_rotulo, lin_h, rotulo, negrito=True, tamanho=8.5)
            for i, valor in enumerate(valores):
                _celula(c, X0 + col_rotulo + i * col, y, col, lin_h, valor, tamanho=9, alinhar="C")
        y -= lin_h + 6 * mm
        img_h = max(min(135 * mm, y - LIMITE_RODAPE - 8 * mm), 30 * mm)
        _imagem(c, imagens.get("tempera"), X0 + 10 * mm, y - img_h, LARGURA_UTIL - 20 * mm, img_h,
                vazio="[Gráfico do forno não enviado]", invalido="[Gráfico não disponível]")  # fmt: skip
        y -= img_h + 4 * mm
        _legenda(c, LARGURA / 2, y, "Figura 1 – Gráfico Pré aquecimento e Austenitização")
        rodape(c, DOC_TT, referencia, data_emissao)
        c.showPage()

        # ---------- página 2: revenimento
        y = cabecalho(c, empresa, titulo, subtitulo, DOC_TT, 2, total, laudo, data_emissao, dados.get("po"))
        y = _tabela_cabecalho_tt(c, y, dados, lotes_incluidos)
        y = _titulo_ciclo(c, y, "CICLO 2 — REVENIMENTO", dados.get("forno_revenimento_desc", ""))
        col_rotulo = LARGURA_UTIL * 0.30
        col = (LARGURA_UTIL - col_rotulo) / 2
        _celula(c, X0, y, col_rotulo, lin_h, fundo=CINZA_FUNDO)
        _celula(c, X0 + col_rotulo, y, col, lin_h, "Temperatura", negrito=True, tamanho=8.5, alinhar="C", fundo=CINZA_FUNDO)
        _celula(c, X0 + col_rotulo + col, y, col, lin_h, "Tempo", negrito=True, tamanho=8.5, alinhar="C", fundo=CINZA_FUNDO)
        for i, r in enumerate(dados.get("revenimento") or []):
            y -= lin_h
            _celula(c, X0, y, col_rotulo, lin_h, f"{i + 1}º Revenimento", negrito=True, tamanho=8.5)
            _celula(c, X0 + col_rotulo, y, col, lin_h, f"{r.get('temp', '')}°C", tamanho=9, alinhar="C")
            _celula(c, X0 + col_rotulo + col, y, col, lin_h, f"{r.get('tempo', '')} Min", tamanho=9, alinhar="C")
        y -= lin_h + 6 * mm

        # Os blocos finais ficam presos ao rodapé: observações (92 mm), verificação de dureza (78 mm) e
        # assinaturas (46 mm). Os gráficos usam o espaço que sobra acima de 100 mm.
        limite = 100 * mm
        graficos = [imagens[k] for k in ("rev1", "rev2") if imagens.get(k)]
        if len(graficos) == 2:
            w_cada = (LARGURA_UTIL - 10 * mm) / 2
            h_disp = max(min(70 * mm, y - limite - 8 * mm), 20 * mm)
            for i, caminho in enumerate(graficos):
                x = X0 + i * (w_cada + 10 * mm)
                _imagem(c, caminho, x, y - h_disp, w_cada, h_disp, vazio="", invalido="[Gráfico indisponível]")
                _legenda(c, x + w_cada / 2, y - h_disp - 4 * mm, f"Figura {i + 2} – Gráfico de revenimento {i + 1}", 7.5)
        elif len(graficos) == 1:
            h_disp = max(min(70 * mm, y - limite - 5 * mm), 20 * mm)
            _imagem(c, graficos[0], X0 + 15 * mm, y - h_disp, LARGURA_UTIL - 30 * mm, h_disp, vazio="",
                    invalido="[Gráfico indisponível]")  # fmt: skip
            _legenda(c, LARGURA / 2, y - h_disp - 4 * mm, "Figura 2 – Gráfico de revenimento", 7.5)
        else:
            h_disp = max(min(50 * mm, y - limite), 15 * mm)
            _imagem(c, None, X0 + 15 * mm, y - h_disp, LARGURA_UTIL - 30 * mm, h_disp,
                    vazio="[Gráficos do revenimento não enviados]", invalido="")  # fmt: skip

        f = _f()
        if dados.get("obs"):
            c.setFont(f["negrito"], 8.5)
            c.setFillColor(PRETO)
            c.drawString(X0, 92 * mm, "Observações:")
            c.setFont(f["normal"], 8.5)
            for i, linha in enumerate(simpleSplit(dados["obs"], f["normal"], 8.5, LARGURA_UTIL)[:2]):
                c.drawString(X0, (87 - 4 * i) * mm, linha)

        pos = dados.get("dureza_pos_tt") or {}
        if pos.get("minimo") is not None or pos.get("maximo") is not None:
            y_v = _titulo_secao(c, 78 * mm, "VERIFICAÇÃO DE DUREZA PÓS-TRATAMENTO TÉRMICO")
            col_d = LARGURA_UTIL / 4
            for i, nome in enumerate(("Especificação", "Dureza mínima encontrada", "Dureza máxima encontrada", "Status")):
                _celula(c, X0 + i * col_d, y_v, col_d, lin_h, nome, negrito=True, tamanho=7.5, alinhar="C", fundo=CINZA_FUNDO)
            y_v -= lin_h
            status = pos.get("status") or ""
            _celula(c, X0, y_v, col_d, lin_h, dados.get("esp_dureza", ""), tamanho=9, alinhar="C")
            _celula(c, X0 + col_d, y_v, col_d, lin_h, f"{numero_br(pos.get('minimo'))} HRc", tamanho=9, alinhar="C")
            _celula(c, X0 + 2 * col_d, y_v, col_d, lin_h, f"{numero_br(pos.get('maximo'))} HRc", tamanho=9, alinhar="C")
            _celula(c, X0 + 3 * col_d, y_v, col_d, lin_h, status, negrito=True, tamanho=9, alinhar="C", cor=_cor_status(status))
            y_v -= lin_h + 3 * mm
            c.setFont(f["italico"], 7.5)
            c.setFillColor(CINZA)
            c.drawString(X0, y_v, "Verificação do técnico de tratamento térmico — não substitui o ensaio formal de Dureza "
                                  f"({DOC_DUR['codigo']}).")  # fmt: skip

        bloco_assinaturas(
            c, 46 * mm,
            {"nome": dados.get("tecnico_nome"), "cargo": dados.get("tecnico_cargo") or "Técnico de Trat. Térmico",
             "data": dados.get("data_tratamento") or data_emissao, "assinatura": dados.get("assinatura_executado")},
            {"nome": dados.get("aprovado_por"), "cargo": dados.get("aprovado_por_cargo") or "",
             "data": dados.get("data_aprovacao") or data_emissao, "assinatura": dados.get("assinatura_aprovado")},
        )  # fmt: skip
        rodape(c, DOC_TT, referencia, data_emissao)
        c.showPage()

    return _gerar(desenhar)


# ---------------------------------------------------------------- Inspeção visual e marcação a laser


def gerar_pdf_visual(lote: dict, dados: dict, imagens: dict, empresa: dict) -> bytes:
    """Relatório de Inspeção Visual e Marcação a Laser.

    lote: op, lote, coditem. dados: cliente, nome_peca, desenho, padrao_aceitacao, po, qtd_inspecionada,
        resultado ('APROVADO' / 'REPROVADO' / 'USAR COMO ESTÁ (RNC)'), rnc, obs1..obs3, lote_completo,
        inspecionado_por, aprovado_por, data (= emissão), data_execucao, data_aprovacao, assinaturas.
        (Os códigos do laser ficam no registro e na tela; não entram no PDF, como no antigo.)
    imagens: {'geral', 'peca', 'laser'} -> Path ou None.
    """
    data_emissao = dados.get("data", "")
    laudo = laudo_numero("VIS", data_emissao, lote.get("op", ""))
    referencia = f"OP {lote.get('op', '')} / Lote {lote.get('lote', '')}"
    lin_h = 6.5 * mm

    def desenhar(c: canvas.Canvas, total: int | str) -> None:
        f = _f()
        pagina = 1
        y = cabecalho(c, empresa, "RELATÓRIO DE INSPEÇÃO VISUAL E MARCAÇÃO A LASER", "Inspeção final — Rastreabilidade por laser",
                      DOC_VIS, pagina, total, laudo, data_emissao, dados.get("po"))  # fmt: skip
        y = bloco_identificacao(c, y, [
            ("Cliente", dados.get("cliente", "")),
            ("Padrão de Aceitação", dados.get("padrao_aceitacao", "")),
            ("Item", dados.get("nome_peca", "")),
            ("Código do Item", lote.get("coditem", "")),
            ("Desenho / Revisão", dados.get("desenho", "")),
            ("Procedimento Interno", DOC_VIS["proc"]),
            ("OP", lote.get("op", "")),
            ("Lote", dados.get("lote_completo") or lote.get("lote", "")),
            ("Qtd. Inspecionada", str(dados.get("qtd_inspecionada", ""))),
        ])  # fmt: skip

        resultado = (dados.get("resultado") or "").upper()
        cor = VERDE if resultado == "APROVADO" else (VERMELHO if resultado == "REPROVADO" else AZUL)
        fundo = FUNDO_APROVADO if resultado == "APROVADO" else (FUNDO_REPROVADO if resultado == "REPROVADO" else CINZA_FUNDO)
        res_h = 10 * mm
        _celula(c, X0, y, LARGURA_UTIL * 0.65, res_h, f"RESULTADO DA INSPEÇÃO: {resultado}", negrito=True, tamanho=11,
                alinhar="C", fundo=fundo, cor=cor, encolher=True)  # fmt: skip
        _celula(c, X0 + LARGURA_UTIL * 0.65, y, LARGURA_UTIL * 0.35, res_h, f"Nº RNC: {dados.get('rnc') or 'N/A'}",
                negrito=True, tamanho=9, alinhar="C", fundo=CINZA_FUNDO, encolher=True)  # fmt: skip
        y -= res_h + 4 * mm

        y = _titulo_secao(c, y, "VERIFICAÇÕES REALIZADAS", h=lin_h, alinhar="E")
        c.setFont(f["normal"], 8.5)
        c.setFillColor(PRETO)
        for obs in (dados.get("obs1"), dados.get("obs2"), dados.get("obs3")):
            if not obs:
                continue
            linhas = simpleSplit(f"• {obs}", f["normal"], 8.5, LARGURA_UTIL - 4 * mm)
            for i, linha in enumerate(linhas):
                c.drawString(X0 + 2 * mm + (3 * mm if i else 0), y - 4.5 * mm, linha)
                y -= 4.5 * mm
            y -= 1.5 * mm
        y -= 3 * mm

        legendas = [("geral", "Figura 1 — Foto geral (lote embalado)"), ("peca", "Figura 2 — Foto da peça (detalhe)"),
                    ("laser", "Figura 3 — Foto da gravação laser")]  # fmt: skip
        foto_h = 50 * mm
        foto_w = (LARGURA_UTIL - 10 * mm) / 3
        if y - foto_h - 10 * mm - 28 * mm < LIMITE_RODAPE:  # fotos + assinaturas não cabem: vão para a página seguinte
            rodape(c, DOC_VIS, referencia, data_emissao)
            c.showPage()
            pagina += 1
            y = cabecalho(c, empresa, "RELATÓRIO DE INSPEÇÃO VISUAL E MARCAÇÃO A LASER",
                          "Inspeção final — Rastreabilidade por laser", DOC_VIS, pagina, total, laudo, data_emissao,
                          dados.get("po"))  # fmt: skip
        x = X0
        for chave, legenda in legendas:
            _imagem(c, imagens.get(chave), x, y - foto_h, foto_w, foto_h, vazio="[Imagem a anexar]", invalido="[Foto inválida]",
                    moldura=True)  # fmt: skip
            _legenda(c, x + foto_w / 2, y - foto_h - 4 * mm, legenda, 7)
            x += foto_w + 5 * mm
        y -= foto_h + 10 * mm

        bloco_assinaturas(
            c, y,
            {"nome": dados.get("inspecionado_por"), "cargo": dados.get("inspecionado_por_cargo") or "Controle de Qualidade",
             "data": dados.get("data_execucao") or data_emissao, "assinatura": dados.get("assinatura_executado")},
            {"nome": dados.get("aprovado_por"), "cargo": dados.get("aprovado_por_cargo") or "",
             "data": dados.get("data_aprovacao") or data_emissao, "assinatura": dados.get("assinatura_aprovado")},
        )  # fmt: skip
        rodape(c, DOC_VIS, referencia, data_emissao)
        c.showPage()

    return _gerar(desenhar)
