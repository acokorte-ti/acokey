"""Registro das etapas do lote: formulários, aprovação por documento, anexos, fotos de registro interno, avanço,
importação em massa, certificado da corrida, PDF do registro, arquivo do laser e mapa do lote.

Portado de legado/app.py (ver_etapa, registrar, anexar, anexar_fotos_registro, excluir_anexo, avancar,
importar_lote, importar_certificado_mp, pdf_registro, laser_csv, mapa_lote). O que mudou:
- quem registra é sempre o usuário logado (o antigo pedia o nome num campo livre);
- anexo não é apagado: é marcado como removido, com motivo;
- envio de arquivo tem limite de tamanho e confere o conteúdo;
- reprovação abre NC com número sem duplicidade (numeracao.py).
"""
import csv
import io
import json
import math
import re
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import ciclo_lote, fluxo, formularios, parametros
from app.api_recursos import listar_desenhos
from app.arquivos import DOCUMENTOS, IMAGENS, copiar_arquivo, nome_seguro, resposta_arquivo, salvar_upload
from app.config import agora_local
from app.db import get_db
from app.estado import estado_lotes
from app.historico import registrar_evento
from app.lotes import buscar_lote
from app.models import (
    Anexo,
    EspecificacaoCota,
    EspecificacaoTipo,
    Evento,
    FornecedorMP,
    Lote,
    MateriaPrima,
    MateriaPrimaAnexo,
    NaoConformidade,
    Prestador,
    Registro,
)
from app.nc import abrir_nc_automatica, fechar_nc_se_aberta, nome_etapa
from app.registro_pdf import gerar_pdf_registro
from app.seguranca import QUALQUER, Contexto, auditar, celula_segura, exigir, limpar_texto

rota = APIRouter()

# Registrar, anexar, aprovar por documento, avançar e importar: quem trabalha no lote
REGISTRO = exigir("qualidade", "pcp", "producao_tt", "producao_usinagem")
MAXIMO_ARQUIVOS = 30
ESPEC_NUMEROS = ("dureza_min", "dureza_max", "tr_le_min", "tr_le_max", "tr_lr_min", "tr_lr_max", "tr_al_min", "tr_ra_min",
                 "ch_med_min", "ch_ind_min")  # fmt: skip


# ---------------------------------------------------------------- apoio


def _etapa(chave: str) -> fluxo.Etapa:
    etapa = fluxo.POR_CHAVE.get(chave)
    if not etapa:
        raise HTTPException(404, "Etapa não encontrada.")
    return etapa


def _aplicavel(etapa: fluxo.Etapa, lote: Lote) -> None:
    if not etapa.aplicavel(lote.tipo):
        raise HTTPException(422, f"A etapa '{etapa.curto}' não se aplica a lotes {lote.tipo}.")


def _sub(etapa: fluxo.Etapa, lote: Lote, sub: str) -> str:
    subs = etapa.subs_de(lote.tipo)
    if sub in subs:
        return sub
    if len(subs) == 1:
        return subs[0]
    raise HTTPException(422, "Escolha o ensaio: " + " ou ".join(fluxo.SUB_NOME[s] for s in subs) + ".")


def _report(registro: Registro) -> Any:
    dados = registro.dados if isinstance(registro.dados, dict) else {}
    return dados.get("report")


def _registro_json(r: Registro, nc: NaoConformidade | None) -> dict:
    dados = r.dados if isinstance(r.dados, dict) else {}
    report = dados.get("report")
    via = dados.get("via") or ("sistema" if isinstance(report, str) else "")
    return {
        "id": r.id,
        "sub": r.sub,
        "status": r.status,
        "quando": r.quando,
        "responsavel": r.responsavel,
        "anulado": r.anulado,
        "anulado_motivo": r.anulado_motivo,
        "via": via,
        "titulo": report.get("titulo", "") if isinstance(report, dict) else "",
        "tem_relatorio": bool(report),
        "nc": {"id": nc.id, "numero": nc.numero, "status": nc.status, "disposicao": nc.disposicao} if nc else None,
    }


def _anexo_json(a: Anexo) -> dict:
    return {"id": a.id, "sub": a.sub, "nome": a.nome, "quando": a.quando, "apenas_registro": a.apenas_registro}


def _anexos_validos(lote_id: int, chave: str):
    return select(Anexo).where(Anexo.lote_id == lote_id, Anexo.etapa == chave, Anexo.removido_em.is_(None))


def _contar_documentos(db: Session, lote_id: int, chave: str) -> int:
    """Documentos que entram no databook (as fotos "só registro interno" não contam para aprovar)."""
    return db.scalar(
        select(func.count(Anexo.id)).where(
            Anexo.lote_id == lote_id, Anexo.etapa == chave, Anexo.removido_em.is_(None), Anexo.apenas_registro.is_(False)
        )
    ) or 0


def _decimal(valor) -> float | None:
    return float(valor) if valor is not None else None


def _ficha(db: Session, lote: Lote, etapa: fluxo.Etapa) -> formularios.Ficha:
    cotas = {}
    if lote.coditem:
        cotas = {c.id: c for c in db.scalars(select(EspecificacaoCota).where(EspecificacaoCota.coditem == lote.coditem))}
    return formularios.Ficha(
        numero=lote.numero, op=lote.op, tipo=lote.tipo, qtd=lote.qtd or 0, corrida=lote.corrida or "",
        relatorio=etapa.relatorio_de(lote.tipo), espec=db.get(EspecificacaoTipo, lote.tipo), cotas=cotas,
        elementos=_elementos(db), laser_formato=parametros.ler(db, "laser_formato"),
    )  # fmt: skip


