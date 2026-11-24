"""Montagem do PDF do databook (dossiê de qualidade do produto que vai para o cliente).

Porte de legado/databook.py (função `montar`): capa, índice com links, página-separador por seção, os documentos
anexados, rodapé numerado ("Página X de Y"), marcadores e compressão final. Mesmo layout, textos e cálculos.

Diferenças em relação ao antigo, por causa do servidor:
- os documentos chegam prontos em `Secao`/`Documento` (o antigo copiava os anexos para pastas e lia de lá);
- assinatura na capa: a IMAGEM da assinatura digital de quem elaborou e de quem aprovou. O antigo escrevia o nome
  em letra cursiva do Windows (Segoe Script), que não existe no Linux; sem imagem cadastrada, sai o nome em itálico,
  que era o que o antigo fazia quando não achava a fonte cursiva;
- fontes de `pdf_comum.fontes()` (com acentos no servidor) no lugar da Helvetica;
- a compressão é feita na memória e só fica se o arquivo diminuir.
"""
import io
import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from app.pdf_comum import fontes

IMG_EXT = {".jpg", ".jpeg", ".png"}
PDF_EXT = {".pdf"}
AZUL = colors.HexColor("#1F3A5F")
CINZA = colors.HexColor("#666666")
PRETO = colors.HexColor("#1B2430")
ROTULO_CZ = colors.HexColor("#555555")
FONTE_ASSINATURA = "Helvetica-Oblique"  # nome escrito quando o usuário não tem imagem de assinatura
LINHAS_POR_PAGINA = 38


class SemDocumentos(Exception):
    """Nenhum documento do lote pôde entrar no databook."""


@dataclass
class Documento:
    nome: str  # nome do arquivo, para o relatório de conferência
    caminho: Path | None  # None: o arquivo não está na pasta de arquivos (vira alerta no relatório)

    @property
    def titulo(self) -> str:
        return limpar_titulo(self.nome)


@dataclass
class Secao:
    titulo: str
    documentos: list[Documento] = field(default_factory=list)


@dataclass
class Capa:
    empresa: str
    cliente: str
    projeto: str
    produto: str
    pedido: str
    lote: str
    qtd: str
    numero_documento: str
    revisao: str
    data: str  # data de emissão (= data de aprovação digitada na tela), "dd/mm/aaaa"
    elaborado_por: str = ""
    elaborado_cargo: str = ""
    assinatura_elaborado: Path | None = None
    aprovado_por: str = ""
    aprovado_cargo: str = ""
    assinatura_aprovado: Path | None = None
    data_aprovacao: str = ""


@dataclass
class Resultado:
    pdf: bytes
    paginas: int
    relatorio: str  # texto do relatório de conferência (o antigo gravava Relatorio_Conferencia_*.txt)
    alertas: list[str]
    tamanho_antes: int
    tamanho_depois: int


# ----------------------------------------------------------------- utilidades
def limpar_titulo(nome: str) -> str:
    """'01_Certificado_Composicao_Quimica' -> 'Certificado Composicao Quimica'; tira a extensão de arquivo."""
    nome = Path(nome).stem if Path(nome).suffix.lower() in (PDF_EXT | IMG_EXT) else nome
    nome = re.sub(r"^\d+[\s_.\-]*", "", nome)
    return nome.replace("_", " ").strip() or "Sem título"


def normalizar(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", txt)
    return "".join(c for c in txt if not unicodedata.combining(c)).lower()


def truncar(txt: str, fonte: str, tam: float, largura: float) -> str:
    if stringWidth(txt, fonte, tam) <= largura:
        return txt
    while txt and stringWidth(txt + "...", fonte, tam) > largura:
        txt = txt[:-1]
    return txt + "..."


def imagem_para_pdf(caminho: Path) -> bytes:
    """Foto ou digitalização (JPG/PNG) numa página A4, deitada se a imagem for mais larga que alta."""
    with Image.open(caminho) as im:
        w, h = im.size
    pw, ph = A4
    if w > h:  # paisagem
        pw, ph = ph, pw
    margem = 15 * mm
    esc = min((pw - 2 * margem) / w, (ph - 2 * margem) / h)
    iw, ih = w * esc, h * esc
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(pw, ph))
    c.drawImage(ImageReader(str(caminho)), (pw - iw) / 2, (ph - ih) / 2, iw, ih)
    c.save()
    return buf.getvalue()


