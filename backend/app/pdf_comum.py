"""Peças comuns a todos os PDFs gerados pelo sistema (ReportLab).

Regras do sistema antigo que continuam valendo (ver legado/CLAUDE.md, seção 8):
- Toda tabela de uma página tem a MESMA largura total: LARGURA_UTIL (186 mm, A4 com ~12 mm de margem).
- Código de documento oficial (ex.: "FOR-TT-IS.8.5-06-8") é copiado exatamente, nunca "arrumado".
- Documento que pode sair da empresa nunca cita o cliente final (use o parâmetro só em documento interno).
- Razão social sem "Ltda." e sem CNPJ (parâmetro empresa_razao_social).
"""
from pathlib import Path

from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from sqlalchemy.orm import Session

from app import parametros
from app.arquivos import caminho_seguro
from app.models import Usuario

LARGURA_UTIL = 186 * mm
LOGO = Path(__file__).parent / "recursos" / "logo-acokorte.png"

# Fonte com acentos: DejaVu no servidor (pacote fonts-dejavu-core na imagem); sem ela, Helvetica do ReportLab
_CANDIDATAS = {
    "normal": ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"],
    "negrito": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"],
}
_fontes: dict[str, str] | None = None


def fontes() -> dict[str, str]:
    """{'normal': nome, 'negrito': nome} já registradas no ReportLab."""
    global _fontes
    if _fontes is None:
        _fontes = {"normal": "Helvetica", "negrito": "Helvetica-Bold"}
        for estilo, caminhos in _CANDIDATAS.items():
            for caminho in caminhos:
                if Path(caminho).is_file():
                    nome = f"AcoKey-{estilo}"
                    pdfmetrics.registerFont(TTFont(nome, caminho))
                    _fontes[estilo] = nome
                    break
    return _fontes


def empresa(db: Session) -> dict[str, str]:
    return {
        "razao_social": parametros.ler(db, "empresa_razao_social"),
        "endereco": parametros.ler(db, "empresa_endereco"),
    }


def caminho_assinatura(usuario: Usuario | None) -> Path | None:
    """Imagem da assinatura digital do usuário (PNG/JPG), se houver."""
    return caminho_seguro(usuario.assinatura_arquivo) if usuario and usuario.assinatura_arquivo else None
