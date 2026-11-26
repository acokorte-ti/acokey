"""Relatórios gerados pelo sistema: Dureza HRC (RIP-35), Tratamento Térmico e Inspeção Visual / laser.

Porte de legado/app.py (gerar_relatorio_dureza, gerar_relatorio_tt, gerar_relatorio_visual). Ao salvar cada
relatório: gera o PDF (relatorios_pdf.py), grava o Anexo na etapa, grava o Registro aprovado/reprovado (com os
dados no formato novo: as leituras de dureza na chave `leituras`), registra o evento, audita, abre NC automática
se reprovado ou encerra a NC de retrabalho se aprovado, e avança o cursor do lote se ele estava parado na etapa.

Diferenças do antigo:
- No antigo estas telas nasceram no "modo de teste". Aqui ficam ligadas normalmente (decisão da Qualidade).
- Quem grava é sempre o usuário logado (registro.responsavel e usuario_id); "Executado por" e "Aprovado por" são
  escolhidos numa lista de usuários ativos ("Aprovado por" só aceita quem pode aprovar).
- Especificação de dureza não cadastrada bloqueia (o antigo usava 30/39 HRc no TT). Durômetro é obrigatório.
- "Usar como está" na inspeção visual exige quem pode aprovar e o número da RNC; a NC aberta da etapa é
  encerrada com essa disposição.
"""
import re
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import fluxo, parametros
from app.api_cargas_tt import aguardando_tt, carga_ativa_do_lote, lotes_das_cargas
from app.arquivos import IMAGENS, caminho_seguro, salvar_bytes, salvar_upload
from app.config import agora_local
from app.db import get_db
from app.estado import ultimos_registros
from app.historico import registrar_evento
from app.lotes import buscar_lote
from app.models import Anexo, CargaTT, Lote, NaoConformidade, OrdemProducao, Registro, Usuario
from app.nc import abrir_nc_automatica, fechar_nc_se_aberta
from app.pdf_comum import caminho_assinatura, empresa
from app.relatorios_dados import (
    LIMITE_CPS_DUREZA,
    MATERIAL,
    PARAM_DESIGNACAO,
    PARAM_DESIGNACAO_LASER,
    PARAM_ITEM_TT,
    amostra_dureza,
    aprovadores,
    avancar_se_parado,
    buscar_aprovador,
    buscar_executor,
    cadastros_op,
    cliente_da_op,
    data_br,
    descricao_do_desenho,
    desenho_do_item,
    durometros,
    equipamento,
    equipamento_dict,
    especificacao_dureza,
    executores,
    fornecedor_da_corrida,
    fornos,
    ler_param,
    nome_peca,
    rotulo_equipamento,
    texto_equipamento,
)
from app.relatorios_pdf import calcular_status_dureza, gerar_pdf_dureza, gerar_pdf_tt, gerar_pdf_visual
from app.seguranca import QUALIDADE, Contexto, auditar, exigir, limpar_texto

rota = APIRouter()

TT = exigir("producao_tt", "qualidade")
MODULOS_QUALIDADE = ("qualidade",)
MODULOS_TT = ("producao_tt", "qualidade")
UCE = "USAR COMO ESTÁ (RNC)"
RESULTADOS_VISUAL = ("APROVADO", "REPROVADO", UCE)
_RE_LOTE_COMPLETO = re.compile(r"^\d{2}-\d-\d+$")
_RE_CAMPO_LASER = re.compile(r"\{(\w+)(?::0?(\d+)d)?\}")


# ---------------------------------------------------------------- utilidades


def _texto(valor: str | None, limite: int = 200) -> str:
    return limpar_texto(valor or "").strip()[:limite]


def _data(valor: str | None, rotulo: str) -> date | None:
    """'2026-11-24' (campo de data da tela) -> date. Vazio -> None."""
    valor = (valor or "").strip()
    if not valor:
        return None
    try:
        return date.fromisoformat(valor[:10])
    except ValueError:
        raise HTTPException(422, f"{rotulo}: data inválida.") from None


def _id(valor: str | int | None) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return 0


def _numero(valor: str | float | None, rotulo: str) -> float | None:
    """'36,0' -> 36.0. Vazio -> None."""
    if valor is None:
        return None
    if isinstance(valor, int | float):
        numero = float(valor)
    else:
        texto = valor.strip().replace(",", ".")
        if not texto:
            return None
        try:
            numero = float(texto)
        except ValueError:
            raise HTTPException(422, f"{rotulo}: use números (ex.: 36,0).") from None
    if not 0 < numero < 100:
        raise HTTPException(422, f"{rotulo}: o valor {numero:g} está fora da escala HRc. Confira o que foi digitado.")
    return numero


def _lote_basico(lote: Lote) -> dict:
    return {"id": lote.id, "numero": lote.numero, "op": lote.op, "tipo": lote.tipo, "qtd": lote.qtd,
            "corrida": lote.corrida, "coditem": lote.coditem}  # fmt: skip