def abrir_documento(caminho: Path | None) -> PdfReader:
    """Devolve um PdfReader ou levanta exceção (arquivo corrompido, com senha, sem páginas)."""
    if caminho is None or not caminho.is_file():
        raise ValueError("arquivo não encontrado no servidor")
    if caminho.suffix.lower() in IMG_EXT:
        return PdfReader(io.BytesIO(imagem_para_pdf(caminho)))
    reader = PdfReader(str(caminho))
    if reader.is_encrypted and reader.decrypt("") == 0:
        raise ValueError("PDF protegido por senha")
    if len(reader.pages) == 0:
        raise ValueError("PDF sem páginas")
    return reader


# ----------------------------------------------------------------- páginas geradas
def _assinatura(c: canvas.Canvas, x: float, largura: float, nome: str, imagem: Path | None) -> None:
    """Imagem da assinatura digital acima da linha; sem imagem, o nome em itálico (como o antigo sem a fonte cursiva)."""
    if imagem:
        try:
            c.drawImage(ImageReader(str(imagem)), x + 10 * mm, 38 * mm, largura - 20 * mm, 13 * mm,
                        preserveAspectRatio=True, anchor="s", mask="auto")  # fmt: skip
            return
        except Exception:  # imagem ilegível: cai no nome escrito, a capa não deixa de sair
            pass
    c.setFillColor(colors.black)
    c.setFont(FONTE_ASSINATURA, 10)
    c.drawCentredString(x + largura / 2, 42 * mm, truncar(nome, FONTE_ASSINATURA, 10, largura - 10 * mm))


