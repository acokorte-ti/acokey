"""Especificações por tipo (dureza, tração, Charpy) e cotas por desenho.

Regras (legado/app.py: especificacoes, salvar_espec_tipo, salvar_espec_cotas; legado/CLAUDE.md, seção 7.5):
- NUNCA inventar valor da especificação técnica do cliente: campo vazio fica vazio (None), nada é completado.
- Limites numéricos ficam em Numeric(8,2): mais de 2 casas decimais é recusado (arredondar seria inventar valor).
- Temperatura do Charpy e corpo de prova são texto ("Ambiente", "-20", "10 x 10 mm").
- Cotas por item (CODITEM): texto, exatamente como digitado. Salvar substitui a lista inteira do item; a lista
  anterior fica guardada na auditoria (o sistema antigo também apagava e regravava, mas sem histórico).
- Ver: Qualidade ou Cadastros. Gravar: Cadastros (era o menu Cadastros no sistema antigo).
"""
import re
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api_recursos import listar_desenhos
from app.db import get_db
from app.models import TIPOS_LOTE, EspecificacaoCota, EspecificacaoTipo
from app.seguranca import Contexto, auditar, diferencas, exigir, limpar_texto

rota = APIRouter()

VER = exigir("qualidade", "cadastros")
GRAVAR = exigir("cadastros")

CAMPOS_NUMERICOS = {
    "dureza_min": "Dureza mínima",
    "dureza_max": "Dureza máxima",
    "tr_le_min": "LE mínimo",
    "tr_le_max": "LE máximo",
    "tr_lr_min": "LR mínimo",
    "tr_lr_max": "LR máximo",
    "tr_al_min": "Alongamento mínimo",
    "tr_ra_min": "Redução de área mínima",
    "ch_med_min": "Energia média mínima",
    "ch_ind_min": "Energia individual mínima",
}
CAMPOS_TEXTO = {"ch_temp": "Temperatura de ensaio", "ch_dim_cp": "Corpo de prova"}
CAMPOS = (*CAMPOS_NUMERICOS, *CAMPOS_TEXTO)
# Pares mínimo/máximo que não podem ficar invertidos
PARES = (("dureza_min", "dureza_max", "dureza"), ("tr_le_min", "tr_le_max", "LE"), ("tr_lr_min", "tr_lr_max", "LR"))
_NUMERO = re.compile(r"^-?\d{1,6}(?:[.,]\d+)?$")
MAX_COTAS = 100


def _texto_numero(valor: Decimal | None) -> str:
    """Decimal('30.00') -> '30'; Decimal('0.50') -> '0.5'; None -> ''."""
    if valor is None:
        return ""
    texto = format(valor, "f")
    return texto.rstrip("0").rstrip(".") if "." in texto else texto


def _numero(texto: str | None, campo: str) -> Decimal | None:
    s = limpar_texto(texto or "").strip()
    if not s:
        return None
    rotulo = CAMPOS_NUMERICOS[campo]
    if not _NUMERO.match(s):
        raise HTTPException(422, f"{rotulo}: '{s}' não é um número (use, por exemplo, 30 ou 30,5).")
    valor = Decimal(s.replace(",", "."))
    if valor != valor.quantize(Decimal("0.01")):
        raise HTTPException(422, f"{rotulo}: use no máximo 2 casas decimais (o valor não é arredondado pelo sistema).")
    return valor


def _tipo_para_tela(spec: EspecificacaoTipo | None, tipo: str) -> dict:
    saida: dict = {"tipo": tipo, "cadastrada": spec is not None}
    for campo in CAMPOS_NUMERICOS:
        saida[campo] = _texto_numero(getattr(spec, campo)) if spec else ""
    for campo in CAMPOS_TEXTO:
        saida[campo] = getattr(spec, campo) if spec else ""
    return saida


def _classificar(descricao: str) -> str:
    """Tipo detectado pelo nome do desenho (mesma ordem do sistema antigo: PIN, BOX, ARK)."""
    texto = (descricao or "").upper()
    return next((t for t in ("PIN", "BOX", "ARK") if t in texto), "")


def _cota_para_tela(c: EspecificacaoCota) -> dict:
    return {"id": c.id, "descricao": c.descricao, "nominal": c.nominal, "tol_min": c.tol_min, "tol_max": c.tol_max}


def _cotas(db: Session, coditem: str) -> list[EspecificacaoCota]:
    return list(db.scalars(select(EspecificacaoCota).where(EspecificacaoCota.coditem == coditem).order_by(EspecificacaoCota.id)))


@rota.get("/especificacoes")
def ver(ctx: Contexto = Depends(VER), db: Session = Depends(get_db)) -> dict:
    specs = {s.tipo: s for s in db.scalars(select(EspecificacaoTipo))}
    contagem = dict(
        db.execute(select(EspecificacaoCota.coditem, func.count()).group_by(EspecificacaoCota.coditem)).all()
    )
    desenhos = [
        {"coditem": d["coditem"], "descricao": d["descricao"], "classificacao": _classificar(d["descricao"]),
         "n_cotas": contagem.get(d["coditem"], 0)}
        for d in listar_desenhos()
    ]  # fmt: skip
    descricao = {d["coditem"]: d["descricao"] for d in desenhos}
    itens = [{"coditem": c, "n_cotas": n, "descricao": descricao.get(c, "")} for c, n in sorted(contagem.items()) if n]
    return {
        "tipos": [_tipo_para_tela(specs.get(t), t) for t in TIPOS_LOTE],
        "desenhos": desenhos,
        "itens": itens,
        "pode_editar": ctx.tem_modulo("cadastros"),
    }