def _elementos(db: Session) -> list[str]:
    return [e.strip() for e in parametros.ler(db, "elementos_quimicos").split(",") if e.strip()]


def _trocar_corrida(db: Session, lote: Lote, corrida: str) -> dict | None:
    """Receb. MP: a corrida informada passa a ser a do lote (e o vínculo com a matéria-prima acompanha)."""
    corrida = limpar_texto(corrida or "").strip()[:60]
    if not corrida or corrida == (lote.corrida or ""):
        return None
    antes = lote.corrida
    lote.corrida = corrida
    mp = ciclo_lote.mp_da_corrida(db, corrida)
    lote.materia_prima_id = mp.id if mp else None
    registrar_evento(db, lote.id, f"Corrida do lote: {antes or '-'} → {corrida}")
    return {"corrida": [antes, corrida]}


def _limpo(valor: Any, profundidade: int = 0) -> Any:
    """O que veio da tela, pronto para gravar em JSON: sem caracteres de controle (o PostgreSQL recusa \x00), sem
    NaN/infinito e sem aninhamento ou listas sem fim."""
    if profundidade > 6:
        return None
    if isinstance(valor, str):
        return limpar_texto(valor)[:200_000]
    if isinstance(valor, bool) or valor is None or isinstance(valor, int):
        return valor
    if isinstance(valor, float):
        return valor if math.isfinite(valor) else None
    if isinstance(valor, dict):
        return {limpar_texto(str(k))[:60]: _limpo(v, profundidade + 1) for k, v in list(valor.items())[:300]}
    if isinstance(valor, list):
        return [_limpo(v, profundidade + 1) for v in valor[:300]]
    return limpar_texto(str(valor))[:1000]


# ---------------------------------------------------------------- página da etapa


@rota.get("/lotes/{lote_id}/etapas/{chave}")
def ver_etapa(lote_id: int, chave: str, sub: str = "", ctx: Contexto = Depends(QUALQUER), db: Session = Depends(get_db)) -> dict:
    lote = buscar_lote(db, lote_id)
    etapa = _etapa(chave)
    aplicavel = etapa.aplicavel(lote.tipo)
    subs = list(etapa.subs_de(lote.tipo)) if aplicavel else list(etapa.subs)
    sub = sub if sub in subs else subs[0]
    indice = fluxo.INDICE[chave]
    estados, ultimos = estado_lotes(db, [lote_id])
    estado = estados.get(lote_id, {})
    indice_real = fluxo.etapa_real(lote.tipo, estado)

    registros = list(db.scalars(select(Registro).where(Registro.lote_id == lote_id, Registro.etapa == chave).order_by(Registro.id.desc())))
    nc_por_registro: dict[int, NaoConformidade] = {}
    if registros:
        consulta = select(NaoConformidade).where(NaoConformidade.registro_id.in_([r.id for r in registros])).order_by(NaoConformidade.id)
        for nc in db.scalars(consulta):
            nc_por_registro[nc.registro_id] = nc
    anexos = list(db.scalars(_anexos_validos(lote_id, chave).order_by(Anexo.id.desc())))
    documentos = [a for a in anexos if not a.apenas_registro]

    espec = db.get(EspecificacaoTipo, lote.tipo)
    espec_json = None
    if espec:
        espec_json = {c: _decimal(getattr(espec, c)) for c in ESPEC_NUMEROS} | {"ch_temp": espec.ch_temp, "ch_dim_cp": espec.ch_dim_cp}
    cotas = []
    if lote.coditem:
        consulta = select(EspecificacaoCota).where(EspecificacaoCota.coditem == lote.coditem).order_by(EspecificacaoCota.id)
        cotas = [{"id": c.id, "descricao": c.descricao, "nominal": c.nominal, "tol_min": c.tol_min, "tol_max": c.tol_max}
                 for c in db.scalars(consulta)]  # fmt: skip
    desenho = next(({"coditem": d["coditem"], "descricao": d["descricao"]} for d in listar_desenhos() if d["coditem"] == lote.coditem),
                   None) if lote.coditem else None  # fmt: skip

    corridas_mp: list[dict] = []
    certificados_corrida = 0
    if chave == "receb_mp":
        consulta = (select(MateriaPrima).where(MateriaPrima.corrida != "", MateriaPrima.cancelado_em.is_(None))
                    .order_by(MateriaPrima.id.desc()).limit(300))  # fmt: skip
        corridas_mp = [{"corrida": m.corrida, "nf_entrada": m.nf_entrada, "fornecedor": m.fornecedor, "tipo_destino": m.tipo_destino,
                        "status": m.status} for m in db.scalars(consulta)]  # fmt: skip
        mp = ciclo_lote.mp_da_corrida(db, lote.corrida) if lote.corrida and not documentos else None
        if mp:
            certificados_corrida = db.scalar(
                select(func.count(MateriaPrimaAnexo.id)).where(
                    MateriaPrimaAnexo.materia_prima_id == mp.id, MateriaPrimaAnexo.removido_em.is_(None)
                )
            ) or 0

    hoje = agora_local()
    laser_formato = parametros.ler(db, "laser_formato")
    return {
        "lote": {
            "id": lote.id, "numero": lote.numero, "op": lote.op, "tipo": lote.tipo, "qtd": lote.qtd, "corrida": lote.corrida,
            "coditem": lote.coditem, "cursor": lote.etapa, "concluido": indice_real >= fluxo.CONCLUIDO,
        },  # fmt: skip
        "etapa": {
            "chave": etapa.chave, "indice": indice, "nome": etapa.nome_de(lote.tipo), "curto": etapa.curto_de(lote.tipo),
            "setor": etapa.setor, "formulario": etapa.formulario, "exige_anexo": etapa.exige_anexo,
            "relatorio": etapa.relatorio_de(lote.tipo), "aplicavel": aplicavel,
            "situacao": fluxo.situacao_etapa(indice, lote.tipo, estado, indice_real),
            "subs": [{"sub": s, "nome": fluxo.SUB_NOME.get(s, s),
                      "status": (ultimos[(lote_id, chave, s)].status if (lote_id, chave, s) in ultimos else None)} for s in subs],
            # O formulário detalhado só vale para etapa já liberada; o atalho por documento vale para qualquer uma
            "liberada": indice <= lote.etapa,
        },  # fmt: skip
        "sub": sub,
        "pode_avancar": lote.etapa == indice and fluxo.pode_avancar(lote.etapa, lote.tipo, estado),
        "registros": [_registro_json(r, nc_por_registro.get(r.id)) for r in registros],
        "anexos": [_anexo_json(a) for a in documentos],
        "fotos_registro": [_anexo_json(a) for a in anexos if a.apenas_registro],
        "espec": espec_json,
        "cotas": cotas,
        "desenho": desenho,
        "prestadores": ciclo_lote.prestadores_para_etapa(db, chave, lote.tipo),
        "fornecedores_mp": ciclo_lote.fornecedores_mp(db) if chave == "receb_mp" else [],
        "rotulo_prestador": ciclo_lote.ROTULO_PRESTADOR_TELA.get(chave, ""),
        "equipamentos": ciclo_lote.equipamentos(db) if etapa.formulario in ("dureza", "dim", "tt") else [],
        "corridas_mp": corridas_mp,
        "certificados_corrida": certificados_corrida,
        "envios": ciclo_lote.envios_da_etapa(db, lote, chave),
        "padroes": {
            "ano": hoje.year, "trimestre": (hoje.month - 1) // 3 + 1, "laser_formato": laser_formato,
            "laser_formato_legivel": formularios.formato_laser_legivel(laser_formato), "elementos": _elementos(db),
            "usuario": ctx.usuario.nome, "parafusos": formularios.rotulo_parafusos(lote.tipo), "ciclos_tt": list(formularios.CICLOS_TT),
        },  # fmt: skip
    }