def gerar_capa(capa: Capa, logo: Path | None) -> bytes:
    """Capa minimalista: sem barra de cabeçalho preenchida, título e rótulos em cinza escuro/preto, azul só como
    linha fina de destaque (pedido do cliente, para reduzir o peso visual da página)."""
    f = fontes()
    normal, negrito = f["normal"], f["negrito"]
    w, h = A4
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    x_texto = 20 * mm
    if logo and logo.exists():
        try:
            c.drawImage(ImageReader(str(logo)), 20 * mm, h - 32 * mm, 28 * mm, 18 * mm,
                        preserveAspectRatio=True, anchor="w", mask="auto")  # fmt: skip
            x_texto = 54 * mm
        except Exception:
            pass
    c.setFillColor(PRETO)
    c.setFont(negrito, 11)
    c.drawString(x_texto, h - 22 * mm, truncar(capa.empresa, negrito, 11, w - x_texto - 20 * mm))

    c.setStrokeColor(AZUL)
    c.setLineWidth(1.3)
    c.line(20 * mm, h - 38 * mm, w - 20 * mm, h - 38 * mm)

    c.setFillColor(PRETO)
    c.setFont(negrito, 32)
    c.drawCentredString(w / 2, h - 70 * mm, "DATABOOK")
    c.setFont(normal, 13)
    c.setFillColor(CINZA)
    c.drawCentredString(w / 2, h - 79 * mm, "Dossiê de Qualidade do Produto")

    campos = [
        ("Cliente", capa.cliente),
        ("Especificação / Projeto", capa.projeto),
        ("Produto", capa.produto),
        ("Nº do pedido (PO)", capa.pedido),
        ("Lote", capa.lote),
        ("QTD - Lote", capa.qtd),
        ("Nº do documento", capa.numero_documento),
        ("Revisão", capa.revisao),
        ("Data de emissão", capa.data),
    ]
    y = h - 98 * mm
    x1, x2 = 30 * mm, 98 * mm
    for rotulo, valor in campos:
        c.setFont(negrito, 9.5)
        c.setFillColor(ROTULO_CZ)
        c.drawString(x1, y, rotulo.upper())
        c.setFont(normal, 11)
        c.setFillColor(colors.black)
        c.drawString(x2, y, truncar(str(valor), normal, 11, w - x2 - 25 * mm))
        c.setStrokeColor(colors.HexColor("#DDDDDD"))
        c.setLineWidth(0.5)
        c.line(x1, y - 2.5 * mm, w - 25 * mm, y - 2.5 * mm)
        y -= 11 * mm

    # bloco de aprovação - discreto: sem caixa nem barra preenchida, só o título e uma linha fina separando
    data_assin = capa.data_aprovacao or capa.data
    blocos = [
        ("Elaborado por", capa.elaborado_por, capa.elaborado_cargo, capa.assinatura_elaborado),
        ("Aprovado por", capa.aprovado_por, capa.aprovado_cargo, capa.assinatura_aprovado),
    ]
    caixa_w = (w - 60 * mm) / 2
    topo = 60 * mm
    c.setStrokeColor(colors.HexColor("#DDDDDD"))
    c.setLineWidth(0.5)
    c.line(30 * mm, topo, w - 30 * mm, topo)
    for i, (titulo, nome, cargo, imagem) in enumerate(blocos):
        x = 30 * mm + i * caixa_w
        c.setFillColor(ROTULO_CZ)
        c.setFont(negrito, 9)
        c.drawCentredString(x + caixa_w / 2, topo - 7 * mm, titulo.upper())
        _assinatura(c, x, caixa_w, nome, imagem)
        c.setStrokeColor(colors.HexColor("#AAAAAA"))
        c.setLineWidth(0.4)
        c.line(x + 10 * mm, 37 * mm, x + caixa_w - 10 * mm, 37 * mm)
        # nome por extenso + cargo
        c.setFillColor(colors.black)
        c.setFont(negrito, 9)
        c.drawCentredString(x + caixa_w / 2, 32 * mm, truncar(nome, negrito, 9, caixa_w - 10 * mm))
        c.setFillColor(CINZA)
        c.setFont(normal, 8)
        if cargo:
            c.drawCentredString(x + caixa_w / 2, 27 * mm, truncar(cargo, normal, 8, caixa_w - 10 * mm))
        if data_assin:
            c.drawCentredString(x + caixa_w / 2, 22 * mm, f"Data: {data_assin}")
        if i == 0:
            c.setStrokeColor(colors.HexColor("#EEEEEE"))
            c.setLineWidth(0.4)
            c.line(x + caixa_w, 18 * mm, x + caixa_w, topo)
    c.save()
    return buf.getvalue()


def gerar_indice(entradas: list[tuple[int, str, int]]) -> tuple[bytes, int, list]:
    """entradas: (nivel, texto, pagina_destino). Devolve (pdf, nº de páginas, links), links = [(pág. do índice, ret., destino)]."""
    f = fontes()
    w, h = A4
    n_pags = max(1, math.ceil(len(entradas) / LINHAS_POR_PAGINA))
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    links = []
    for p in range(n_pags):
        c.setFillColor(AZUL)
        c.setFont(f["negrito"], 20)
        c.drawString(20 * mm, h - 25 * mm, "ÍNDICE")
        c.setStrokeColor(AZUL)
        c.setLineWidth(1.2)
        c.line(20 * mm, h - 29 * mm, w - 20 * mm, h - 29 * mm)
        y = h - 40 * mm
        for nivel, texto, pg in entradas[p * LINHAS_POR_PAGINA:(p + 1) * LINHAS_POR_PAGINA]:
            if nivel == 0:
                fonte, tam, recuo = f["negrito"], 10.5, 0
                y -= 1.5 * mm
                c.setFillColor(AZUL)
            else:
                fonte, tam, recuo = f["normal"], 9.5, 8 * mm
                c.setFillColor(colors.black)
            x0 = 20 * mm + recuo
            x_pg = w - 20 * mm
            c.setFont(fonte, tam)
            texto_ok = truncar(texto, fonte, tam, x_pg - x0 - 22 * mm)
            c.drawString(x0, y, texto_ok)
            c.drawRightString(x_pg, y, str(pg))
            fim_txt = x0 + stringWidth(texto_ok, fonte, tam) + 2 * mm
            ini_num = x_pg - stringWidth(str(pg), fonte, tam) - 2 * mm
            if ini_num > fim_txt:  # pontilhado até o número da página
                c.setStrokeColor(colors.HexColor("#999999"))
                c.setLineWidth(0.6)
                c.setDash(0.6, 2.2)
                c.line(fim_txt, y + 0.8 * mm, ini_num, y + 0.8 * mm)
                c.setDash()
            links.append((p, (20 * mm, y - 1.5 * mm, x_pg, y + 4 * mm), pg))
            y -= 6.6 * mm if nivel == 0 else 6 * mm
        c.showPage()
    c.save()
    return buf.getvalue(), n_pags, links