@rota.get("/especificacoes/cotas/{coditem}")
def ver_cotas(coditem: str, _: Contexto = Depends(VER), db: Session = Depends(get_db)) -> dict:
    coditem = coditem.strip()
    desenho = next((d for d in listar_desenhos() if d["coditem"] == coditem), None)
    return {
        "coditem": coditem,
        "desenho": {"descricao": desenho["descricao"], "classificacao": _classificar(desenho["descricao"])} if desenho else None,
        "cotas": [_cota_para_tela(c) for c in _cotas(db, coditem)],
    }


class EspecificacaoTipoEntrada(BaseModel):
    dureza_min: str | None = Field(None, max_length=20)
    dureza_max: str | None = Field(None, max_length=20)
    tr_le_min: str | None = Field(None, max_length=20)
    tr_le_max: str | None = Field(None, max_length=20)
    tr_lr_min: str | None = Field(None, max_length=20)
    tr_lr_max: str | None = Field(None, max_length=20)
    tr_al_min: str | None = Field(None, max_length=20)
    tr_ra_min: str | None = Field(None, max_length=20)
    ch_temp: str | None = Field(None, max_length=40)
    ch_med_min: str | None = Field(None, max_length=20)
    ch_ind_min: str | None = Field(None, max_length=20)
    ch_dim_cp: str | None = Field(None, max_length=40)


@rota.put("/especificacoes/tipos/{tipo}")
def salvar_tipo(tipo: str, corpo: EspecificacaoTipoEntrada, ctx: Contexto = Depends(GRAVAR), db: Session = Depends(get_db)) -> dict:
    tipo = tipo.strip().upper()
    if tipo not in TIPOS_LOTE:
        raise HTTPException(404, "Tipo de chaveta desconhecido (use PIN, BOX ou ARK).")
    novos: dict = {campo: _numero(getattr(corpo, campo), campo) for campo in CAMPOS_NUMERICOS}
    novos |= {campo: limpar_texto(getattr(corpo, campo) or "").strip() for campo in CAMPOS_TEXTO}
    for minimo, maximo, nome in PARES:
        if novos[minimo] is not None and novos[maximo] is not None and novos[minimo] > novos[maximo]:
            raise HTTPException(422, f"O mínimo de {nome} ({novos[minimo]}) está maior que o máximo ({novos[maximo]}).")
    spec = db.get(EspecificacaoTipo, tipo)
    antes = {campo: getattr(spec, campo) for campo in CAMPOS} if spec else {}
    if spec is None:
        spec = EspecificacaoTipo(tipo=tipo)
        db.add(spec)
    mudou = diferencas(antes, novos)  # Decimal compara pelo valor: 30 == 30.00 não conta como mudança
    for campo, valor in novos.items():
        setattr(spec, campo, valor)
    if mudou:
        auditar(db, ctx, "CRIAR" if not antes else "ALTERAR", "especificacao_tipo", tipo, mudou)
    db.commit()
    return {"mensagem": f"Especificações de {tipo} salvas.", "tipo": _tipo_para_tela(spec, tipo)}


class CotaEntrada(BaseModel):
    descricao: str = Field("", max_length=200)
    nominal: str = Field("", max_length=40)
    tol_min: str = Field("", max_length=40)
    tol_max: str = Field("", max_length=40)


class CotasEntrada(BaseModel):
    coditem: str = Field(max_length=40)
    cotas: list[CotaEntrada] = Field(default_factory=list, max_length=MAX_COTAS)


@rota.put("/especificacoes/cotas")
def salvar_cotas(corpo: CotasEntrada, ctx: Contexto = Depends(GRAVAR), db: Session = Depends(get_db)) -> dict:
    coditem = limpar_texto(corpo.coditem).strip()
    if not coditem:
        raise HTTPException(422, "Informe o código do item/desenho.")
    novas = []
    for linha, cota in enumerate(corpo.cotas, start=1):
        valores = {campo: limpar_texto(getattr(cota, campo)).strip() for campo in ("descricao", "nominal", "tol_min", "tol_max")}
        if not valores["descricao"]:
            if any(valores.values()):
                raise HTTPException(422, f"A cota da linha {linha} está sem descrição: preencha a descrição ou limpe a linha.")
            continue  # linha toda em branco: ignorada
        novas.append(valores)
    anteriores = _cotas(db, coditem)
    antes = [{k: v for k, v in _cota_para_tela(c).items() if k != "id"} for c in anteriores]
    if antes != novas:
        # Substitui a lista do item. A lista anterior fica inteira na auditoria.
        for c in anteriores:
            db.delete(c)
        db.flush()
        for valores in novas:
            db.add(EspecificacaoCota(coditem=coditem, **valores))
        auditar(db, ctx, "ALTERAR", "especificacao_cotas", coditem, {"antes": antes, "depois": novas})
    db.commit()
    if not novas:
        mensagem = f"O item {coditem} ficou sem cotas cadastradas."
    else:
        mensagem = f"Cotas do item {coditem} salvas ({len(novas)})."
    return {"mensagem": mensagem, "coditem": coditem, "cotas": [_cota_para_tela(c) for c in _cotas(db, coditem)]}
