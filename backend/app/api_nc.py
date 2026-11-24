"""Não conformidades: lista, detalhe, decisão de disposição, reabertura e correção de dureza.

Regras do sistema antigo (legado/app.py: nao_conformidades_*, corrigir_dureza; legado/CLAUDE.md, seção 7.6):
- Retrabalho: a NC fica "em tratamento" e a etapa continua bloqueada; encerra sozinha quando um registro NOVO
  da mesma etapa for aprovado (nc.fechar_nc_se_aberta, chamado por quem grava o registro).
- Sucata: abate a quantidade sucateada do lote, encerra e libera o avanço.
- Uso como está: só quem "pode aprovar", com justificativa escrita. Encerra e libera.
- Anulada (erro de digitação): só quem "pode aprovar", com motivo escrito. Marca o REGISTRO como anulado (o fluxo
  passa a ignorá-lo) e encerra. O valor certo entra num registro NOVO da etapa.
- Correção de dureza: corrige as leituras de um registro de dureza reprovado; se ficar aprovado, a NC encerra como
  anulada. O valor de antes fica na auditoria.
A ABERTURA automática da NC fica em nc.py (chamada por quem grava o registro reprovado).
"""
import copy

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import fluxo
from app.config import agora_local
from app.db import get_db
from app.historico import registrar_evento
from app.leituras_dureza import extrair_leituras, formatar, numero, status_dureza, texto_leituras
from app.lotes import buscar_lote
from app.models import DISPOSICOES_NC, EspecificacaoTipo, Lote, NaoConformidade, Registro
from app.seguranca import APROVADOR, QUALIDADE, Contexto, auditar, limpar_texto

rota = APIRouter()

DISPOSICAO_NOME = {
    "retrabalho": "Retrabalho",
    "sucata": "Sucata",
    "uso_como_esta": "Uso como está (desvio)",
    "anulada": "Anulada (erro de digitação)",
}
ABAS = {"abertas": tuple(fluxo.NC_EM_ABERTO), "encerradas": ("encerrada",)}
MAX_TEXTO = 2000


# ---------------------------------------------------------------- leitura


def _lote_resumo(lote: Lote | None) -> dict | None:
    if lote is None:
        return None
    return {"id": lote.id, "numero": lote.numero, "op": lote.op, "tipo": lote.tipo, "qtd": lote.qtd,
            "coditem": lote.coditem, "cancelado": lote.cancelado_em is not None}  # fmt: skip


def _nc_para_tela(nc: NaoConformidade, lote: Lote | None) -> dict:
    etapa = fluxo.POR_CHAVE.get(nc.etapa)
    return {
        "id": nc.id,
        "numero": nc.numero,
        "status": nc.status,
        "etapa": nc.etapa,
        "sub": nc.sub,
        "etapa_nome": etapa.curto_de(lote.tipo) if etapa and lote else nc.etapa,
        "sub_nome": fluxo.SUB_NOME.get(nc.sub, nc.sub),
        "descricao": nc.descricao,
        "registro_id": nc.registro_id,
        "qtd_lote_na_abertura": nc.qtd_lote_na_abertura,
        "qtd_afetada": nc.qtd_afetada,
        "disposicao": nc.disposicao,
        "disposicao_nome": DISPOSICAO_NOME.get(nc.disposicao, nc.disposicao),
        "justificativa": nc.justificativa,
        "observacoes": nc.observacoes,
        "aberta_em": nc.aberta_em,
        "aberta_por": nc.aberta_por,
        "decidida_em": nc.decidida_em,
        "decidida_por": nc.decidida_por,
        "encerrada_em": nc.encerrada_em,
        "encerrada_por": nc.encerrada_por,
        "lote": _lote_resumo(lote),
    }


def _buscar_nc(db: Session, nc_id: int, travar: bool = False) -> NaoConformidade:
    consulta = select(NaoConformidade).where(NaoConformidade.id == nc_id)
    nc = db.scalar(consulta.with_for_update() if travar else consulta)
    if not nc:
        raise HTTPException(404, "Não conformidade não encontrada.")
    return nc


