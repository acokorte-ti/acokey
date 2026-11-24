"""Arquivos de referência que ficam na pasta de arquivos (fora do Git, porque são do cliente ou internos):

- recursos/desenhos/      desenhos das chavetas ("ORIGEM - <CODITEM> <descrição>.pdf")
- recursos/instrucoes/    instruções da Qualidade (PDF)
- recursos/relatorios/    imagens usadas nos relatórios (ex.: pontos de dureza)
- recursos/modelos/       modelos de documento de terceiros (ex.: requisição de ensaio do laboratório)

A carga do sistema antigo copia tudo para lá.
"""
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.arquivos import resposta_arquivo
from app.config import config
from app.seguranca import QUALQUER, Contexto

rota = APIRouter()

RE_DESENHO = re.compile(r"^ORIGEM\s*-\s*(\d+)\s+(.*)\.pdf$", re.IGNORECASE)


def pasta_recursos(nome: str) -> Path:
    return config().pasta_arquivos / "recursos" / nome


def listar_desenhos() -> list[dict]:
    pasta = pasta_recursos("desenhos")
    saida = []
    for arquivo in sorted(pasta.glob("*.pdf")) if pasta.is_dir() else []:
        achado = RE_DESENHO.match(arquivo.name)
        if achado:
            saida.append({"coditem": achado.group(1), "descricao": achado.group(2).strip(), "arquivo": arquivo.name})
    return saida


def caminho_recurso(pasta: str, nome: str) -> str:
    """Relativo à pasta de arquivos, só com o nome do arquivo (nada de subpastas vindas da URL)."""
    return f"recursos/{pasta}/{Path(nome).name}"


@rota.get("/recursos/desenhos")
def desenhos(_: Contexto = Depends(QUALQUER)) -> list[dict]:
    return listar_desenhos()


@rota.get("/recursos/desenhos/{coditem}")
def desenho(coditem: str, _: Contexto = Depends(QUALQUER)) -> FileResponse:
    achado = next((d for d in listar_desenhos() if d["coditem"] == coditem), None)
    if not achado:
        raise HTTPException(404, f"Não há desenho cadastrado para o item {coditem}.")
    return resposta_arquivo(caminho_recurso("desenhos", achado["arquivo"]), achado["arquivo"])


@rota.get("/recursos/instrucoes")
def instrucoes(_: Contexto = Depends(QUALQUER)) -> list[dict]:
    pasta = pasta_recursos("instrucoes")
    return [
        {"nome": p.stem, "arquivo": p.name, "tamanho_kb": p.stat().st_size // 1024}
        for p in (sorted(pasta.glob("*.pdf")) if pasta.is_dir() else [])
    ]


@rota.get("/recursos/instrucoes/{arquivo}")
def instrucao(arquivo: str, _: Contexto = Depends(QUALQUER)) -> FileResponse:
    if not arquivo.lower().endswith(".pdf"):
        raise HTTPException(404, "Instrução não encontrada.")
    return resposta_arquivo(caminho_recurso("instrucoes", arquivo), Path(arquivo).name)


@rota.get("/recursos/relatorios/{arquivo}")
def imagem_relatorio(arquivo: str, _: Contexto = Depends(QUALQUER)) -> FileResponse:
    if Path(arquivo).suffix.lower() not in (".png", ".jpg", ".jpeg"):
        raise HTTPException(404, "Imagem não encontrada.")
    return resposta_arquivo(caminho_recurso("relatorios", arquivo), Path(arquivo).name)