def gerar_separador(numero: int, titulo: str, n_docs: int) -> bytes:
    """Página-separador no estilo da capa: bloco centralizado, texto cinza escuro e uma linha fina azul."""
    f = fontes()
    w, h = A4
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    cy = h / 2
    c.setFillColor(ROTULO_CZ)
    c.setFont(f["negrito"], 10)
    c.drawCentredString(w / 2, cy + 15 * mm, f"SEÇÃO {numero}")
    c.setFillColor(PRETO)
    c.setFont(f["negrito"], 20)
    c.drawCentredString(w / 2, cy + 5 * mm, truncar(titulo.upper(), f["negrito"], 20, w - 30 * mm))
    c.setStrokeColor(AZUL)
    c.setLineWidth(1.3)
    c.line(60 * mm, cy - 1 * mm, w - 60 * mm, cy - 1 * mm)
    c.setFillColor(CINZA)
    c.setFont(f["normal"], 10)
    c.drawCentredString(w / 2, cy - 9 * mm, f"{n_docs} documento(s)")
    c.save()
    return buf.getvalue()


def gerar_carimbos(tamanhos: list[tuple[float, float]], capa: Capa, primeira_numerada: int, total: int) -> PdfReader:
    """Uma página transparente por página final, com o rodapé numerado (a capa não é numerada)."""
    normal = fontes()["normal"]
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    ref = f"{capa.numero_documento} Rev. {capa.revisao}"
    for i, (w, h) in enumerate(tamanhos):
        c.setPageSize((w, h))
        if i >= primeira_numerada:
            c.setFont(normal, 7.5)
            c.setFillColor(CINZA)
            c.setStrokeColor(colors.HexColor("#AAAAAA"))
            c.setLineWidth(0.4)
            c.line(12 * mm, 9 * mm, w - 12 * mm, 9 * mm)
            c.drawString(12 * mm, 5.5 * mm, truncar(f"{capa.cliente} - {capa.projeto}", normal, 7.5, w * 0.45))
            if w > 400:
                c.drawCentredString(w / 2, 5.5 * mm, ref)
            c.drawRightString(w - 12 * mm, 5.5 * mm, f"Página {i + 1} de {total}")
        c.showPage()
    c.save()
    return PdfReader(io.BytesIO(buf.getvalue()))


# ----------------------------------------------------------------- checklist e compressão
def conferir_checklist(checklist: list[str], secoes: list[tuple[str, list[dict]]]) -> list[str]:
    """Itens do checklist que não aparecem no nome de nenhum documento nem no título da seção dele."""
    nomes = [normalizar(d["nome"]) + " " + normalizar(titulo) for titulo, docs in secoes for d in docs]
    return [item for item in checklist if not any(normalizar(item) in n for n in nomes)]


