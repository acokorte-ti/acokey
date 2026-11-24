"""Verificação dimensional automática de relatório RIP-33A (PDF).

Duas entradas, como no sistema antigo (legado/app.py: verificar_dimensional, verificar_dimensional_anexo):
- um PDF enviado na hora (só é lido, não fica guardado);
- um anexo já existente de um lote (na etapa dimensional, a tela da etapa liga para /verificar-dimensional?anexo=ID).
"""
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.arquivos import LIMITE_PADRAO_MB, caminho_seguro, conferir_conteudo
from app.db import get_db
from app.dimensional import analisar_rip33a
from app.models import Anexo, Lote
from app.seguranca import QUALIDADE, Contexto

rota = APIRouter()


@rota.post("/dimensional/verificar")
def verificar_upload(arquivo: UploadFile = File(...), _: Contexto = Depends(QUALIDADE)) -> dict:
    nome = Path(arquivo.filename or "").name or "arquivo.pdf"
    if Path(nome).suffix.lower() != ".pdf":
        raise HTTPException(422, f"O arquivo '{nome}' não é PDF. Envie o relatório RIP-33A em PDF.")
    limite = LIMITE_PADRAO_MB * 1024 * 1024
    conteudo = arquivo.file.read(limite + 1)
    if len(conteudo) > limite:
        raise HTTPException(413, f"O arquivo '{nome}' passa do limite de {LIMITE_PADRAO_MB} MB.")
    if not conteudo:
        raise HTTPException(422, f"O arquivo '{nome}' está vazio.")
    if not conferir_conteudo(conteudo[:16], ".pdf"):
        raise HTTPException(422, f"O conteúdo de '{nome}' não é de um arquivo PDF.")
    return {"nome": nome, "anexo": None, "lote": None, "resultado": analisar_rip33a(dados=conteudo)}


@rota.get("/dimensional/anexos/{anexo_id}")
def verificar_anexo(anexo_id: int, _: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> dict:
    anexo = db.get(Anexo, anexo_id)
    if not anexo or anexo.removido_em:
        raise HTTPException(404, "Anexo não encontrado.")
    lote = db.get(Lote, anexo.lote_id)
    if lote is None or lote.cancelado_em:
        raise HTTPException(404, "Anexo não encontrado.")
    if ".pdf" not in (Path(anexo.arquivo or "").suffix.lower(), Path(anexo.nome or "").suffix.lower()):
        raise HTTPException(422, "Só dá para verificar relatório em PDF.")
    caminho = caminho_seguro(anexo.arquivo)
    if not caminho:
        raise HTTPException(404, f"O arquivo '{anexo.nome}' não foi encontrado no servidor.")
    return {
        "nome": anexo.nome,
        "anexo": {"id": anexo.id, "etapa": anexo.etapa, "sub": anexo.sub},
        "lote": {"id": lote.id, "numero": lote.numero, "op": lote.op, "tipo": lote.tipo},
        "resultado": analisar_rip33a(caminho=caminho),
    }