def _lote_pdf(lote: Lote) -> dict:
    return {"op": lote.op, "lote": lote.numero, "tipo": lote.tipo, "qtd": lote.qtd, "coditem": lote.coditem}


def _po(cadastro: OrdemProducao | None) -> str:
    return (cadastro.po if cadastro and cadastro.po else "") or "—"


def _salvar_imagem(arquivo: UploadFile | None, pasta: str) -> str | None:
    if arquivo is None or not arquivo.filename:
        return None
    relativo, _ = salvar_upload(arquivo, pasta, IMAGENS)
    return relativo


def _gravar(db: Session, ctx: Contexto, lote: Lote, etapa: str, status: str, dados: dict, pdf: bytes, nome_pdf: str,
            texto_evento: str) -> tuple[Registro, Anexo]:  # fmt: skip
    """Anexo PDF + Registro + evento + auditoria (sem commit). A NC fica com quem chama."""
    agora = agora_local()
    anexo = Anexo(lote_id=lote.id, etapa=etapa, sub="", nome=nome_pdf, arquivo=salvar_bytes(pdf, f"lotes/{lote.id}/anexos", nome_pdf),
                  quando=agora, apenas_registro=False)  # fmt: skip
    registro = Registro(lote_id=lote.id, etapa=etapa, sub="", status=status, dados=dados, quando=agora,
                        responsavel=ctx.usuario.nome, usuario_id=ctx.usuario.id)  # fmt: skip
    db.add_all([anexo, registro])
    db.flush()
    registrar_evento(db, lote.id, texto_evento)
    auditar(db, ctx, "APROVAR" if status == "aprovado" else "REPROVAR", "registro", registro.id,
            {"etapa": etapa, "status": status, "relatorio": dados.get("report"), "anexo_id": anexo.id, "anexo": nome_pdf},
            lote_id=lote.id)  # fmt: skip
    return registro, anexo


def _assinaturas(executor: Usuario, aprovador: Usuario) -> dict:
    return {"assinatura_executado": caminho_assinatura(executor), "assinatura_aprovado": caminho_assinatura(aprovador)}


# ---------------------------------------------------------------- Dureza HRC (RIP-35)


def _info_dureza(db: Session, lote: Lote) -> dict:
    if not fluxo.POR_CHAVE["dureza"].abrivel(lote.tipo):
        raise HTTPException(422, f"O relatório de Dureza (RIP-35) não se aplica a lotes {lote.tipo}.")
    minimo, maximo, especificacao, _ = especificacao_dureza(db, lote.tipo)
    cadastro = cadastros_op(db, [lote.op]).get(lote.op)
    return {
        "cliente": cliente_da_op(db, cadastro),
        "nome_peca": nome_peca(db, lote, cadastro),
        "desenho": desenho_do_item(db, lote),
        "especificacao": especificacao,
        "esp_min": minimo,
        "esp_max": maximo,
        "padrao_aceitacao": parametros.ler(db, "especificacao_codigo"),
        "material": MATERIAL[lote.tipo],
        "po": _po(cadastro),
    }


def _imagem_pontos(tipo: str) -> str:
    """Figura dos pontos de medição, na pasta de recursos do servidor (não vai para o Git). Sem ela, o PDF sai sem a figura."""
    return {"BOX": "dureza_box.png", "ARK": "dureza_ark.png"}.get(tipo, "dureza_pin.png")


