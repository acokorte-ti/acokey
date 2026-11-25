"""Arquivos enviados pela tela e gerados pelo sistema (anexos, certificados, fotos, PDFs).

Regras:
- Todo arquivo fica dentro da pasta de arquivos (`ARQUIVOS_DIR`, um volume no servidor) e o banco guarda só o
  caminho RELATIVO a ela. Nada de caminho absoluto (o sistema antigo gravava `C:\\...`).
- Envio: extensão permitida, tamanho máximo e conferência do conteúdo (um ".pdf" precisa começar como PDF).
- Leitura: só por `caminho_seguro`, que recusa qualquer caminho que tente sair da pasta.
- Nada é apagado do disco: remover um anexo só o marca como removido no banco.
"""
import re
import secrets
import unicodedata
from collections.abc import Callable, Iterable
from pathlib import Path

from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.config import agora_local, config

PDF = {".pdf"}
IMAGENS = {".jpg", ".jpeg", ".png"}
DOCUMENTOS = PDF | IMAGENS  # anexos de etapa, certificados de matéria-prima
PLANILHAS = {".xlsx"}
LIMITE_PADRAO_MB = 25

TIPOS_CONTEUDO = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".csv": "text/csv",
}
# Começo do conteúdo de cada tipo: barra arquivo renomeado (ex.: um .exe chamado .pdf)
_ASSINATURAS = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".xlsx": (b"PK\x03\x04",),
    ".docx": (b"PK\x03\x04",),
}


def nome_seguro(nome: str | None, padrao: str = "arquivo") -> str:
    """'Relatório Dureza (OP 1).PDF' -> 'Relatorio_Dureza_OP_1.pdf'. Só letras, números, ponto, hífen e sublinhado."""
    nome = unicodedata.normalize("NFKD", Path(nome or "").name).encode("ascii", "ignore").decode()
    base, ponto, extensao = nome.rpartition(".")
    if not ponto:
        base, extensao = nome, ""
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-")[:100] or padrao
    extensao = re.sub(r"[^A-Za-z0-9]", "", extensao).lower()[:8]
    return f"{base}.{extensao}" if extensao else base


def em_ordem_do_databook(anexos: Iterable, nome: Callable[[str], str] = lambda texto: texto) -> list:
    """Ordem dos documentos de uma etapa na tela e no databook: a escolhida pelo usuário (Anexo.ordem) e, sem ordem
    escolhida, a alfabética do nome do arquivo, como no sistema antigo. Anexo enviado depois de ordenar vai para o fim."""
    return sorted(anexos, key=lambda a: (a.ordem is None, a.ordem or 0, nome(a.nome).lower(), a.id))


def _pasta_relativa(pasta: str) -> str:
    partes = [p for p in re.split(r"[\\/]+", pasta) if p]
    if any(p in (".", "..") for p in partes):
        raise ValueError(f"Pasta inválida: {pasta!r}")
    return "/".join(partes)


def _destino(pasta: str, nome: str) -> tuple[Path, str]:
    """Caminho absoluto e relativo de um arquivo novo, com carimbo de data para nunca sobrescrever outro."""
    relativo = f"{_pasta_relativa(pasta)}/{agora_local():%Y%m%d%H%M%S}_{secrets.token_hex(3)}_{nome}"
    absoluto = config().pasta_arquivos / relativo
    absoluto.parent.mkdir(parents=True, exist_ok=True)
    return absoluto, relativo


def conferir_conteudo(inicio: bytes, extensao: str) -> bool:
    esperado = _ASSINATURAS.get(extensao)
    return esperado is None or any(inicio.startswith(a) for a in esperado)


def salvar_upload(
    arquivo: UploadFile,
    pasta: str,
    extensoes: set[str] = DOCUMENTOS,
    limite_mb: int = LIMITE_PADRAO_MB,
) -> tuple[str, str]:
    """Grava um arquivo enviado pela tela. Devolve (caminho relativo, nome original para mostrar)."""
    nome_original = Path(arquivo.filename or "").name or "arquivo"
    nome = nome_seguro(nome_original)
    extensao = Path(nome).suffix.lower()
    if extensao not in extensoes:
        aceitos = ", ".join(sorted(e.lstrip(".").upper() for e in extensoes))
        raise HTTPException(422, f"O arquivo '{nome_original}' não é aceito aqui. Tipos aceitos: {aceitos}.")
    limite = limite_mb * 1024 * 1024
    conteudo = arquivo.file.read(limite + 1)
    if len(conteudo) > limite:
        raise HTTPException(413, f"O arquivo '{nome_original}' passa do limite de {limite_mb} MB.")
    if not conteudo:
        raise HTTPException(422, f"O arquivo '{nome_original}' está vazio.")
    if not conferir_conteudo(conteudo[:16], extensao):
        raise HTTPException(422, f"O conteúdo de '{nome_original}' não é de um arquivo {extensao.lstrip('.').upper()}.")
    absoluto, relativo = _destino(pasta, nome)
    absoluto.write_bytes(conteudo)
    return relativo, nome_original


def salvar_bytes(conteudo: bytes, pasta: str, nome: str) -> str:
    """Grava um arquivo gerado pelo sistema (PDF de relatório, PDF carimbado...). Devolve o caminho relativo."""
    absoluto, relativo = _destino(pasta, nome_seguro(nome))
    absoluto.write_bytes(conteudo)
    return relativo


def copiar_arquivo(relativo_origem: str, pasta: str, nome: str | None = None) -> str | None:
    """Copia um arquivo já guardado para outra pasta (ex.: certificado da corrida para o lote novo)."""
    origem = caminho_seguro(relativo_origem)
    if not origem:
        return None
    return salvar_bytes(origem.read_bytes(), pasta, nome or origem.name)


def caminho_seguro(relativo: str | None) -> Path | None:
    """Caminho do arquivo dentro da pasta de arquivos; None se ele tentar sair dela ou não existir."""
    base = config().pasta_arquivos
    if not relativo:
        return None
    caminho = (base / relativo).resolve()
    if base != caminho and base not in caminho.parents:
        return None
    return caminho if caminho.is_file() else None


def resposta_arquivo(relativo: str | None, nome: str, baixar: bool = False) -> FileResponse:
    """Entrega um arquivo guardado. PDF e imagem abrem no navegador; o resto só é baixado (nunca interpretado)."""
    caminho = caminho_seguro(relativo)
    if not caminho:
        raise HTTPException(404, f"O arquivo '{nome}' não foi encontrado no servidor.")
    tipo = TIPOS_CONTEUDO.get(caminho.suffix.lower())
    abre_no_navegador = not baixar and caminho.suffix.lower() in PDF | IMAGENS
    return FileResponse(
        caminho,
        media_type=tipo or "application/octet-stream",
        filename=nome,
        content_disposition_type="inline" if abre_no_navegador else "attachment",
    )