# ---------------------------------------------------------------- registro pelo formulário detalhado


class CorpoRegistro(BaseModel):
    sub: str = Field("", max_length=10)
    campos: dict[str, Any] = Field(default_factory=dict)


@rota.post("/lotes/{lote_id}/etapas/{chave}/registros", status_code=201)
def registrar(lote_id: int, chave: str, corpo: CorpoRegistro, ctx: Contexto = Depends(REGISTRO), db: Session = Depends(get_db)) -> dict:
    lote = buscar_lote(db, lote_id)
    etapa = _etapa(chave)
    _aplicavel(etapa, lote)
    sub = _sub(etapa, lote, corpo.sub)
    campos = _limpo(corpo.campos)
    if len(json.dumps(campos, ensure_ascii=False)) > 300_000:
        raise HTTPException(413, "O formulário está grande demais.")
    if fluxo.INDICE[chave] > lote.etapa:
        raise HTTPException(409, "Esta etapa ainda não é a etapa atual do lote. Anexe o documento e use \"Aprovar com base no "
                                 "documento anexado\": o lote avança sozinho até aqui.")  # fmt: skip
    try:
        resultado = formularios.PARSERS[etapa.formulario](campos, _ficha(db, lote, etapa), sub)
    except formularios.ErroFormulario as erro:
        raise HTTPException(422, str(erro)) from erro

    status, aviso = resultado.status, None
    if etapa.exige_anexo and status == "aprovado" and _contar_documentos(db, lote_id, chave) == 0:
        status = "pendente"
        aviso = "Anexe o certificado/relatório do fornecedor ou laboratório (PDF/imagem) e registre novamente para aprovar."
    detalhes: dict = {"etapa": chave, "sub": sub, "status": status, "via": "formulario"}
    if resultado.corrida is not None:
        detalhes |= _trocar_corrida(db, lote, resultado.corrida) or {}

    registro = Registro(
        lote_id=lote_id, etapa=chave, sub=sub, status=status, quando=agora_local(), responsavel=ctx.usuario.nome,
        usuario_id=ctx.usuario.id, dados={"report": resultado.report, "via": "formulario", "entrada": campos},
    )  # fmt: skip
    db.add(registro)
    db.flush()
    nc_aberta = nc_encerrada = None
    if status == "reprovado":
        report = resultado.report
        descricao = (report.get("titulo") or etapa.relatorio_de(lote.tipo) or etapa.curto_de(lote.tipo)) + (
            f" — {report['obs']}" if report.get("obs") else ""
        )
        nc_aberta = abrir_nc_automatica(db, ctx, lote, registro, descricao)
    elif status == "aprovado":
        nc_encerrada = fechar_nc_se_aberta(db, ctx, lote_id, chave, sub)
    registrar_evento(db, lote_id, f"{nome_etapa(chave, sub, lote.tipo)}: registro {status.upper()} por {ctx.usuario.nome}")
    acao = {"aprovado": "APROVAR", "reprovado": "REPROVAR"}.get(status, "REGISTRAR")
    auditar(db, ctx, acao, "registro", registro.id, detalhes, lote_id=lote_id)
    db.commit()
    return {
        "registro": _registro_json(registro, nc_aberta),
        "status": status,
        "aviso": aviso,
        "nc": {"id": nc_aberta.id, "numero": nc_aberta.numero} if nc_aberta else None,
        "nc_encerrada": nc_encerrada.numero if nc_encerrada else None,
    }