@rota.get("/relatorios/dureza/{lote_id}")
def tela_dureza(lote_id: int, ctx: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> dict:
    lote = buscar_lote(db, lote_id)
    info = _info_dureza(db, lote)
    carga = carga_ativa_do_lote(db, lote.id)
    outros = []
    if carga:  # o RIP-35 é um por lote: atalhos para os outros lotes PIN/BOX da mesma carga
        lotes = [lo for lo in lotes_das_cargas(db, [carga.id])[carga.id] if lo.id != lote.id and lo.tipo in ("PIN", "BOX")
                 and not lo.cancelado_em]  # fmt: skip
        ultimos = ultimos_registros(db, [lo.id for lo in lotes])
        for lo in lotes:
            reg = ultimos.get((lo.id, "dureza", ""))
            outros.append(_lote_basico(lo) | {"ja_feito": bool(reg and reg.status == "aprovado")})
    imagem = _imagem_pontos(lote.tipo)
    return {
        "lote": _lote_basico(lote),
        "info": info,
        "imagem_pontos": imagem,
        "tem_imagem_pontos": caminho_seguro(f"recursos/relatorios/{imagem}") is not None,
        "amostra": amostra_dureza(db, lote) | {"limite": LIMITE_CPS_DUREZA},
        "durometros": [equipamento_dict(e) for e in durometros(db)],
        "executores": executores(db, ctx, MODULOS_QUALIDADE),
        "aprovadores": aprovadores(db),
        "usuario_id": ctx.usuario.id,
        "carga": {"id": carga.id, "numero": carga.numero} if carga else None,
        "carga_outros_lotes": outros,
        "hoje": agora_local().date(),
    }


class LeituraCP(BaseModel):
    cp: str = Field("", max_length=60)
    valores: list[str | float | None] = Field(default_factory=list, max_length=5)


class DurezaEntrada(BaseModel):
    leituras: list[LeituraCP] = Field(..., max_length=LIMITE_CPS_DUREZA)
    equipamento_codigo: str = Field("", max_length=30)
    executado_por: int | None = None
    aprovado_por: int | None = None
    data: date | None = None
    data_aprovacao: date | None = None


@rota.post("/relatorios/dureza/{lote_id}")
def gerar_dureza(lote_id: int, entrada: DurezaEntrada, ctx: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> dict:
    lote = buscar_lote(db, lote_id)
    info = _info_dureza(db, lote)
    leituras, todos = [], []
    for indice, linha in enumerate(entrada.leituras, start=1):
        valores = [v for v in (_numero(x, f"Leitura do CP {indice}") for x in linha.valores) if v is not None]
        if not valores:
            continue  # linha sem leitura é ignorada, como no antigo
        cp = _texto(linha.cp, 60) or f"OP{lote.op}-DUR{indice}"
        leituras.append({"cp": cp, "valores": valores, "status": calcular_status_dureza(valores, info["esp_min"], info["esp_max"])})
        todos.extend(valores)
    if not leituras:
        raise HTTPException(422, "Informe pelo menos uma leitura de dureza.")
    e = equipamento(db, entrada.equipamento_codigo)
    if not e:
        raise HTTPException(422, "Escolha o durômetro usado no ensaio (cadastro de equipamentos).")
    executor = buscar_executor(db, _id(entrada.executado_por))
    aprovador = buscar_aprovador(db, _id(entrada.aprovado_por))
    status = calcular_status_dureza(todos, info["esp_min"], info["esp_max"])
    data_txt = data_br(entrada.data or agora_local().date())
    data_aprov = data_br(entrada.data_aprovacao) or data_txt
    carga = carga_ativa_do_lote(db, lote.id)
    dados = info | {
        "report": "dureza-sistema",
        "relatorio": "RIP-35",
        "status": status,
        "leituras": leituras,
        "equipamento": texto_equipamento(e),
        "equipamento_codigo": e.codigo,
        "inspecionado_por": executor.nome,
        "inspecionado_por_id": executor.id,
        "inspecionado_por_cargo": executor.cargo or "",
        "aprovado_por": aprovador.nome,
        "aprovado_por_id": aprovador.id,
        "aprovado_por_cargo": aprovador.cargo or "",
        "data": data_txt,
        "data_execucao": data_txt,
        "data_aprovacao": data_aprov,
        "registrado_por": ctx.usuario.nome,
        **({"carga_numero": carga.numero, "carga_id": carga.id} if carga else {}),
    }
    imagem = caminho_seguro(f"recursos/relatorios/{_imagem_pontos(lote.tipo)}")
    pdf = gerar_pdf_dureza(_lote_pdf(lote), dados | _assinaturas(executor, aprovador), empresa(db), imagem)
    reg_status = "aprovado" if status == "APROVADO" else "reprovado"
    registro, anexo = _gravar(db, ctx, lote, "dureza", reg_status, dados, pdf, f"3-RIP-35-Dureza-OP{lote.op}-{lote.tipo}.pdf",
                              f"Relatório de Dureza gerado pelo sistema (RIP-35) - {status}")  # fmt: skip
    nc = None
    if reg_status == "reprovado":
        nc = abrir_nc_automatica(db, ctx, lote, registro,
                                 f"Dureza fora da especificação ({info['esp_min']:g}-{info['esp_max']:g} HRc)")  # fmt: skip
    else:
        fechar_nc_se_aberta(db, ctx, lote.id, "dureza", "")
    avancou = reg_status == "aprovado" and avancar_se_parado(db, ctx, lote, "dureza", "relatório de Dureza (RIP-35)")
    db.commit()
    mensagem = f"Relatório de Dureza gerado ({status}) e anexado na etapa Dureza HRC."
    if nc:
        mensagem += f" Não conformidade {nc.numero} aberta."
    return {"status": status, "registro_id": registro.id, "anexo_id": anexo.id, "nc": nc.numero if nc else None,
            "avancou": avancou, "mensagem": mensagem}  # fmt: skip


# ---------------------------------------------------------------- Tratamento térmico


def _linha_tt(db: Session, lote: Lote, cadastros: dict) -> dict:
    """Uma linha da lista de lotes do relatório (cada lote com o cliente da SUA OP)."""
    return {"op": lote.op, "lote": lote.numero, "tipo": lote.tipo, "qtd": lote.qtd,
            "cliente": cliente_da_op(db, cadastros.get(lote.op)).upper(), "item": ler_param(db, PARAM_ITEM_TT, lote.tipo)}  # fmt: skip


def _info_tt(db: Session, lote: Lote) -> dict:
    minimo, maximo, _, esp_tt = especificacao_dureza(db, lote.tipo)
    cadastro = cadastros_op(db, [lote.op]).get(lote.op)
    return {"material": MATERIAL[lote.tipo], "fornecedor": fornecedor_da_corrida(db, lote), "esp_dureza": esp_tt,
            "esp_min": minimo, "esp_max": maximo, "po": _po(cadastro)}  # fmt: skip


def _carga_e_principal(db: Session, lote_id: int | None, carga_id: int | None) -> tuple[Lote, CargaTT | None, list[Lote]]:
    """(lote principal, carga, lotes da carga). Vindo da carga, o principal é o primeiro lote dela."""
    if not carga_id:
        if not lote_id:
            raise HTTPException(422, "Informe o lote ou a carga do relatório.")
        return buscar_lote(db, lote_id), None, []
    carga = db.get(CargaTT, carga_id)
    if not carga:
        raise HTTPException(404, "Carga de tratamento térmico não encontrada.")
    if carga.status == "cancelada":
        raise HTTPException(409, f"A carga {carga.numero} está cancelada.")
    lotes = [lo for lo in lotes_das_cargas(db, [carga.id])[carga.id] if not lo.cancelado_em]
    if not lotes:
        raise HTTPException(422, f"A carga {carga.numero} não tem lotes.")
    principal = next((lo for lo in lotes if lo.id == lote_id), None) if lote_id else lotes[0]
    if principal is None:
        raise HTTPException(422, f"O lote escolhido não faz parte da carga {carga.numero}.")
    return principal, carga, [principal, *[lo for lo in lotes if lo.id != principal.id]]


@rota.get("/relatorios/tt")
def tela_tt(lote: int | None = None, carga: int | None = None, ctx: Contexto = Depends(TT), db: Session = Depends(get_db)) -> dict:
    principal, carga_tt, lotes_carga = _carga_e_principal(db, lote, carga)
    info = _info_tt(db, principal)
    tempera, revenimento = fornos(db)
    if carga_tt:
        outros: list[Lote] = []
    else:
        outros = list(db.scalars(select(Lote).where(Lote.cancelado_em.is_(None), Lote.id != principal.id).order_by(Lote.id.desc())))
    cadastros = cadastros_op(db, [lo.op for lo in [principal, *lotes_carga, *outros]])
    aguardando = aguardando_tt(db, outros)
    # Lote que está numa carga em aberto: a tela sugere gerar o relatório pela carga (replica em todos os lotes)
    sugerida = None if carga_tt else carga_ativa_do_lote(db, principal.id)
    return {
        "lote": _lote_basico(principal),
        "principal": _linha_tt(db, principal, cadastros),
        "carga": {"id": carga_tt.id, "numero": carga_tt.numero, "status": carga_tt.status} if carga_tt else None,
        "carga_do_lote": {"id": sugerida.id, "numero": sugerida.numero, "status": sugerida.status} if sugerida else None,
        "lotes_carga": [_lote_basico(lo) | _linha_tt(db, lo, cadastros) for lo in lotes_carga],
        "outros_lotes": sorted(
            [_lote_basico(lo) | _linha_tt(db, lo, cadastros) | {"aguardando_tt": lo.id in aguardando} for lo in outros],
            key=lambda x: (not x["aguardando_tt"], -x["id"]),
        ),
        "info": info,
        "fornos_tempera": [equipamento_dict(e) for e in tempera],
        "fornos_revenimento": [equipamento_dict(e) for e in revenimento],
        "forno_tempera_padrao": (carga_tt.forno_tempera_codigo if carga_tt else "") or parametros.ler(db, "forno_tempera_padrao"),
        "forno_revenimento_padrao": (carga_tt.forno_revenimento_codigo if carga_tt else "")
        or parametros.ler(db, "forno_revenimento_padrao"),
        "tecnicos": executores(db, ctx, MODULOS_TT),
        "aprovadores": aprovadores(db),
        "usuario_id": ctx.usuario.id,
        "hoje": agora_local().date(),
    }


@rota.post("/relatorios/tt")
def gerar_tt(
    lote_id: str = Form(""),
    carga_id: str = Form(""),
    lotes_extras: str = Form("", description="ids separados por vírgula (lotes que entraram no mesmo forno)"),
    forno_tempera_codigo: str = Form(""),
    forno_revenimento_codigo: str = Form(""),
    pre_temp: str = Form(""),
    pre_tempo: str = Form(""),
    z2_temp: str = Form(""),
    z2_tempo: str = Form(""),
    z3_temp: str = Form(""),
    z3_tempo: str = Form(""),
    resfr_pre: str = Form("-"),
    resfr_z2: str = Form("-"),
    resfr_z3: str = Form("Óleo"),
    rev1_temp: str = Form(""),
    rev1_tempo: str = Form(""),
    rev2_temp: str = Form(""),
    rev2_tempo: str = Form(""),
    dur_pos_min: str = Form(""),
    dur_pos_max: str = Form(""),
    tecnico: str = Form(""),
    aprovado_por: str = Form(""),
    data_tratamento: str = Form(""),
    data_registro: str = Form(""),
    data_aprovacao: str = Form(""),
    obs: str = Form(""),
    grafico_tempera: UploadFile | None = File(None),
    grafico_rev1: UploadFile | None = File(None),
    grafico_rev2: UploadFile | None = File(None),
    ctx: Contexto = Depends(TT),
    db: Session = Depends(get_db),
) -> dict:
    principal, carga, lotes_carga = _carga_e_principal(db, _id(lote_id) or None, _id(carga_id) or None)
    info = _info_tt(db, principal)
    # Lotes que recebem o relatório: da carga, todos; senão, o principal e os escolhidos na tela
    if carga:
        destinatarios = lotes_carga
    else:
        destinatarios = [principal]
        for parte in dict.fromkeys(p.strip() for p in lotes_extras.split(",") if p.strip()):
            extra = db.get(Lote, _id(parte))
            if not extra or extra.cancelado_em:
                raise HTTPException(422, "Um dos lotes incluídos no tratamento não existe mais ou foi cancelado.")
            if extra.id != principal.id:
                destinatarios.append(extra)

    tempera_eq = equipamento(db, forno_tempera_codigo)
    revenimento_eq = equipamento(db, forno_revenimento_codigo)
    if forno_tempera_codigo.strip() and not tempera_eq:
        raise HTTPException(422, "O forno de têmpera escolhido não está no cadastro de equipamentos.")
    if forno_revenimento_codigo.strip() and not revenimento_eq:
        raise HTTPException(422, "O forno de revenimento escolhido não está no cadastro de equipamentos.")

    # Dureza depois do TT (verificação do técnico): os dois valores ou nenhum
    minimo_pos = _numero(dur_pos_min, "Dureza mínima encontrada")
    maximo_pos = _numero(dur_pos_max, "Dureza máxima encontrada")
    if (minimo_pos is None) != (maximo_pos is None):
        falta = "mínima" if minimo_pos is None else "máxima"
        raise HTTPException(422, f"Informe a dureza {falta} encontrada também, ou deixe os dois campos em branco se o "
                                 "técnico não fez essa verificação.")  # fmt: skip
    if minimo_pos is not None and maximo_pos is not None and minimo_pos > maximo_pos:
        raise HTTPException(422, "A dureza mínima não pode ser maior que a máxima. Confira os valores.")

    executor = buscar_executor(db, _id(tecnico))
    aprovador = buscar_aprovador(db, _id(aprovado_por))
    d_tratamento = _data(data_tratamento, "Data do tratamento")
    d_registro = _data(data_registro, "Data do registro") or agora_local().date()
    d_aprovacao = _data(data_aprovacao, "Data de aprovação") or d_registro

    cadastros = cadastros_op(db, [lo.op for lo in destinatarios])
    lotes_incluidos = [_linha_tt(db, lo, cadastros) for lo in destinatarios]
    campo = _texto
    revenimentos = [
        {"temp": campo(t, 20), "tempo": campo(tm, 20), "dureza": info["esp_dureza"]}
        for t, tm in ((rev1_temp, rev1_tempo), (rev2_temp, rev2_tempo))
        if campo(t) or campo(tm)
    ]
    dados = {
        "report": "tt-sistema",
        "material": info["material"],
        "fornecedor": info["fornecedor"],
        "esp_dureza": info["esp_dureza"],
        "po": info["po"],
        "cliente": lotes_incluidos[0]["cliente"],
        "item": lotes_incluidos[0]["item"],
        "tempera": {
            "pre_temp": campo(pre_temp, 20), "pre_tempo": campo(pre_tempo, 20),
            "z2_temp": campo(z2_temp, 20), "z2_tempo": campo(z2_tempo, 20),
            "z3_temp": campo(z3_temp, 20), "z3_tempo": campo(z3_tempo, 20),
            "resfriamento_pre": campo(resfr_pre, 30) or "-", "resfriamento_z2": campo(resfr_z2, 30) or "-",
            "resfriamento_z3": campo(resfr_z3, 30) or "-",
        },  # fmt: skip
        "revenimento": revenimentos,
        "forno_tempera_codigo": tempera_eq.codigo if tempera_eq else "",
        "forno_revenimento_codigo": revenimento_eq.codigo if revenimento_eq else "",
        "forno_tempera_desc": rotulo_equipamento(tempera_eq) if tempera_eq else "",
        "forno_revenimento_desc": rotulo_equipamento(revenimento_eq) if revenimento_eq else "",
        "tecnico_nome": executor.nome,
        "tecnico_id": executor.id,
        "tecnico_cargo": executor.cargo or "Técnico de T. Térmico",
        "aprovado_por": aprovador.nome,
        "aprovado_por_id": aprovador.id,
        "aprovado_por_cargo": aprovador.cargo or "",
        "data_tratamento": data_br(d_tratamento),
        "data_registro": data_br(d_registro),
        "data_aprovacao": data_br(d_aprovacao),
        "obs": campo(obs, 500),
        "registrado_por": ctx.usuario.nome,
    }
    if minimo_pos is not None and maximo_pos is not None:
        aprovado = minimo_pos >= info["esp_min"] and maximo_pos <= info["esp_max"]
        dados["dureza_pos_tt"] = {"minimo": minimo_pos, "maximo": maximo_pos, "especificacao": info["esp_dureza"],
                                  "status": "APROVADO" if aprovado else "REPROVADO"}  # fmt: skip

    # Tudo conferido: agora os gráficos vão para a pasta do lote principal
    pasta = f"lotes/{principal.id}/graficos_tt"
    graficos = {"tempera": _salvar_imagem(grafico_tempera, pasta), "rev1": _salvar_imagem(grafico_rev1, pasta),
                "rev2": _salvar_imagem(grafico_rev2, pasta)}  # fmt: skip
    dados["graficos"] = {k: v for k, v in graficos.items() if v}
    imagens = {k: caminho_seguro(v) if v else None for k, v in graficos.items()}
    pdf = gerar_pdf_tt(_lote_pdf(principal), dados | _assinaturas(executor, aprovador), lotes_incluidos, imagens, empresa(db))

    origem = f"Carga {carga.numero}" if carga else "Relatório pelo sistema"
    nome_pdf = f"2-Relatorio-TT-OP{principal.op}-{principal.tipo}.pdf"
    ops = "/".join(str(lo["op"]) for lo in lotes_incluidos)
    anexo_principal = registro_principal = None
    avancados = 0
    for lote in destinatarios:
        dados_lote = dados | {"origem": origem, "lotes_incluidos": lotes_incluidos}
        if carga:
            dados_lote |= {"carga_numero": carga.numero, "carga_id": carga.id}
        registro, anexo = _gravar(db, ctx, lote, "trat_termico", "aprovado", dados_lote, pdf, nome_pdf,
                                  f"Relatório de Tratamento Térmico gerado. Origem: {origem}. OPs no ciclo: {ops}")  # fmt: skip
        if lote.id == principal.id:
            anexo_principal, registro_principal = anexo, registro
        fechar_nc_se_aberta(db, ctx, lote.id, "trat_termico", "")
        avancados += avancar_se_parado(db, ctx, lote, "trat_termico", "relatório de Tratamento Térmico")
    if carga:  # gerado pela carga: ela fica concluída e aponta para o anexo do lote principal
        antes = carga.status
        carga.status = "concluida"
        carga.data_fim = carga.data_fim or agora_local()
        carga.relatorio_anexo_id = anexo_principal.id
        registrar_evento(db, principal.id, f"Carga TT {carga.numero} concluída ao gerar o relatório.")
        auditar(db, ctx, "CONCLUIR", "carga_tt", carga.id,
                {"numero": carga.numero, "status": [antes, "concluida"], "via": "relatório de TT",
                 "anexo_id": anexo_principal.id})  # fmt: skip
    db.commit()
    n = len(destinatarios)
    mensagem = (f"Relatório de Tratamento Térmico gerado, anexado e etapa avançada em {n} lotes." if n > 1
                else "Relatório de Tratamento Térmico gerado e anexado em Trat. térmico.")  # fmt: skip
    return {"lote_id": principal.id, "registro_id": registro_principal.id, "anexo_id": anexo_principal.id, "lotes": n,
            "avancados": avancados, "mensagem": mensagem}  # fmt: skip


# ---------------------------------------------------------------- Inspeção visual e marcação a laser


def formatar_laser(formato: str, **valores) -> str:
    """Aplica o formato do parâmetro laser_formato ('{ano}T{tri}-C{corrida}-L{lote}-{seq:03d}').

    Só troca os campos conhecidos (e o preenchimento com zeros '{seq:03d}'); nunca usa str.format, porque o
    formato vem de um parâmetro editável na tela.
    """

    def troca(achado: re.Match) -> str:
        nome, largura = achado.group(1), achado.group(2)
        if nome not in valores:
            return achado.group(0)
        texto = str(valores[nome])
        return texto.zfill(int(largura)) if largura else texto

    return _RE_CAMPO_LASER.sub(troca, formato)


def formato_legivel(formato: str) -> str:
    """'{ano}T{tri}-...-{seq:03d}' -> '<ano>T<tri>-...-<seq>' (como o antigo guardava no registro)."""
    return _RE_CAMPO_LASER.sub(lambda a: f"<{a.group(1)}>", formato)


def lote_completo(numero: str, ano: int | str, tri: int | str) -> str:
    """Número já no formato completo (AA-T-NNNNN) fica como está; senão monta com o ano e o trimestre do laser."""
    numero = str(numero or "").strip()
    if _RE_LOTE_COMPLETO.match(numero):
        return numero
    return f"{str(ano).strip()[-2:]}-{str(tri).strip()}-{numero}"


def _info_visual(db: Session, lote: Lote) -> dict:
    cadastro = cadastros_op(db, [lote.op]).get(lote.op)
    desenho = desenho_do_item(db, lote)
    ark = lote.tipo == "ARK"
    fosfato = "Oxidação Negra" if ark else "Fosfato de Manganês"
    parafuso = "Sextavado M10x10mm ou M10x12mm" if ark else "Sextavado M6x1x10mm"
    designacao = "ARK" if ark else ler_param(db, PARAM_DESIGNACAO)
    designacao_laser = "ARK" if ark else ler_param(db, PARAM_DESIGNACAO_LASER)
    diametro = re.search(r"(\d{2}-\d{2})", descricao_do_desenho(lote) or desenho or "")  # do nome inteiro do PDF
    return {
        "cliente": cliente_da_op(db, cadastro),
        "nome_peca": nome_peca(db, lote, cadastro),
        "desenho": desenho,
        "padrao_aceitacao": parametros.ler(db, "especificacao_codigo"),
        "po": _po(cadastro),
        "obs1": f"Verificado aspecto geral e acabamento das {designacao}'s, {fosfato}, considerado: APROVADO.",
        "obs2": f"Peças acompanham parafusos {parafuso} (01 parafuso por Peça)",
        "obs3": f"Para Rastreabilidade, foi gravado por processo a Laser: {designacao_laser}"
        + (f" + R{diametro.group(1)}" if diametro else "")
        + " + Codificação vide imagem.",
    }


@rota.get("/relatorios/visual/{lote_id}")
def tela_visual(lote_id: int, ctx: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> dict:
    lote = buscar_lote(db, lote_id)
    agora = agora_local()
    tri = (agora.month - 1) // 3 + 1
    return {
        "lote": _lote_basico(lote),
        "info": _info_visual(db, lote),
        "laser": {"formato": parametros.ler(db, "laser_formato"), "corrida": lote.corrida or "SC", "lote": lote.numero},
        "ano": agora.year,
        "tri": tri,
        "lote_completo": lote_completo(lote.numero, agora.year, tri),
        "resultados": list(RESULTADOS_VISUAL),
        "pode_usar_como_esta": ctx.usuario.pode_aprovar,
        "executores": executores(db, ctx, MODULOS_QUALIDADE),
        "aprovadores": aprovadores(db),
        "usuario_id": ctx.usuario.id,
        "hoje": agora.date(),
    }


def _encerrar_nc_uso_como_esta(db: Session, ctx: Contexto, lote: Lote, justificativa: str) -> NaoConformidade | None:
    nc = db.scalar(
        select(NaoConformidade)
        .where(NaoConformidade.lote_id == lote.id, NaoConformidade.etapa == "visual", NaoConformidade.sub == "",
               NaoConformidade.status.in_(fluxo.NC_EM_ABERTO))
        .order_by(NaoConformidade.id.desc())
    )  # fmt: skip
    if not nc:
        return None
    antes, agora = nc.status, agora_local()
    nc.disposicao, nc.justificativa = "uso_como_esta", justificativa
    nc.decidida_em, nc.decidida_por = agora, ctx.usuario.nome
    nc.status, nc.encerrada_em, nc.encerrada_por = "encerrada", agora, ctx.usuario.nome
    registrar_evento(db, lote.id, f"NC {nc.numero} encerrada como 'uso como está' pelo relatório de inspeção visual")
    auditar(db, ctx, "ENCERRAR", "nc", nc.id, {"status": [antes, "encerrada"], "disposicao": "uso_como_esta",
                                               "justificativa": justificativa, "via": "relatório visual"}, lote_id=lote.id)  # fmt: skip
    return nc


@rota.post("/relatorios/visual/{lote_id}")
def gerar_visual(
    lote_id: int,
    resultado: str = Form("APROVADO"),
    qtd: str = Form(""),
    rnc: str = Form("N/A"),
    obs1: str = Form(""),
    obs2: str = Form(""),
    obs3: str = Form(""),
    ano: str = Form(""),
    tri: str = Form(""),
    executado_por: str = Form(""),
    aprovado_por: str = Form(""),
    data: str = Form(""),
    data_aprovacao: str = Form(""),
    foto_geral: UploadFile | None = File(None),
    foto_peca: UploadFile | None = File(None),
    foto_laser: UploadFile | None = File(None),
    ctx: Contexto = Depends(QUALIDADE),
    db: Session = Depends(get_db),
) -> dict:
    lote = buscar_lote(db, lote_id)
    resultado = (resultado or "").strip().upper()
    if resultado not in RESULTADOS_VISUAL:
        raise HTTPException(422, "Resultado inválido: escolha APROVADO, REPROVADO ou USAR COMO ESTÁ (RNC).")
    quantidade = _id(qtd)
    if quantidade <= 0:
        raise HTTPException(422, "Informe a quantidade inspecionada.")
    if quantidade > 100_000:
        raise HTTPException(422, "Quantidade inspecionada grande demais. Confira o número.")
    agora = agora_local()
    ano_txt, tri_txt = (ano or str(agora.year)).strip(), (tri or str((agora.month - 1) // 3 + 1)).strip()
    if not (ano_txt.isdigit() and len(ano_txt) == 4):
        raise HTTPException(422, "Ano do código a laser inválido (use 4 dígitos, ex.: 2026).")
    if tri_txt not in ("1", "2", "3", "4"):
        raise HTTPException(422, "Trimestre do código a laser inválido (1 a 4).")
    rnc_txt = _texto(rnc, 60) or "N/A"
    if resultado == UCE:
        if not ctx.usuario.pode_aprovar:
            raise HTTPException(403, "Só quem pode aprovar pela Qualidade registra 'Usar como está'.")
        if rnc_txt.upper() in ("N/A", "NA", "-"):
            raise HTTPException(422, "Para 'Usar como está', informe o número da RNC (não conformidade) que autoriza.")
    executor = buscar_executor(db, _id(executado_por))
    aprovador = buscar_aprovador(db, _id(aprovado_por))
    d_ensaio = _data(data, "Data do ensaio") or agora.date()
    d_aprovacao = _data(data_aprovacao, "Data de aprovação") or d_ensaio

    info = _info_visual(db, lote)
    formato = parametros.ler(db, "laser_formato")
    corrida = lote.corrida or "SC"
    primeiro = formatar_laser(formato, ano=ano_txt, tri=tri_txt, corrida=corrida, lote=lote.numero, seq=1)
    ultimo = formatar_laser(formato, ano=ano_txt, tri=tri_txt, corrida=corrida, lote=lote.numero, seq=quantidade)
    data_txt = data_br(d_ensaio)
    dados = info | {
        "report": "visual-sistema",
        "qtd_inspecionada": quantidade,
        "resultado": resultado,
        "rnc": rnc_txt,
        "obs1": _texto(obs1, 400),
        "obs2": _texto(obs2, 400),
        "obs3": _texto(obs3, 400),
        "lote_completo": lote_completo(lote.numero, ano_txt, tri_txt),
        "laser_primeiro": primeiro,
        "laser_ultimo": ultimo,
        "laser_qtd": quantidade,
        "laser_formato": formato_legivel(formato),
        "inspecionado_por": executor.nome,
        "inspecionado_por_id": executor.id,
        "inspecionado_por_cargo": executor.cargo or "",
        "aprovado_por": aprovador.nome,
        "aprovado_por_id": aprovador.id,
        "aprovado_por_cargo": aprovador.cargo or "",
        "data": data_txt,
        "data_execucao": data_txt,
        "data_aprovacao": data_br(d_aprovacao),
        "registrado_por": ctx.usuario.nome,
    }
    pasta = f"lotes/{lote.id}/fotos_visual"
    fotos = {"geral": _salvar_imagem(foto_geral, pasta), "peca": _salvar_imagem(foto_peca, pasta),
             "laser": _salvar_imagem(foto_laser, pasta)}  # fmt: skip
    dados["fotos"] = {k: v for k, v in fotos.items() if v}
    imagens = {k: caminho_seguro(v) if v else None for k, v in fotos.items()}
    pdf = gerar_pdf_visual(_lote_pdf(lote), dados | _assinaturas(executor, aprovador), imagens, empresa(db))

    reg_status = "reprovado" if resultado == "REPROVADO" else "aprovado"
    registro, anexo = _gravar(db, ctx, lote, "visual", reg_status, dados, pdf,
                              f"5-Relatorio-Visual-OP{lote.op}-{lote.tipo}.pdf",
                              f"Relatório de Inspeção Visual gerado pelo sistema - {resultado}")  # fmt: skip
    nc = None
    if reg_status == "reprovado":
        descricao = "Inspeção visual reprovada" + (f" (RNC {rnc_txt})" if rnc_txt != "N/A" else "")
        nc = abrir_nc_automatica(db, ctx, lote, registro, descricao)
    elif resultado == UCE:
        _encerrar_nc_uso_como_esta(db, ctx, lote, f"Usar como está conforme RNC {rnc_txt} (relatório de inspeção visual).")
    else:
        fechar_nc_se_aberta(db, ctx, lote.id, "visual", "")
    avancou = reg_status == "aprovado" and avancar_se_parado(db, ctx, lote, "visual", "relatório de Inspeção Visual")
    db.commit()
    mensagem = f"Relatório de Inspeção Visual gerado ({resultado}) e anexado na etapa Visual / Laser."
    if nc:
        mensagem += f" Não conformidade {nc.numero} aberta."
    return {"status": resultado, "registro_id": registro.id, "anexo_id": anexo.id, "nc": nc.numero if nc else None,
            "avancou": avancou, "mensagem": mensagem}  # fmt: skip
