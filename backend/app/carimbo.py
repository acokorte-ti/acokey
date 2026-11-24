"""Carimbo "APROVADO" da Qualidade nos certificados de matéria-prima (PDF).

Regras do sistema antigo (legado/app.py: _carimbar_pdf_aprovado):
- carimbo compacto no canto inferior direito de TODAS as páginas;
- SEM data visível (a data fica gravada no sistema e na auditoria);
- com a imagem da assinatura digital de quem aprovou, o nome dele e "Qualidade AçoKorte" embaixo.

O arquivo original nunca é alterado: quem chama grava o resultado como um arquivo novo.
"""
from pathlib import Path

import pymupdf

VERDE = (0.12, 0.54, 0.29)
CINZA = (0.5, 0.5, 0.5)
TINTA = (0.1, 0.1, 0.1)
# Medidas do carimbo do sistema antigo, em pontos (1/72 pol.)
LARGURA, ALTURA, MARGEM = 95, 52, 20
RODAPE = "Qualidade AçoKorte"


class ErroCarimbo(Exception):
    """Mensagem pronta para o usuário."""


def _centralizado(pagina: pymupdf.Page, x0: float, largura: float, y: float, texto: str, tamanho: float, cor) -> None:
    medida = pymupdf.get_text_length(texto, fontname="helv", fontsize=tamanho)
    pagina.insert_text(pymupdf.Point(x0 + max(4, (largura - medida) / 2), y), texto, fontname="helv", fontsize=tamanho,
                       color=cor)  # fmt: skip


def _nome_que_cabe(nome: str, largura: float) -> tuple[str, float]:
    """Nome do aprovador no tamanho 6; se não couber, diminui até 4,5 e, por fim, corta."""
    nome = (nome or "---").strip() or "---"
    for tamanho in (6, 5.5, 5, 4.5):
        if pymupdf.get_text_length(nome, fontname="helv", fontsize=tamanho) <= largura:
            return nome, tamanho
    while len(nome) > 3 and pymupdf.get_text_length(nome + ".", fontname="helv", fontsize=4.5) > largura:
        nome = nome[:-1]
    return nome.rstrip() + ".", 4.5


def carimbar_pdf(conteudo: bytes, nome_aprovador: str, assinatura: Path | None) -> bytes:
    """Devolve o PDF com o carimbo em todas as páginas."""
    try:
        doc = pymupdf.open(stream=conteudo, filetype="pdf")
    except Exception as erro:  # o PyMuPDF levanta tipos variados para arquivo corrompido
        raise ErroCarimbo("O arquivo não pôde ser aberto como PDF (pode estar corrompido).") from erro
    try:
        if doc.needs_pass:
            raise ErroCarimbo("O PDF está protegido por senha e não pode ser carimbado. Peça ao fornecedor uma via sem senha.")
        if doc.page_count == 0:
            raise ErroCarimbo("O PDF não tem nenhuma página.")
        nome, tamanho_nome = _nome_que_cabe(nome_aprovador, LARGURA - 8)
        for pagina in doc:
            # Página "deitada" (scanner): sem isto o carimbo cairia em outro canto
            if pagina.rotation:
                pagina.remove_rotation()
            x1 = pagina.rect.width - MARGEM
            y1 = pagina.rect.height - MARGEM
            x0, y0 = x1 - LARGURA, y1 - ALTURA
            pagina.draw_rect(pymupdf.Rect(x0, y0, x1, y1), color=VERDE, fill=(1, 1, 1), width=1.0, overlay=True)
            _centralizado(pagina, x0, LARGURA, y0 + 11, "APROVADO", 9, VERDE)
            pagina.draw_line(pymupdf.Point(x0 + 6, y0 + 14), pymupdf.Point(x1 - 6, y0 + 14), color=VERDE, width=0.4)
            if assinatura:
                try:
                    pagina.insert_image(pymupdf.Rect(x0 + 10, y0 + 16, x1 - 10, y0 + 34), filename=str(assinatura),
                                        keep_proportion=True, overlay=True)  # fmt: skip
                except Exception as erro:
                    raise ErroCarimbo(
                        "A imagem da sua assinatura digital não pôde ser usada. Peça ao administrador para cadastrá-la de novo."
                    ) from erro
            _centralizado(pagina, x0, LARGURA, y0 + 42, nome, tamanho_nome, TINTA)
            _centralizado(pagina, x0, LARGURA, y0 + 49, RODAPE, 5, CINZA)
        return doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()
