from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import api_auth, api_lotes
from app.config import config
from app.db import SessionLocal
from app.sementes import semear


@asynccontextmanager
async def ciclo(_: FastAPI):
    with SessionLocal() as db:
        semear(db)
    yield


_dev = config().app_env == "dev"
app = FastAPI(
    title="AçoKey Q",
    lifespan=ciclo,
    # A documentação automática fica desligada em produção (menos superfície exposta)
    docs_url="/api/docs" if _dev else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if _dev else None,
)

for modulo in (api_auth, api_lotes):
    app.include_router(modulo.rota, prefix="/api")


@app.get("/api/saude")
def saude() -> dict:
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.exception_handler(RequestValidationError)
async def erro_validacao(_: Request, erro: RequestValidationError) -> JSONResponse:
    """Troca o erro técnico (e em inglês) do FastAPI por uma frase que o usuário entende."""
    partes = []
    for e in erro.errors():
        nomes = [p for p in e.get("loc", ()) if isinstance(p, str) and p not in ("body", "query", "path")]
        campo = ROTULOS.get(nomes[-1], nomes[-1]) if nomes else ""
        mensagem = _traduzir(e)
        partes.append(f"{campo}: {mensagem}" if campo else mensagem)
    return JSONResponse(status_code=422, content={"detail": "; ".join(partes) or "Dados inválidos."})


ROTULOS = {
    "login": "Login", "senha": "Senha", "senha_atual": "Senha atual", "senha_nova": "Senha nova",
    "nome": "Nome", "cargo": "Cargo", "modulos": "Módulos", "admin": "Administrador",
    "pode_aprovar": "Pode aprovar", "ativo": "Ativo", "de": "Data inicial", "ate": "Data final",
    "lote_id": "Lote", "pagina": "Página", "tamanho": "Tamanho da página",
}  # fmt: skip


def _traduzir(e: dict) -> str:
    tipo, ctx = e.get("type", ""), e.get("ctx") or {}
    if tipo == "missing":
        return "campo obrigatório"
    if tipo == "string_too_short":
        return f"precisa ter pelo menos {ctx.get('min_length')} caracteres"
    if tipo == "string_too_long":
        return f"pode ter no máximo {ctx.get('max_length')} caracteres"
    if tipo == "too_long":
        return f"pode ter no máximo {ctx.get('max_length')} itens"
    if tipo == "string_pattern_mismatch":
        return "contém caracteres não permitidos"
    if tipo.startswith(("int_", "float_")):
        return "precisa ser um número"
    if tipo.startswith(("datetime", "date", "time")):
        return "data ou hora inválida"
    if tipo.startswith("bool"):
        return "precisa ser sim ou não"
    if tipo in ("greater_than", "greater_than_equal", "less_than", "less_than_equal"):
        return "valor fora do intervalo permitido"
    if tipo == "value_error":
        return e.get("msg", "valor inválido").removeprefix("Value error, ")
    return "valor inválido"