# ---------------------------------------------------------------- aprovar com base no documento anexado


class CorpoAprovarAnexo(BaseModel):
    corrida: str = Field("", max_length=60)
    prestador: str = Field("", max_length=30)
    obs: str = Field("", max_length=2000)


@rota.post("/lotes/{lote_id}/etapas/{chave}/aprovar-por-anexo")
def aprovar_por_anexo(
    lote_id: int, chave: str, corpo: CorpoAprovarAnexo, ctx: Contexto = Depends(REGISTRO), db: Session = Depends(get_db)
) -> dict:
    """Aprova todos os sub-registros ainda não aprovados da etapa, sem o formulário detalhado. Vale para qualquer etapa
    (o lote avança sozinho até onde estiver tudo aprovado). Etapa que não exige documento pode ser marcada como
    concluída sem anexo (operação interna sem documento próprio)."""
    lote = buscar_lote(db, lote_id)
    etapa = _etapa(chave)
    _aplicavel(etapa, lote)
    documentos = _contar_documentos(db, lote_id, chave)
    if documentos == 0 and etapa.exige_anexo:
        raise HTTPException(422, "Anexe primeiro o certificado/relatório antes de aprovar por anexo.")

    detalhes: dict = {}
    if chave == "receb_mp":
        detalhes |= _trocar_corrida(db, lote, corpo.corrida) or {}
    _, ultimos = estado_lotes(db, [lote_id])
    alvos = [s for s in etapa.subs_de(lote.tipo) if not ((r := ultimos.get((lote_id, chave, s))) and r.status == "aprovado")]
    if not alvos:
        if detalhes:
            auditar(db, ctx, "ALTERAR", "lote", lote.id, detalhes, lote_id=lote_id)
            db.commit()
        return {"aprovados": [], "mensagem": "Esta etapa já está totalmente aprovada.", "avancou": 0}

    prestador_rotulo = ""
    codigo = limpar_texto(corpo.prestador).strip().upper()
    if codigo:
        if chave == "receb_mp":
            achado = db.scalar(select(FornecedorMP).where(func.upper(FornecedorMP.codigo) == codigo))
        else:
            validos = {p["codigo"].upper() for p in ciclo_lote.prestadores_para_etapa(db, chave, lote.tipo)}
            achado = db.scalar(select(Prestador).where(func.upper(Prestador.codigo) == codigo)) if codigo in validos else None
        if not achado:
            raise HTTPException(422, "Prestador ou fornecedor não encontrado no cadastro.")
        prestador_rotulo = f"{achado.codigo} - {achado.razao_social}"

    obs = limpar_texto(corpo.obs).strip()
    titulo_base = etapa.relatorio_de(lote.tipo) or etapa.nome_de(lote.tipo)
    quem = ctx.usuario.nome
    for s in alvos:
        kv: list[list[str]] = []
        if chave == "receb_mp":
            if lote.corrida:
                kv.append(["Corrida", lote.corrida])
            if prestador_rotulo:
                kv.append(["Fornecedor da matéria-prima", prestador_rotulo])
        elif prestador_rotulo:
            kv.append([ciclo_lote.ROTULO_PRESTADOR.get(chave, "Prestador externo"), prestador_rotulo])
        if documentos:
            explicacao = "Aprovado com base no documento anexado à etapa."
            texto_evento = f"{nome_etapa(chave, s, lote.tipo)}: APROVADO pelo documento anexado, por {quem}"
            via = "documento_anexado"
        else:
            explicacao = "Etapa marcada como concluída (operação interna sem documento próprio)."
            texto_evento = f"{nome_etapa(chave, s, lote.tipo)}: concluída sem documento, por {quem}"
            via = "sem_documento"
        kv += [["Aprovado por", quem], ["Observação", explicacao]]
        titulo = f"{titulo_base} - {fluxo.SUB_NOME.get(s, s)}" if s else titulo_base
        report = {"titulo": titulo, "kv": kv, "tabelas": [], "grafico": None, "obs": obs}
        registro = Registro(lote_id=lote_id, etapa=chave, sub=s, status="aprovado", quando=agora_local(), responsavel=quem,
                            usuario_id=ctx.usuario.id, dados={"report": report, "via": via})  # fmt: skip
        db.add(registro)
        db.flush()
        fechar_nc_se_aberta(db, ctx, lote_id, chave, s)
        registrar_evento(db, lote_id, texto_evento)
        auditar(db, ctx, "APROVAR", "registro", registro.id,
                {"etapa": chave, "sub": s, "status": "aprovado", "via": via, "prestador": prestador_rotulo or None} | detalhes,
                lote_id=lote_id)  # fmt: skip
    passos = ciclo_lote.avancar_automatico(db, lote)
    db.commit()
    if len(alvos) > 1:
        mensagem = f"Etapa aprovada ({len(alvos)} ensaios) com base no documento anexado."
    elif documentos:
        mensagem = "Etapa aprovada com base no documento anexado."
    else:
        mensagem = "Etapa marcada como concluída."
    return {"aprovados": alvos, "mensagem": mensagem, "avancou": passos}