def comprimir_pdf(pdf: bytes, dpi_max: int = 150, qualidade_jpeg: int = 75, area_min_fracao: float = 0.08) -> bytes:
    """Reduz o PDF final (comum 10+ MB -> 2-3 MB) para facilitar o envio por e-mail.

    Tira objetos repetidos/sem uso, comprime e, principalmente, reamostra para `dpi_max` as imagens grandes
    (certificados digitalizados em página inteira), recodificando como JPEG. Imagens pequenas (menos de
    `area_min_fracao` da página: assinaturas, carimbos, logos) ficam como estão, porque o JPEG borra traço fino.
    Qualquer falha devolve o PDF original: a compressão nunca impede a entrega do databook.
    """
    try:
        doc = pymupdf.open(stream=pdf, filetype="pdf")
        for page in doc:
            area_pagina = page.rect.width * page.rect.height or 1
            for img in page.get_images(full=True):
                xref, pix_w, pix_h = img[0], img[2], img[3]
                rects = page.get_image_rects(xref)
                if not rects:
                    continue
                r = rects[0]
                disp_w_pol = r.width / 72
                if disp_w_pol <= 0 or r.height <= 0:
                    continue
                if (r.width * r.height) / area_pagina < area_min_fracao:
                    continue  # assinatura/selo/logo: preserva
                dpi_atual = pix_w / disp_w_pol
                if dpi_atual <= dpi_max:
                    continue
                fator = dpi_max / dpi_atual
                novo_w, novo_h = max(1, int(pix_w * fator)), max(1, int(pix_h * fator))
                try:
                    info = doc.extract_image(xref)
                    pil_img = Image.open(io.BytesIO(info["image"]))
                    if pil_img.mode in ("RGBA", "P", "CMYK", "LA"):
                        pil_img = pil_img.convert("RGB")
                    pil_img = pil_img.resize((novo_w, novo_h), Image.Resampling.LANCZOS)
                    buf = io.BytesIO()
                    pil_img.save(buf, format="JPEG", quality=qualidade_jpeg, optimize=True)
                    page.replace_image(xref, stream=buf.getvalue())
                except Exception:
                    continue  # imagem de formato raro: mantém a original
        saida = doc.tobytes(garbage=4, deflate=True, clean=True)
        doc.close()
    except Exception:
        return pdf
    return saida if len(saida) < len(pdf) else pdf