def _detalhe(db: Session, ctx: Contexto, nc: NaoConformidade) -> dict:
    lote = db.get(Lote, nc.lote_id)
    saida = _nc_para_tela(nc, lote)
    registro = db.get(Registro, nc.registro_id) if nc.registro_id else None
    saida["registro"] = (
        {
            "id": registro.id, "etapa": registro.etapa, "sub": registro.sub, "status": registro.status,
            "quando": registro.quando, "responsavel": registro.responsavel, "anulado": registro.anulado,
            "anulado_motivo": registro.anulado_motivo, "anulado_em": registro.anulado_em, "anulado_por": registro.anulado_por,
        }  # fmt: skip
        if registro
        else None
    )
    # O atalho de correção só existe para dureza (nas outras etapas: anular a NC e gravar um registro novo)
    saida["corrigir_dureza_disponivel"] = bool(
        registro and registro.etapa == "dureza" and registro.status == "reprovado" and not registro.anulado
    )
    saida["pode_decidir_desvio"] = ctx.usuario.pode_aprovar
    return saida


@rota.get("/nao-conformidades")
def listar(
    aba: str = Query("abertas"),
    lote_id: int | None = None,
    _: Contexto = Depends(QUALIDADE),
    db: Session = Depends(get_db),
) -> dict:
    aba = aba if aba in ABAS else "abertas"
    # NC de lote cancelado sai das listas (como o lote sai do painel); continua no banco e no detalhe
    base = select(NaoConformidade, Lote).join(Lote, Lote.id == NaoConformidade.lote_id).where(Lote.cancelado_em.is_(None))
    if lote_id is not None:
        base = base.where(NaoConformidade.lote_id == lote_id)
    linhas = db.execute(base.where(NaoConformidade.status.in_(ABAS[aba])).order_by(NaoConformidade.id.desc())).all()
    contagens = {nome: 0 for nome in ABAS}
    contar = (
        select(NaoConformidade.status, func.count())
        .join(Lote, Lote.id == NaoConformidade.lote_id)
        .where(Lote.cancelado_em.is_(None))
        .group_by(NaoConformidade.status)
    )
    if lote_id is not None:
        contar = contar.where(NaoConformidade.lote_id == lote_id)
    for status, quantidade in db.execute(contar):
        for nome, situacoes in ABAS.items():
            if status in situacoes:
                contagens[nome] += quantidade
    return {"aba": aba, "contagens": contagens, "itens": [_nc_para_tela(nc, lote) for nc, lote in linhas]}