# ---------------------------------------------------------------- anexos e fotos


def _salvar_varios(arquivos: list[UploadFile], pasta: str, extensoes: set[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """Grava os que passam na conferência; os outros voltam como 'nome: motivo' (o antigo também seguia com os bons)."""
    if not arquivos:
        raise HTTPException(422, "Selecione um ou mais arquivos.")
    if len(arquivos) > MAXIMO_ARQUIVOS:
        raise HTTPException(422, f"Envie no máximo {MAXIMO_ARQUIVOS} arquivos de uma vez.")
    salvos, ignorados = [], []
    for arquivo in arquivos:
        try:
            salvos.append(salvar_upload(arquivo, pasta, extensoes))
        except HTTPException as erro:
            ignorados.append(str(erro.detail))
    return salvos, ignorados


@rota.post("/lotes/{lote_id}/etapas/{chave}/anexos", status_code=201)
def anexar(
    lote_id: int,
    chave: str,
    arquivos: list[UploadFile] = File(...),
    sub: str = Form(""),
    ctx: Contexto = Depends(REGISTRO),
    db: Session = Depends(get_db),
) -> dict:
    lote = buscar_lote(db, lote_id)
    etapa = _etapa(chave)
    _aplicavel(etapa, lote)
    sub = sub if sub in etapa.subs_de(lote.tipo) else ""
    salvos, ignorados = _salvar_varios(arquivos, f"lotes/{lote_id}/anexos", DOCUMENTOS)
    if not salvos:
        raise HTTPException(422, "Nenhum arquivo foi anexado. " + " ".join(ignorados))
    novos = []
    for relativo, nome in salvos:
        anexo = Anexo(lote_id=lote_id, etapa=chave, sub=sub, nome=limpar_texto(nome)[:255], arquivo=relativo, quando=agora_local())
        db.add(anexo)
        db.flush()
        novos.append(anexo)
        registrar_evento(db, lote_id, f"Anexo '{anexo.nome}' em {etapa.curto_de(lote.tipo)}")
        auditar(db, ctx, "CRIAR", "anexo", anexo.id, {"etapa": chave, "sub": sub, "nome": anexo.nome}, lote_id=lote_id)
    db.commit()
    return {"salvos": [_anexo_json(a) for a in novos], "ignorados": ignorados}


@rota.post("/lotes/{lote_id}/etapas/{chave}/fotos-registro", status_code=201)
def anexar_fotos_registro(
    lote_id: int, chave: str, fotos: list[UploadFile] = File(...), ctx: Contexto = Depends(REGISTRO), db: Session = Depends(get_db)
) -> dict:
    """Fotos só para registro interno (evidência): ficam na etapa, mas NÃO entram no databook do cliente."""
    lote = buscar_lote(db, lote_id)
    etapa = _etapa(chave)
    _aplicavel(etapa, lote)
    salvos, ignorados = _salvar_varios(fotos, f"lotes/{lote_id}/anexos", IMAGENS)
    if not salvos:
        raise HTTPException(422, "Nenhuma foto foi adicionada. " + " ".join(ignorados))
    novos = []
    for relativo, nome in salvos:
        anexo = Anexo(lote_id=lote_id, etapa=chave, sub="", nome=limpar_texto(nome)[:255], arquivo=relativo, quando=agora_local(),
                      apenas_registro=True)  # fmt: skip
        db.add(anexo)
        db.flush()
        novos.append(anexo)
        auditar(db, ctx, "CRIAR", "anexo", anexo.id, {"etapa": chave, "nome": anexo.nome, "apenas_registro": True}, lote_id=lote_id)
    registrar_evento(db, lote_id, f"{len(novos)} foto(s) de registro adicionada(s) em {etapa.curto_de(lote.tipo)} (não entram no databook)")
    db.commit()
    return {"salvos": [_anexo_json(a) for a in novos], "ignorados": ignorados}


class CorpoMotivo(BaseModel):
    motivo: str = Field(min_length=3, max_length=1000)


@rota.post("/anexos/{anexo_id}/remover")
def remover_anexo(anexo_id: int, corpo: CorpoMotivo, ctx: Contexto = Depends(REGISTRO), db: Session = Depends(get_db)) -> dict:
    """Nada é apagado: o anexo sai da etapa e do databook, mas o arquivo e a linha ficam (com quem, quando e por quê)."""
    anexo = db.get(Anexo, anexo_id)
    if not anexo:
        raise HTTPException(404, "Anexo não encontrado.")
    lote = buscar_lote(db, anexo.lote_id)
    if anexo.removido_em:
        raise HTTPException(409, "Este anexo já foi removido.")
    motivo = limpar_texto(corpo.motivo).strip()
    if len(motivo) < 3:
        raise HTTPException(422, "Escreva o motivo da remoção.")
    anexo.removido_em = agora_local()
    anexo.removido_por = ctx.usuario.nome
    anexo.removido_motivo = motivo
    origem = fluxo.POR_CHAVE[anexo.etapa].curto_de(lote.tipo) if anexo.etapa in fluxo.POR_CHAVE else "arquivos avulsos"
    registrar_evento(db, lote.id, f"Anexo '{anexo.nome}' removido de {origem} por {ctx.usuario.nome} — {motivo}")
    auditar(db, ctx, "REMOVER", "anexo", anexo.id, {"nome": anexo.nome, "etapa": anexo.etapa, "sub": anexo.sub, "motivo": motivo},
            lote_id=lote.id)  # fmt: skip
    db.commit()
    return {"ok": True}


@rota.post("/lotes/{lote_id}/importar-certificado-mp", status_code=201)
def importar_certificado_mp(lote_id: int, ctx: Contexto = Depends(REGISTRO), db: Session = Depends(get_db)) -> dict:
    """Copia o certificado da corrida (cadastrado em Matéria-prima) para a etapa Receb. MP do lote.

    Prefere as cópias carimbadas ('_APROVADO'); sem elas, a revisão mais recente."""
    lote = buscar_lote(db, lote_id)
    if not lote.corrida:
        raise HTTPException(422, "Este lote não tem corrida vinculada.")
    mp = ciclo_lote.mp_da_corrida(db, lote.corrida)
    if not mp:
        raise HTTPException(404, f"Corrida {lote.corrida} não encontrada em Matéria-prima.")
    linhas = list(db.scalars(
        select(MateriaPrimaAnexo)
        .where(MateriaPrimaAnexo.materia_prima_id == mp.id, MateriaPrimaAnexo.removido_em.is_(None))
        .order_by(MateriaPrimaAnexo.id.desc())
    ))  # fmt: skip
    carimbados = [a for a in linhas if "_APROVADO" in (a.nome or "")]
    escolhidos = carimbados or linhas[:1]
    vistos: set[str] = set()
    novos, falhas = [], 0
    for certificado in escolhidos:
        chave_nome = (certificado.nome or "").lower()
        if chave_nome in vistos:
            continue
        vistos.add(chave_nome)
        relativo = copiar_arquivo(certificado.arquivo, f"lotes/{lote_id}/anexos", nome_seguro(certificado.nome))
        if not relativo:
            falhas += 1
            continue
        anexo = Anexo(lote_id=lote_id, etapa="receb_mp", sub="", nome=certificado.nome, arquivo=relativo, quando=agora_local())
        db.add(anexo)
        db.flush()
        novos.append(anexo)
    if not novos:
        raise HTTPException(422, "Nenhum certificado foi importado: a corrida pode estar sem anexos ou o arquivo original sumiu.")
    registrar_evento(db, lote_id, f"{len(novos)} certificado(s) da corrida {mp.corrida} importado(s) em Receb. MP (atalho)")
    auditar(db, ctx, "IMPORTAR", "anexo", ",".join(str(a.id) for a in novos), {"origem": f"corrida {mp.corrida}", "qtd": len(novos)},
            lote_id=lote_id)  # fmt: skip
    db.commit()
    mensagem = f"{len(novos)} certificado(s) da corrida {mp.corrida} anexado(s) à etapa."
    if falhas:
        mensagem += f" ({falhas} arquivo(s) não foram encontrados no servidor e foram ignorados.)"
    return {"mensagem": mensagem + " Agora é só aprovar com base no documento.", "salvos": [_anexo_json(a) for a in novos]}


# ---------------------------------------------------------------- avanço do lote


class CorpoAvancar(BaseModel):
    forcar: bool = False
    motivo: str = Field("", max_length=1000)


@rota.post("/lotes/{lote_id}/avancar")
def avancar(lote_id: int, corpo: CorpoAvancar | None = None, ctx: Contexto = Depends(REGISTRO), db: Session = Depends(get_db)) -> dict:
    """"Concluir etapa atual e liberar para a próxima": anda o cursor uma etapa (e pula as que não se aplicam ao tipo)."""
    corpo = corpo or CorpoAvancar()
    lote = buscar_lote(db, lote_id)
    estados, _ = estado_lotes(db, [lote_id])
    if not fluxo.pode_avancar(lote.etapa, lote.tipo, estados.get(lote_id, {})):
        raise HTTPException(409, "A etapa atual ainda não está aprovada.")
    mp = ciclo_lote.mp_do_lote(db, lote)
    motivo = limpar_texto(corpo.motivo).strip()
    forcado = False
    if mp and mp.status == "reprovada":
        if not corpo.forcar:
            auditar(db, ctx, "TENTATIVA_BLOQUEADA", "lote", lote.id, {"motivo": f"avanço com MP reprovada (corrida {lote.corrida})"},
                    lote_id=lote.id)  # fmt: skip
            db.commit()
            raise HTTPException(409, f"A corrida {lote.corrida} está REPROVADA em Matéria-prima. Isso trava o fluxo: revise a "
                                     "matéria-prima antes de avançar.")  # fmt: skip
        if not ctx.usuario.pode_aprovar:
            raise HTTPException(403, "Só quem pode aprovar pode avançar um lote com a matéria-prima reprovada.")
        if len(motivo) < 5:
            raise HTTPException(422, "Escreva o motivo para avançar com a matéria-prima reprovada.")
        forcado = True
    antes = lote.etapa
    nome = fluxo.ETAPAS[antes].curto_de(lote.tipo)
    while True:
        lote.etapa += 1
        if lote.etapa >= fluxo.CONCLUIDO or fluxo.ETAPAS[lote.etapa].aplicavel(lote.tipo):
            break
    lote.etapa_desde = agora_local()
    texto = f"Etapa '{nome}' concluída e liberada"
    if forcado:
        texto += f" (matéria-prima reprovada; liberado por {ctx.usuario.nome}: {motivo})"
    registrar_evento(db, lote.id, texto)
    auditar(db, ctx, "AVANCAR", "lote", lote.id, {"etapa": [antes, lote.etapa], "nome": nome} | ({"forcado": motivo} if forcado else {}),
            lote_id=lote.id)  # fmt: skip
    db.commit()
    return {"etapa": lote.etapa, "mensagem": f"Etapa '{nome}' concluída."}


# ---------------------------------------------------------------- importação em massa (por prefixo do nome do arquivo)


def _registro_importado(db: Session, ctx: Contexto, lote: Lote, chave: str, sub: str, titulo: str, obs: str, documento: str) -> Registro:
    agora = agora_local()
    kv = [["Documento", documento or "N/A (operação interna)"], ["Origem", "Importação de documentos do lote"],
          ["Data da importação", agora.strftime("%d/%m/%Y %H:%M")]]  # fmt: skip
    report = {"titulo": titulo, "kv": kv, "tabelas": [], "grafico": None, "obs": obs}
    registro = Registro(lote_id=lote.id, etapa=chave, sub=sub, status="aprovado", quando=agora, responsavel=ctx.usuario.nome,
                        usuario_id=ctx.usuario.id, dados={"report": report, "via": "importacao"})  # fmt: skip
    db.add(registro)
    db.flush()
    fechar_nc_se_aberta(db, ctx, lote.id, chave, sub)
    auditar(db, ctx, "APROVAR", "registro", registro.id, {"etapa": chave, "sub": sub, "status": "aprovado", "via": "importacao",
                                                           "documento": documento or None}, lote_id=lote.id)  # fmt: skip
    return registro


@rota.post("/lotes/{lote_id}/importar", status_code=201)
def importar_lote(lote_id: int, arquivos: list[UploadFile] = File(...), ctx: Contexto = Depends(REGISTRO),
                  db: Session = Depends(get_db)) -> dict:  # fmt: skip
    """Cada arquivo com prefixo numérico do checklist (ex.: '3-Relatorio de dureza.pdf') vai para a etapa certa e a
    aprova; os sem prefixo conhecido ficam como avulsos do lote (registro interno, fora do databook)."""
    lote = buscar_lote(db, lote_id)
    indice = ciclo_lote.PERFIL_INDICE.get(lote.tipo)
    if not indice:
        raise HTTPException(422, f"O tipo {lote.tipo} não tem índice de importação definido.")
    mapa = ciclo_lote.IMPORT_INDEX[indice]
    salvos, ignorados = _salvar_varios(arquivos, f"lotes/{lote_id}/anexos", DOCUMENTOS)
    if not salvos:
        raise HTTPException(422, "Nenhum arquivo foi importado. " + " ".join(ignorados))
    importados, avulsos = [], []
    for relativo, nome in salvos:
        nome = limpar_texto(nome)[:255]
        prefixo = re.match(r"^(\d+)", nome)
        destinos = [d for d in mapa.get(prefixo.group(1), []) if fluxo.POR_CHAVE[d[0]].aplicavel(lote.tipo)] if prefixo else []
        if not destinos:
            anexo = Anexo(lote_id=lote_id, etapa="outros", sub="", nome=nome, arquivo=relativo, quando=agora_local(), apenas_registro=True)
            db.add(anexo)
            db.flush()
            auditar(db, ctx, "CRIAR", "anexo", anexo.id, {"etapa": "outros", "nome": nome, "apenas_registro": True}, lote_id=lote_id)
            avulsos.append(nome)
            continue
        for chave, sub, titulo in destinos:
            anexo = Anexo(lote_id=lote_id, etapa=chave, sub=sub, nome=nome, arquivo=relativo, quando=agora_local())
            db.add(anexo)
            db.flush()
            auditar(db, ctx, "CRIAR", "anexo", anexo.id, {"etapa": chave, "sub": sub, "nome": nome, "via": "importacao"}, lote_id=lote_id)
            _registro_importado(db, ctx, lote, chave, sub, titulo, f"Documento '{nome}' importado como relatório final da etapa.", nome)
            importados.append(f"{nome} → {nome_etapa(chave, sub, lote.tipo)}")

    _, ultimos = estado_lotes(db, [lote_id])
    for chave, sub in ciclo_lote.ETAPAS_AUTO_APROVAR.get(indice, []):
        etapa = fluxo.POR_CHAVE[chave]
        existente = ultimos.get((lote_id, chave, sub))
        if not etapa.aplicavel(lote.tipo) or (existente and existente.status == "aprovado"):
            continue
        _registro_importado(db, ctx, lote, chave, sub, etapa.relatorio_de(lote.tipo) or etapa.nome_de(lote.tipo),
                            f"Etapa marcada como concluída na importação (o checklist de {ciclo_lote.NOME_INDICE[indice]} não "
                            "tem documento próprio para ela).", "")  # fmt: skip
    passos = ciclo_lote.avancar_automatico(db, lote)
    registrar_evento(db, lote_id, f"Importação de documentos ({ciclo_lote.NOME_INDICE[indice]}): {len(importados)} documento(s), "
                                  f"{len(avulsos)} avulso(s), {len(ignorados)} ignorado(s)")  # fmt: skip
    auditar(db, ctx, "IMPORTAR", "lote", lote_id, {"importados": len(importados), "avulsos": len(avulsos), "ignorados": len(ignorados)},
            lote_id=lote_id)  # fmt: skip
    db.commit()
    return {"importados": importados, "avulsos": avulsos, "ignorados": ignorados, "avancou": passos}


# ---------------------------------------------------------------- PDF do registro, arquivo do laser e mapa


@rota.get("/registros/{registro_id}/pdf", response_model=None)
def pdf_registro(registro_id: int, _: Contexto = Depends(QUALQUER), db: Session = Depends(get_db)) -> Response | FileResponse:
    registro = db.get(Registro, registro_id)
    if not registro:
        raise HTTPException(404, "Registro não encontrado.")
    lote = buscar_lote(db, registro.lote_id, incluir_cancelado=True)
    report = _report(registro)
    if isinstance(report, str):
        # Relatório gerado pelo próprio sistema (dureza, TT, visual): o PDF já está anexado à etapa
        anexo = db.scalar(
            _anexos_validos(registro.lote_id, registro.etapa).where(Anexo.apenas_registro.is_(False)).order_by(Anexo.id.desc()).limit(1)
        )
        if not anexo:
            raise HTTPException(404, "O PDF deste relatório não está mais anexado à etapa.")
        return resposta_arquivo(anexo.arquivo, anexo.nome)
    if not isinstance(report, dict):
        raise HTTPException(404, "Este registro não tem relatório para gerar.")
    conteudo = gerar_pdf_registro(db, lote, registro, report)
    cabecalho = {"Content-Disposition": f'inline; filename="relatorio_{registro_id}.pdf"'}
    return Response(conteudo, media_type="application/pdf", headers=cabecalho)


@rota.get("/lotes/{lote_id}/laser.csv")
def laser_csv(lote_id: int, _: Contexto = Depends(QUALQUER), db: Session = Depends(get_db)) -> Response:
    """Códigos gravados a laser em cada peça (um por linha), para a máquina de gravação."""
    lote = buscar_lote(db, lote_id)
    _, ultimos = estado_lotes(db, [lote_id])
    registro = ultimos.get((lote_id, "visual", ""))
    if not registro or registro.status != "aprovado":
        raise HTTPException(404, "A inspeção visual deste lote ainda não está aprovada.")
    dados = registro.dados if isinstance(registro.dados, dict) else {}
    report = dados.get("report")
    codigos = report.get("laser") if isinstance(report, dict) else None
    codigos = codigos or dados.get("laser_codigos")
    if not codigos:
        # Aprovado por documento, importação ou relatório do sistema: calcula com a mesma fórmula, pela data da aprovação
        quando = registro.quando or agora_local()
        quantidade = int(formularios.num(dados.get("laser_qtd")) or formularios.num(dados.get("qtd_inspecionada")) or lote.qtd or 0)
        try:
            codigos = formularios.codigos_laser(parametros.ler(db, "laser_formato"), str(quando.year), str((quando.month - 1) // 3 + 1),
                                                lote.corrida, lote.numero, quantidade)  # fmt: skip
        except formularios.ErroFormulario as erro:
            raise HTTPException(422, str(erro)) from erro
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";")
    escritor.writerow(["sequencial", "codigo_gravacao"])
    for n, codigo in enumerate(codigos, 1):
        escritor.writerow([n, celula_segura(str(codigo))])
    nome = nome_seguro(f"laser_lote_{lote.numero}.csv")
    return Response(saida.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})  # fmt: skip


@rota.get("/lotes/{lote_id}/mapa")
def mapa_lote(lote_id: int, _: Contexto = Depends(QUALQUER), db: Session = Depends(get_db)) -> dict:
    """Mapa consolidado do lote para consulta e impressão: cada etapa aplicável (e cada ensaio), situação, quem
    aprovou e quando, documentos anexados (os do databook) e o histórico completo."""
    lote = buscar_lote(db, lote_id)
    estados, ultimos = estado_lotes(db, [lote_id])
    indice_real = fluxo.etapa_real(lote.tipo, estados.get(lote_id, {}))
    anexos = list(db.scalars(select(Anexo).where(Anexo.lote_id == lote_id, Anexo.removido_em.is_(None),
                                                 Anexo.apenas_registro.is_(False)).order_by(Anexo.id)))  # fmt: skip
    linhas = []
    for etapa in fluxo.ETAPAS:
        if not etapa.aplicavel(lote.tipo):
            continue
        for s in etapa.subs_de(lote.tipo):
            r = ultimos.get((lote_id, etapa.chave, s))
            linhas.append({
                "etapa": etapa.chave, "sub": s,
                "nome": etapa.curto_de(lote.tipo) + (f" / {fluxo.SUB_NOME[s]}" if s else ""),
                "setor": etapa.setor, "status": r.status if r else "pendente",
                "quando": r.quando if r else None, "responsavel": r.responsavel if r else "",
                "anexos": [_anexo_json(a) for a in anexos if a.etapa == etapa.chave and a.sub in (s, "")],
            })  # fmt: skip
    eventos = db.scalars(select(Evento).where(Evento.lote_id == lote_id).order_by(Evento.id))
    aplicaveis = [i for i, e in enumerate(fluxo.ETAPAS) if e.aplicavel(lote.tipo)]
    posicao = next((n for n, i in enumerate(aplicaveis, 1) if i >= indice_real), len(aplicaveis))
    return {
        "lote": {"id": lote.id, "numero": lote.numero, "op": lote.op, "tipo": lote.tipo, "qtd": lote.qtd, "corrida": lote.corrida,
                 "coditem": lote.coditem, "criado_em": lote.criado_em},  # fmt: skip
        "concluido": indice_real >= fluxo.CONCLUIDO,
        "etapa_numero": posicao,
        "total_etapas": len(aplicaveis),
        "linhas": linhas,
        "eventos": [{"quando": ev.quando, "texto": ev.texto} for ev in eventos],
    }