# ----------------------------------------------------------------- montagem
def montar(
    capa: Capa,
    secoes: list[Secao],
    checklist: list[str],
    logo: Path | None = None,
    pagina_separadora: bool = True,
    numerar_paginas: bool = True,
    indice_simples: bool = True,
) -> Resultado:
    """Monta o databook. Levanta SemDocumentos se nenhum documento puder entrar."""
    # 1) abre os documentos de cada seção; arquivo com problema fica de fora e vira alerta
    abertas: list[tuple[str, list[dict]]] = []
    problemas: list[str] = []
    vazias: list[str] = []
    for s in secoes:
        docs = []
        for d in s.documentos:
            try:
                reader = abrir_documento(d.caminho)
                docs.append({"titulo": d.titulo, "nome": d.nome, "reader": reader, "paginas": len(reader.pages)})
            except Exception as e:  # arquivo corrompido, com senha etc.
                problemas.append(f"{s.titulo}/{d.nome}: {e}")
        if docs:
            abertas.append((s.titulo, docs))
        elif s.documentos:
            vazias.append(s.titulo)
    if not abertas:
        raise SemDocumentos("Nenhum documento (PDF/JPG/PNG) do lote pôde entrar no databook.")

    # 2) quantas páginas o índice ocupa (uma entrada por seção, no índice simples)
    n_entradas = len(abertas) if indice_simples else sum(1 + len(docs) for _, docs in abertas)
    _, n_idx, _ = gerar_indice([(0, "x", 0)] * n_entradas)

    # 3) página de cada seção e de cada documento
    pagina = 2 + n_idx
    entradas: list[tuple[int, str, int]] = []
    pag_secao: list[int] = []
    for i, (titulo, docs) in enumerate(abertas, 1):
        pag_secao.append(pagina)
        entradas.append((0, f"{i}. {titulo}", pagina))
        if pagina_separadora:
            pagina += 1
        for j, d in enumerate(docs, 1):
            d["pag_ini"] = pagina
            if not indice_simples:
                entradas.append((1, f"{i}.{j}  {d['titulo']}", pagina))
            pagina += d["paginas"]
    total = pagina - 1

    # 4) montagem
    w = PdfWriter()
    for pg in PdfReader(io.BytesIO(gerar_capa(capa, logo))).pages:
        w.add_page(pg)
    idx_bytes, _, links = gerar_indice(entradas)
    for pg in PdfReader(io.BytesIO(idx_bytes)).pages:
        w.add_page(pg)
    for i, (titulo, docs) in enumerate(abertas, 1):
        if pagina_separadora:
            w.add_page(PdfReader(io.BytesIO(gerar_separador(i, titulo, len(docs)))).pages[0])
        for d in docs:
            for pg in d["reader"].pages:
                if pg.get("/Rotate"):
                    pg.transfer_rotation_to_content()
                w.add_page(pg)

    if numerar_paginas:
        tamanhos = [(float(p.mediabox.width), float(p.mediabox.height)) for p in w.pages]
        carimbos = gerar_carimbos(tamanhos, capa, 1, total)
        for pg, ov in zip(w.pages, carimbos.pages, strict=True):
            pg.merge_page(ov)

    for p_idx, rect, destino in links:  # links clicáveis no índice
        w.add_annotation(page_number=1 + p_idx, annotation=Link(rect=rect, target_page_index=destino - 1))

    w.add_outline_item(title="Capa", page_number=0)  # marcadores
    w.add_outline_item(title="Índice", page_number=1)
    for i, (titulo, docs) in enumerate(abertas, 1):
        pai = w.add_outline_item(title=f"{i}. {titulo}", page_number=pag_secao[i - 1] - 1)
        for j, d in enumerate(docs, 1):
            w.add_outline_item(title=f"{i}.{j} {d['titulo']}", page_number=d["pag_ini"] - 1, parent=pai)

    w.add_metadata({
        "/Title": f"Databook - {capa.projeto}",
        "/Author": capa.empresa,
        "/Subject": f"{capa.numero_documento} Rev. {capa.revisao} - {capa.produto}",
    })  # fmt: skip
    w.page_mode = "/UseOutlines"
    buf = io.BytesIO()
    w.write(buf)
    bruto = buf.getvalue()
    final = comprimir_pdf(bruto)

    # 5) relatório de conferência (mesmo texto do antigo)
    faltando = conferir_checklist(checklist, abertas)
    alertas = [f"[FALTA] Nenhum documento com '{f_}' (checklist)" for f_ in faltando]
    alertas += [f"[VAZIA] Seção sem documentos: {v}" for v in vazias]
    alertas += [f"[ERRO ] Arquivo ignorado: {p_}" for p_ in problemas]
    linhas = [f"RELATÓRIO DE CONFERÊNCIA - {capa.numero_documento} Rev. {capa.revisao}",
              f"Gerado em {capa.data}", f"Total de páginas: {total}", ""]  # fmt: skip
    for i, (titulo, docs) in enumerate(abertas, 1):
        linhas.append(f"{i}. {titulo}  (pág. {pag_secao[i - 1]})")
        for j, d in enumerate(docs, 1):
            linhas.append(f"   {i}.{j} {d['nome']}  -> pág. {d['pag_ini']}, {d['paginas']} pág.")
    linhas += ["", "ALERTAS"]
    linhas += [f"   {a}" for a in alertas] or ["   Nenhum."]
    return Resultado(pdf=final, paginas=total, relatorio="\n".join(linhas), alertas=alertas,
                     tamanho_antes=len(bruto), tamanho_depois=len(final))  # fmt: skip