@rota.get("/nao-conformidades/{nc_id}")
def ver(nc_id: int, ctx: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> dict:
    return _detalhe(db, ctx, _buscar_nc(db, nc_id))


# ---------------------------------------------------------------- decisão


class Decisao(BaseModel):
    disposicao: str = Field(max_length=20)
    observacoes: str = Field("", max_length=MAX_TEXTO)
    qtd_afetada: int | None = None
    justificativa: str = Field("", max_length=MAX_TEXTO)
    motivo_anulacao: str = Field("", max_length=MAX_TEXTO)


def _texto(valor: str) -> str:
    return limpar_texto(valor or "").strip()


@rota.post("/nao-conformidades/{nc_id}/decidir")
def decidir(nc_id: int, corpo: Decisao, ctx: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> dict:
    nc = _buscar_nc(db, nc_id, travar=True)
    if nc.status == "encerrada":
        raise HTTPException(409, "Esta NC já está encerrada.")
    if nc.status != "aberta":
        raise HTTPException(409, "Esta NC está em tratamento (retrabalho). Para escolher outra disposição, reabra a decisão primeiro.")
    disposicao = (corpo.disposicao or "").strip()
    if disposicao not in DISPOSICOES_NC:
        raise HTTPException(422, "Escolha uma disposição válida.")
    lote = db.scalar(select(Lote).where(Lote.id == nc.lote_id).with_for_update())
    if lote is None or lote.cancelado_em:
        raise HTTPException(409, "O lote desta NC foi cancelado: não há disposição a decidir.")
    observacoes = _texto(corpo.observacoes)
    quem = ctx.usuario.nome
    agora = agora_local()
    antes = {"status": nc.status, "disposicao": nc.disposicao}

    if disposicao == "retrabalho":
        nc.status = "em_tratamento"
        texto_evento = f"NC {nc.numero}: decisão RETRABALHO — aguardando novo registro aprovado"
        mensagem = (f"NC {nc.numero}: decisão registrada (retrabalho). O lote segue bloqueado nesta etapa até "
                    "um novo registro ser aprovado.")  # fmt: skip
        depois: dict = {"status": "em_tratamento", "disposicao": disposicao, "observacoes": observacoes}

    elif disposicao == "sucata":
        qtd_atual = lote.qtd or 0
        qtd = corpo.qtd_afetada or 0
        if qtd_atual <= 0:
            raise HTTPException(422, "O lote está com 0 peças: não há o que sucatear.")
        if qtd <= 0 or qtd > qtd_atual:
            raise HTTPException(422, f"Informe uma quantidade sucateada válida (entre 1 e {qtd_atual}).")
        lote.qtd = qtd_atual - qtd
        nc.qtd_afetada = qtd
        nc.status = "encerrada"
        texto_evento = (f"NC {nc.numero}: decisão SUCATA de {qtd} peça(s) — quantidade do lote ajustada de "
                        f"{qtd_atual} para {lote.qtd}")  # fmt: skip
        mensagem = f"NC {nc.numero} encerrada: {qtd} peça(s) sucateada(s). Quantidade do lote ajustada para {lote.qtd}."
        antes["qtd_lote"] = qtd_atual
        depois = {"status": "encerrada", "disposicao": disposicao, "qtd_afetada": qtd, "qtd_lote": lote.qtd,
                  "observacoes": observacoes}  # fmt: skip

    elif disposicao == "uso_como_esta":
        if not ctx.usuario.pode_aprovar:
            raise HTTPException(403, "Só um usuário com permissão de aprovação pode decidir 'uso como está'.")
        justificativa = _texto(corpo.justificativa)
        if not justificativa:
            raise HTTPException(422, "Informe a justificativa do desvio para aceitar 'uso como está'.")
        nc.justificativa = justificativa
        nc.status = "encerrada"
        texto_evento = f"NC {nc.numero}: decisão USO COMO ESTÁ (desvio aprovado por {quem})"
        mensagem = f"NC {nc.numero} encerrada: uso como está, com desvio aprovado por {quem}."
        depois = {"status": "encerrada", "disposicao": disposicao, "justificativa": justificativa, "observacoes": observacoes}

    else:  # anulada: erro de digitação
        if not ctx.usuario.pode_aprovar:
            raise HTTPException(403, "Só um usuário com permissão de aprovação pode anular uma NC.")
        motivo = _texto(corpo.motivo_anulacao)
        if not motivo:
            raise HTTPException(422, "Informe o motivo da anulação (ex.: 'Digitado 2,5 em vez de 25 na leitura CP-1').")
        registro = db.get(Registro, nc.registro_id) if nc.registro_id else None
        if registro is not None and not registro.anulado:
            registro.anulado = True
            registro.anulado_motivo = motivo
            registro.anulado_em = agora
            registro.anulado_por = quem
            auditar(db, ctx, "ANULAR", "registro", registro.id,
                    {"motivo": motivo, "status": registro.status, "etapa": registro.etapa, "sub": registro.sub, "nc": nc.numero},
                    lote_id=lote.id)  # fmt: skip
        nc.justificativa = motivo
        nc.status = "encerrada"
        texto_evento = (f"NC {nc.numero} ANULADA (erro de digitação) por {quem}: {motivo} — registro #{nc.registro_id} "
                        "ignorado pelo fluxo. Grave novo registro da etapa.")  # fmt: skip
        mensagem = (f"NC {nc.numero} anulada. O registro reprovado foi marcado como erro de digitação — grave um "
                    "NOVO registro da mesma etapa para continuar.")  # fmt: skip
        antes["registro_id"] = nc.registro_id
        depois = {"status": "encerrada", "disposicao": disposicao, "motivo": motivo, "registro_anulado": nc.registro_id,
                  "observacoes": observacoes}  # fmt: skip

    nc.disposicao = disposicao
    nc.observacoes = observacoes
    nc.decidida_em = agora
    nc.decidida_por = quem
    if nc.status == "encerrada":
        nc.encerrada_em = agora
        nc.encerrada_por = quem
    registrar_evento(db, lote.id, texto_evento)
    auditar(db, ctx, "DECIDIR", "nc", nc.id, {"numero": nc.numero, "antes": antes, "depois": depois}, lote_id=lote.id)
    db.commit()
    return {"mensagem": mensagem, "nc": _detalhe(db, ctx, nc)}


class Reabertura(BaseModel):
    motivo: str = Field("", max_length=MAX_TEXTO)


@rota.post("/nao-conformidades/{nc_id}/reabrir")
def reabrir(nc_id: int, corpo: Reabertura | None = None, ctx: Contexto = Depends(APROVADOR), db: Session = Depends(get_db)) -> dict:
    nc = _buscar_nc(db, nc_id, travar=True)
    if nc.status != "em_tratamento":
        raise HTTPException(409, "Só é possível reabrir a decisão de uma NC em tratamento (retrabalho).")
    motivo = _texto(corpo.motivo) if corpo else ""
    antes = {"status": nc.status, "disposicao": nc.disposicao, "decidida_em": nc.decidida_em, "decidida_por": nc.decidida_por}
    nc.status = "aberta"
    nc.disposicao = ""
    nc.decidida_em = None
    nc.decidida_por = ""
    registrar_evento(db, nc.lote_id, f"NC {nc.numero}: decisão de retrabalho desfeita — volta para aberta"
                                     + (f" ({motivo})" if motivo else ""))  # fmt: skip
    auditar(db, ctx, "REABRIR", "nc", nc.id, {"numero": nc.numero, "antes": antes, "depois": {"status": "aberta", "disposicao": ""},
                                              "motivo": motivo}, lote_id=nc.lote_id)  # fmt: skip
    db.commit()
    return {"mensagem": f"NC {nc.numero} voltou para 'aberta'.", "nc": _detalhe(db, ctx, nc)}


# ---------------------------------------------------------------- correção de dureza (erro de digitação)


def _registro_dureza(db: Session, registro_id: int, travar: bool = False) -> Registro:
    consulta = select(Registro).where(Registro.id == registro_id)
    registro = db.scalar(consulta.with_for_update() if travar else consulta)
    if not registro:
        raise HTTPException(404, "Registro não encontrado.")
    if registro.etapa != "dureza":
        raise HTTPException(422, "A correção de valores só existe para registros de dureza. Para outras etapas, anule a NC "
                                 "e grave um novo registro.")  # fmt: skip
    if registro.anulado:
        raise HTTPException(409, "Este registro já foi anulado — grave um novo registro da etapa.")
    if registro.status != "reprovado":
        raise HTTPException(409, "Só registros reprovados podem ser corrigidos por aqui.")
    return registro


def _faixa_dureza(db: Session, tipo: str) -> tuple[float | None, float | None]:
    spec = db.get(EspecificacaoTipo, tipo)
    if spec is None or spec.dureza_min is None or spec.dureza_max is None:
        return None, None
    return float(spec.dureza_min), float(spec.dureza_max)


def _nc_do_registro(db: Session, registro_id: int) -> NaoConformidade | None:
    return db.scalar(
        select(NaoConformidade)
        .where(NaoConformidade.registro_id == registro_id, NaoConformidade.status.in_(fluxo.NC_EM_ABERTO))
        .order_by(NaoConformidade.id.desc())
    )


@rota.get("/registros/{registro_id}/corrigir-dureza")
def ver_correcao_dureza(registro_id: int, _: Contexto = Depends(APROVADOR), db: Session = Depends(get_db)) -> dict:
    registro = _registro_dureza(db, registro_id)
    lote = buscar_lote(db, registro.lote_id)
    esp_min, esp_max = _faixa_dureza(db, lote.tipo)
    nc = _nc_do_registro(db, registro.id)
    return {
        "lote": _lote_resumo(lote),
        "registro": {"id": registro.id, "status": registro.status, "quando": registro.quando, "responsavel": registro.responsavel},
        "leituras": extrair_leituras(registro.dados),
        "esp_min": esp_min,
        "esp_max": esp_max,
        "nc": {"id": nc.id, "numero": nc.numero, "status": nc.status} if nc else None,
    }


class LeituraCorrigida(BaseModel):
    cp: str = Field("", max_length=60)
    valores: list[str | float | None] = Field(default_factory=list, max_length=10)


class CorrecaoDureza(BaseModel):
    leituras: list[LeituraCorrigida] = Field(max_length=100)
    nc_id: int | None = None


def _atualizar_relatorio_antigo(dados: dict, leituras: list[dict], esp_min: float, esp_max: float, resultado: str) -> None:
    """Registro antigo (formulário livre): reescreve a tabela "Leituras" e o resumo do relatório guardado,
    para a tela da etapa mostrar os valores corrigidos."""
    relatorio = dados.get("report")
    if not isinstance(relatorio, dict):
        return
    for tabela in relatorio.get("tabelas") or []:
        if isinstance(tabela, dict) and "leitura" in str(tabela.get("titulo") or "").lower():
            tabela["linhas"] = [
                [item["cp"] or "CP", formatar(v), "OK" if esp_min <= v <= esp_max else "FORA"]
                for item in leituras
                for v in item["valores"]
            ]
            tabela["cab"] = ["Peça / ponto", "HRC", "Resultado"]
    todos = [v for item in leituras for v in item["valores"]]
    if not todos:
        return
    resumo = [list(item) for item in relatorio.get("kv") or [] if item]

    def definir(chave: str, valor: str) -> None:
        for item in resumo:
            if item[0] == chave:
                item[1:] = [valor]
                return
        resumo.append([chave, valor])

    definir("Leituras", str(len(todos)))
    definir("Mínimo / Máximo", f"{min(todos):g} / {max(todos):g} HRC")
    definir("Média", f"{sum(todos) / len(todos):.1f} HRC")
    definir("Resultado", resultado)
    relatorio["kv"] = resumo


@rota.post("/registros/{registro_id}/corrigir-dureza")
def corrigir_dureza(registro_id: int, corpo: CorrecaoDureza, ctx: Contexto = Depends(APROVADOR), db: Session = Depends(get_db)) -> dict:
    registro = _registro_dureza(db, registro_id, travar=True)
    lote = buscar_lote(db, registro.lote_id)
    esp_min, esp_max = _faixa_dureza(db, lote.tipo)
    if esp_min is None or esp_max is None:
        raise HTTPException(422, f"A especificação de dureza do tipo {lote.tipo} não está cadastrada: não dá para recalcular "
                                 "o resultado. Cadastre em Especificações antes de corrigir.")  # fmt: skip
    atuais = extrair_leituras(registro.dados)
    if len(corpo.leituras) != len(atuais):
        raise HTTPException(409, "As leituras deste registro mudaram desde que a tela foi aberta. Recarregue a página.")

    novas: list[dict] = []
    for indice, (enviada, atual) in enumerate(zip(corpo.leituras, atuais, strict=True), start=1):
        valores = []
        for bruto in enviada.valores:
            if bruto is None or (isinstance(bruto, str) and not bruto.strip()):
                continue
            valor = numero(bruto)
            if valor is None:
                raise HTTPException(422, "Valores de dureza inválidos — use números (ex.: 36,0).")
            valores.append(valor)
        if not valores:
            continue  # CP sem nenhuma leitura sai da lista (como no sistema antigo)
        cp = _texto(enviada.cp) or atual["cp"] or f"OP{lote.op}-DUR{indice}"
        novas.append({"cp": cp, "valores": valores, "status": status_dureza(valores, esp_min, esp_max)})
    if not novas:
        raise HTTPException(422, "Informe pelo menos uma leitura.")

    resultado = status_dureza([v for item in novas for v in item["valores"]], esp_min, esp_max)
    status_novo = "aprovado" if resultado == "APROVADO" else "reprovado"
    agora = agora_local()
    dados = copy.deepcopy(registro.dados) if isinstance(registro.dados, dict) else {}
    dados["leituras"] = novas
    dados["corrigido_em"] = agora.isoformat(sep=" ")
    dados["corrigido_por"] = ctx.usuario.nome
    _atualizar_relatorio_antigo(dados, novas, esp_min, esp_max, resultado)
    status_antes = registro.status
    registro.status = status_novo
    registro.dados = dados
    auditar(db, ctx, "CORRIGIR", "registro", registro.id,
            {"motivo": "Correção de valores digitados (via NC)", "antes": {"status": status_antes, "leituras": atuais},
             "depois": {"status": status_novo, "leituras": novas}},
            lote_id=lote.id)  # fmt: skip

    encerrada = None
    if status_novo == "aprovado":
        nc = _nc_do_registro(db, registro.id)
        if nc is not None:
            antes_nc = nc.status
            nc.status = "encerrada"
            nc.disposicao = "anulada"
            nc.justificativa = "Erro de digitação — valores corrigidos e status ficou APROVADO."
            nc.observacoes = (f"Valores corrigidos — novo status: APROVADO. Antes: {texto_leituras(atuais)}. "
                              f"Depois: {texto_leituras(novas)}.")  # fmt: skip
            nc.decidida_em = nc.encerrada_em = agora
            nc.decidida_por = nc.encerrada_por = ctx.usuario.nome
            registrar_evento(db, lote.id, f"NC {nc.numero} encerrada automaticamente — valores de dureza corrigidos por "
                                          f"{ctx.usuario.nome}, novo status APROVADO.")  # fmt: skip
            auditar(db, ctx, "ENCERRAR", "nc", nc.id, {"numero": nc.numero, "status": [antes_nc, "encerrada"],
                                                       "disposicao": "anulada", "via": "correção de valores"},
                    lote_id=lote.id)  # fmt: skip
            encerrada = {"id": nc.id, "numero": nc.numero}
        registrar_evento(db, lote.id, f"Dureza: valores do registro #{registro.id} corrigidos — novo status APROVADO.")
        mensagem = "Valores corrigidos — novo status APROVADO." + (" NC encerrada automaticamente." if encerrada else "")
    else:
        faixa = f"{formatar(esp_min).replace('.', ',')}–{formatar(esp_max).replace('.', ',')} HRc"
        registrar_evento(db, lote.id, f"Dureza: valores do registro #{registro.id} corrigidos, mas continuam fora da "
                                      f"especificação ({faixa}). NC permanece aberta.")  # fmt: skip
        mensagem = ("Valores atualizados, mas ainda ficaram fora da especificação. A NC segue aberta — decida a disposição "
                    "(retrabalho, sucata, uso como está ou anular).")  # fmt: skip
    db.commit()
    return {"mensagem": mensagem, "status": status_novo, "lote_id": lote.id, "nc_encerrada": encerrada,
            "nc_id": corpo.nc_id, "leituras": novas}  # fmt: skip

