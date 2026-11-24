"""Envios a prestador externo (laboratório, revestimento, NDT).

Trazido do sistema antigo (legado/app.py, "ENVIOS A PRESTADOR"; telas envios_prestador_* de templates_html.py).
Registra o momento em que o lote (ou corpos de prova dele) SAI da fábrica para um laboratório/revestidor — ou,
no NDT, quando o inspetor VEM até a fábrica. O retorno (laudo/certificado) é lançado depois na etapa do lote
(lab_ext, lp, fosfato); o envio só aponta quando isso já aconteceu, e o fechamento ("retornado") é manual.

Diferenças em relação ao antigo:
- número EP-AAAA-NNN reservado sem duplicidade (numeracao.py), e não "maior + 1";
- "Excluir" virou cancelar com motivo (nada é apagado); foto removida fica marcada, com motivo;
- quem registra é o usuário logado ("responsável pelo envio" continua como informação extra);
- o modelo .docx do laboratório não depende mais do nome do prestador no código: parâmetros
  `modelo_ensaio_prestador` (trecho do nome) e `modelo_ensaio_arquivo` (arquivo em recursos/modelos/).
"""
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import fluxo, parametros
from app.arquivos import IMAGENS, resposta_arquivo, salvar_upload
from app.config import agora_local
from app.db import get_db
from app.estado import ultimos_registros
from app.expedicao import (
    cadastro_ops,
    cliente_curto,
    decimal,
    descricao_curta,
    etapas_atuais,
    ler_peso,
    material,
    material_especificacao,
    numero_br,
    numero_previsto,
)
from app.historico import registrar_evento
from app.modelo_ensaio import arquivo_modelo, modelo_disponivel, preencher_modelo, prestador_usa_modelo
from app.models import (
    TIPOS_LOTE,
    EnvioPrestador,
    EnvioPrestadorFoto,
    EnvioPrestadorLote,
    EspecificacaoTipo,
    Lote,
    Prestador,
)
from app.numeracao import proximo_numero
from app.pdf_expedicao import pdf_envio
from app.seguranca import Contexto, auditar, diferencas, exigir, limpar_texto

rota = APIRouter()
EXPEDICAO = exigir("qualidade", "producao_tt", "producao_usinagem")

TIPOS_ENVIO = (
    "Ensaio de tração",
    "Ensaio Charpy",
    "Ensaio de tração + Charpy",
    "NDT - líquido penetrante",
    "Revestimento fosfato",
    "Revestimento oxidação negra",
    "Outro",
)
ENSAIOS = frozenset({"Ensaio de tração", "Ensaio Charpy", "Ensaio de tração + Charpy"})
COM_TRACAO = frozenset({"Ensaio de tração", "Ensaio de tração + Charpy"})
COM_CHARPY = frozenset({"Ensaio Charpy", "Ensaio de tração + Charpy"})
# Etapa do lote em que o retorno do prestador é lançado (para saber se o laudo já chegou)
ETAPA_POR_TIPO = {
    "Ensaio de tração": "lab_ext",
    "Ensaio Charpy": "lab_ext",
    "Ensaio de tração + Charpy": "lab_ext",
    "NDT - líquido penetrante": "lp",
    "Revestimento fosfato": "fosfato",
    "Revestimento oxidação negra": "fosfato",
}
# Dentro do laboratório externo, só os ensaios que foram pedidos contam para o "laudo lançado"
SUBS_DO_ENSAIO = {
    "Ensaio de tração": ("tracao",),
    "Ensaio Charpy": ("charpy",),
    "Ensaio de tração + Charpy": ("tracao", "charpy"),
}
# Tipo de serviço do cadastro de prestadores que atende cada tipo de envio (None = todos)
PRESTADORES_POR_TIPO: dict[str, tuple[str, ...] | None] = {
    "Ensaio de tração": ("Lab mecânico (tração/Charpy)",),
    "Ensaio Charpy": ("Lab mecânico (tração/Charpy)",),
    "Ensaio de tração + Charpy": ("Lab mecânico (tração/Charpy)",),
    "NDT - líquido penetrante": ("NDT - líquido penetrante",),
    "Revestimento fosfato": ("Revestimento fosfato",),
    "Revestimento oxidação negra": ("Revestimento oxidação negra",),
    "Outro": None,
}
ABAS = {"ativos": "enviado", "retornados": "retornado", "cancelados": "cancelado"}
TRANSICOES = {"enviado": {"retornado", "cancelado"}, "retornado": {"enviado"}, "cancelado": set()}
NOME_STATUS = {"enviado": "enviado", "retornado": "retornado", "cancelado": "cancelado"}
DIAS_ALERTA = 10  # envio "enviado" há esse tanto de dias sem retorno vira alerta (lista e painel)
PASTA_FOTOS = "envios_prestador/{id}/fotos"

# Especificação mostrada no envio: (rótulo, coluna mínima, coluna máxima, unidade)
CAMPOS_TRACAO = (
    ("Limite de escoamento (LE)", "tr_le_min", "tr_le_max", "MPa"),
    ("Limite de resistência (LR)", "tr_lr_min", "tr_lr_max", "MPa"),
    ("Alongamento mín.", "tr_al_min", None, "%"),
    ("Redução de área mín.", "tr_ra_min", None, "%"),
)
CAMPOS_CHARPY = (
    ("Temperatura do ensaio", "ch_temp", None, ""),
    ("Charpy — média mín.", "ch_med_min", None, "J"),
    ("Charpy — individual mín.", "ch_ind_min", None, "J"),
    ("Dimensão do CP", "ch_dim_cp", None, "mm"),
)
TEXTO_LIVRE = frozenset({"ch_temp", "ch_dim_cp"})


# ---------------------------------------------------------------- regras (funções puras)


def natureza(tipo_servico: str) -> dict[str, str]:
    """O que sai da fábrica: cp (azul) = só corpos de prova; interno (verde) = o laboratório vem até a fábrica;
    pecas (laranja) = as peças saem fisicamente; outro (cinza)."""
    if tipo_servico in ENSAIOS:
        return {"classe": "cp", "texto": "Envio de corpos de prova (CPs) para ensaio mecânico — as peças do lote permanecem na fábrica."}
    if tipo_servico in ("Revestimento fosfato", "Revestimento oxidação negra"):
        return {"classe": "pecas", "texto": "Envio das peças do lote para revestimento — as peças saem fisicamente da fábrica."}
    if tipo_servico == "NDT - líquido penetrante":
        return {
            "classe": "interno",
            "texto": "Laboratório externo com execução na AçoKorte — as peças permanecem na fábrica; "
            "o inspetor vem aqui realizar o ensaio.",
        }
    return {"classe": "outro", "texto": "Envio externo — descreva nas observações o que está indo."}


def rotulo_fotos(tipo_servico: str) -> str:
    return "Fotos dos corpos de prova" if tipo_servico in ENSAIOS else "Fotos das peças"


def modo_pecas(tipo_servico: str) -> bool:
    """Revestimento, NDT e outro: a tabela por OP tem qtd liberada, volumes e pesos (em vez de CPs)."""
    return tipo_servico not in ENSAIOS


def tipo_compativel(tipo_servico: str, tipo_lote: str) -> bool:
    """Fosfato é de PIN/BOX; oxidação negra é de ARK. Os outros serviços aceitam qualquer lote."""
    if tipo_servico == "Revestimento fosfato":
        return tipo_lote != "ARK"
    if tipo_servico == "Revestimento oxidação negra":
        return tipo_lote == "ARK"
    return True


def _valor_especificacao(espec: EspecificacaoTipo, coluna_min: str, coluna_max: str | None, unidade: str) -> str:
    if coluna_min in TEXTO_LIVRE:
        return (getattr(espec, coluna_min) or "").strip()
    minimo = numero_br(getattr(espec, coluna_min))
    maximo = numero_br(getattr(espec, coluna_max)) if coluna_max else ""
    if minimo and maximo:
        return f"{minimo}–{maximo} {unidade}".strip()
    if maximo:
        return f"≤ {maximo} {unidade}".strip()
    if minimo:
        return f"≥ {minimo} {unidade}".strip()
    return ""


def especificacao_para_envio(db: Session, tipo_servico: str, tipos_pecas) -> list[dict]:
    """Linhas da especificação cadastrada que valem para o envio, por tipo de peça (SC 4330 x H11 Modified).

    Só ensaios mecânicos têm especificação numérica aqui. Nada é inventado: o que não está cadastrado não aparece
    (e o tipo sem nada cadastrado sai como "vazio").
    """
    tipos = [t for t in sorted(set(tipos_pecas)) if t in TIPOS_LOTE]
    grupos = []
    if tipo_servico in COM_TRACAO:
        grupos.append(("tracao", CAMPOS_TRACAO))
    if tipo_servico in COM_CHARPY:
        grupos.append(("charpy", CAMPOS_CHARPY))
    if not grupos or not tipos:
        return []
    saida = []
    for tipo in tipos:
        espec = db.get(EspecificacaoTipo, tipo)
        linhas: dict[str, list[list[str]]] = {"tracao": [], "charpy": []}
        if espec is not None:
            for grupo, campos in grupos:
                for rotulo, coluna_min, coluna_max, unidade in campos:
                    valor = _valor_especificacao(espec, coluna_min, coluna_max, unidade)
                    if valor:
                        linhas[grupo].append([rotulo, valor])
        saida.append({
            "tipo": tipo, "material": material_especificacao(tipo), "tracao": linhas["tracao"], "charpy": linhas["charpy"],
            "vazio": not (linhas["tracao"] or linhas["charpy"]),
        })  # fmt: skip
    return saida


def dias_desde(dia: date | None, hoje: date | None = None) -> int:
    if dia is None:
        return 0
    return max(((hoje or agora_local().date()) - dia).days, 0)


# ---------------------------------------------------------------- leitura


def _buscar_envio(db: Session, envio_id: int) -> EnvioPrestador:
    envio = db.get(EnvioPrestador, envio_id)
    if not envio:
        raise HTTPException(404, "Envio não encontrado.")
    return envio


def _itens_dos_envios(db: Session, envio_ids: list[int]) -> dict[int, list[tuple[EnvioPrestadorLote, Lote]]]:
    saida: dict[int, list[tuple[EnvioPrestadorLote, Lote]]] = {i: [] for i in envio_ids}
    if not envio_ids:
        return saida
    consulta = (
        select(EnvioPrestadorLote, Lote)
        .join(Lote, Lote.id == EnvioPrestadorLote.lote_id)
        .where(EnvioPrestadorLote.envio_id.in_(envio_ids))
        .order_by(EnvioPrestadorLote.ordem, EnvioPrestadorLote.id)
    )
    for item, lote in db.execute(consulta):
        saida[item.envio_id].append((item, lote))
    return saida


def retornos(db: Session, envio: EnvioPrestador, lotes: list[Lote]) -> dict[int, bool]:
    """Para cada lote: o laudo/retorno já foi lançado na etapa correspondente (registro aprovado ou reprovado,
    não anulado, de data igual ou posterior ao envio)? Só lê; o fechamento do envio continua manual."""
    chave = ETAPA_POR_TIPO.get(envio.tipo_servico)
    if not chave or not envio.data_envio or not lotes:
        return {lote.id: False for lote in lotes}
    etapa = fluxo.POR_CHAVE[chave]
    ultimos = ultimos_registros(db, [lote.id for lote in lotes])
    saida = {}
    for lote in lotes:
        subs = [s for s in etapa.subs_de(lote.tipo) if s in SUBS_DO_ENSAIO.get(envio.tipo_servico, (s,))]
        if not etapa.aplicavel(lote.tipo) or not subs:
            saida[lote.id] = False
            continue
        registros = [ultimos.get((lote.id, chave, s)) for s in subs]
        saida[lote.id] = all(
            r is not None and r.status in ("aprovado", "reprovado") and r.quando is not None and r.quando.date() >= envio.data_envio
            for r in registros
        )
    return saida


def _resumo(envio: EnvioPrestador, itens: list[tuple[EnvioPrestadorLote, Lote]], hoje: date) -> dict:
    dias = dias_desde(envio.data_envio, hoje)
    return {
        "id": envio.id,
        "numero": envio.numero,
        "prestador": envio.prestador,
        "tipo_servico": envio.tipo_servico,
        "status": envio.status,
        "data_emissao": envio.data_emissao,
        "data_envio": envio.data_envio,
        "data_retorno": envio.data_retorno,
        "responsavel": envio.responsavel,
        "dias_envio": dias,
        "parado": envio.status == "enviado" and dias >= DIAS_ALERTA,
        "n_lotes": len(itens),
        "total_pecas": sum(lote.qtd or 0 for _, lote in itens),
        "lotes": [{"id": lote.id, "op": lote.op, "tipo": lote.tipo, "numero": lote.numero, "qtd": lote.qtd} for _, lote in itens],
    }


def dados_envio(db: Session, envio: EnvioPrestador) -> dict:
    """Tudo o que o detalhe, o PDF e o modelo .docx precisam saber do envio."""
    itens = _itens_dos_envios(db, [envio.id])[envio.id]
    lotes = [lote for _, lote in itens]
    cad = cadastro_ops(db, [lote.op for lote in lotes])
    etapas = etapas_atuais(db, lotes)
    retornou = retornos(db, envio, lotes)
    padrao_cliente = parametros.ler(db, "cliente_nome_curto")
    linhas = []
    for item, lote in itens:
        op = cad.get((lote.op or "").strip())
        linhas.append({
            "lote_id": lote.id, "op": lote.op, "tipo": lote.tipo, "numero": lote.numero, "qtd": lote.qtd or 0,
            "coditem": lote.coditem or (op.coditem if op else ""),
            "cliente": cliente_curto(db, op.cliente if op else "", padrao_cliente),
            "descricao": descricao_curta(op.descricao if op else ""), "material": material(lote.tipo),
            "etapa_atual": etapas.get(lote.id, (0, ""))[1], "cancelado": lote.cancelado_em is not None,
            "qt_cp_tracao": item.qt_cp_tracao or 0, "qt_cp_impacto": item.qt_cp_impacto or 0,
            "qt_liberar": item.qt_liberar or 0, "volumes": item.volumes or 0,
            "peso_liq": float(item.peso_liq or 0), "peso_bruto": float(item.peso_bruto or 0),
            "retornou": retornou.get(lote.id, False),
        })  # fmt: skip
    fotos = db.scalars(
        select(EnvioPrestadorFoto)
        .where(EnvioPrestadorFoto.envio_id == envio.id, EnvioPrestadorFoto.removido_em.is_(None))
        .order_by(EnvioPrestadorFoto.id)
    ).all()
    chave_etapa = ETAPA_POR_TIPO.get(envio.tipo_servico)
    pecas = modo_pecas(envio.tipo_servico)
    dados = _resumo(envio, itens, agora_local().date())
    dados.update({
        "observacoes": envio.observacoes, "qtd_cps": envio.qtd_cps,
        "qtd_cp_tracao": envio.qtd_cp_tracao or 0, "qtd_cp_impacto": envio.qtd_cp_impacto or 0,
        "criado_em": envio.criado_em, "criado_por": envio.criado_por,
        "cancelado_em": envio.cancelado_em, "cancelado_por": envio.cancelado_por, "cancelado_motivo": envio.cancelado_motivo,
        "natureza": natureza(envio.tipo_servico), "rotulo_fotos": rotulo_fotos(envio.tipo_servico), "modo_pecas": pecas,
        "mostrar_tracao": envio.tipo_servico in COM_TRACAO, "mostrar_charpy": envio.tipo_servico in COM_CHARPY,
        "itens": linhas,
        "totais": {
            "qt_cp_tracao": sum(x["qt_cp_tracao"] for x in linhas),
            "qt_cp_impacto": sum(x["qt_cp_impacto"] for x in linhas),
            # qtd liberada não informada = o lote inteiro (igual ao sistema antigo)
            "qt_liberar": sum(x["qt_liberar"] or x["qtd"] for x in linhas),
            "volumes": sum(x["volumes"] for x in linhas),
            "peso_liq": round(sum(x["peso_liq"] for x in linhas), 3),
            "peso_bruto": round(sum(x["peso_bruto"] for x in linhas), 3),
        },
        "todos_retornaram": bool(linhas) and all(x["retornou"] for x in linhas),
        "etapa_referencia": fluxo.POR_CHAVE[chave_etapa].nome if chave_etapa else "",
        "especificacao": envio.spec_snapshot or [],
        "norma_codigo": parametros.ler(db, "especificacao_codigo"),
        "fotos": [{"id": f.id, "nome": f.nome, "quando": f.quando, "legenda": f.legenda} for f in fotos],
        "modelo_ensaio": modelo_disponivel(db, envio.prestador),
        "pode_editar": envio.status != "cancelado",
    })  # fmt: skip
    return dados


def envios_sem_retorno(db: Session, dias: int = DIAS_ALERTA) -> list[dict]:
    """Envios ainda "enviado" há `dias` dias ou mais sem retorno (alerta do painel), do mais antigo ao mais novo."""
    hoje = agora_local().date()
    envios = db.scalars(
        select(EnvioPrestador)
        .where(EnvioPrestador.status == "enviado", EnvioPrestador.data_envio.is_not(None))
        .order_by(EnvioPrestador.data_envio, EnvioPrestador.id)
    )
    return [
        {"id": e.id, "numero": e.numero, "prestador": e.prestador, "tipo_servico": e.tipo_servico,
         "data_envio": e.data_envio, "dias": dias_desde(e.data_envio, hoje)}
        for e in envios if dias_desde(e.data_envio, hoje) >= dias
    ]  # fmt: skip


# ---------------------------------------------------------------- rotas de consulta


@rota.get("/envios/opcoes")
def opcoes(db: Session = Depends(get_db), ctx: Contexto = Depends(EXPEDICAO)) -> dict:
    """Listas do formulário: tipos de serviço (com a natureza de cada um), prestadores e padrões."""
    prestadores = db.scalars(select(Prestador).where(Prestador.ativo.is_(True)).order_by(Prestador.razao_social))
    return {
        "tipos": [
            {"valor": t, "modo_pecas": modo_pecas(t), "natureza": natureza(t), "rotulo_fotos": rotulo_fotos(t),
             "tipos_prestador": PRESTADORES_POR_TIPO.get(t), "mostrar_tracao": t in COM_TRACAO, "mostrar_charpy": t in COM_CHARPY}
            for t in TIPOS_ENVIO
        ],
        "prestadores": [{"razao_social": p.razao_social, "codigo": p.codigo, "tipo_servico": p.tipo_servico} for p in prestadores],
        # Trecho do nome do laboratório que usa o modelo .docx: ele já vem escolhido nos ensaios de tração
        "prestador_preferido": parametros.ler(db, "modelo_ensaio_prestador", ""),
        "norma_codigo": parametros.ler(db, "especificacao_codigo"),
        "cliente_curto": parametros.ler(db, "cliente_nome_curto"),
        "numero_previsto": numero_previsto(db, "EP"),
        "hoje": agora_local().date(),
        "usuario": ctx.usuario.nome,
    }  # fmt: skip


@rota.get("/envios")
def listar(aba: str = Query("ativos"), db: Session = Depends(get_db), _: Contexto = Depends(EXPEDICAO)) -> dict:
    status = ABAS.get(aba, "enviado")
    envios = db.scalars(select(EnvioPrestador).where(EnvioPrestador.status == status).order_by(EnvioPrestador.id.desc())).all()
    itens = _itens_dos_envios(db, [e.id for e in envios])
    contagem = dict(db.execute(select(EnvioPrestador.status, func.count()).group_by(EnvioPrestador.status)).all())
    hoje = agora_local().date()
    return {
        "itens": [_resumo(e, itens[e.id], hoje) for e in envios],
        "contagens": {nome: contagem.get(s, 0) for nome, s in ABAS.items()},
        "dias_alerta": DIAS_ALERTA,
    }


@rota.get("/envios/lotes-disponiveis")
def lotes_disponiveis(
    tipo_servico: str = Query(""),
    envio_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _: Contexto = Depends(EXPEDICAO),
) -> dict:
    """Lista LIVRE: todo lote ativo e não concluído, em qualquer etapa (o corpo de prova sai a qualquer momento).
    Só o revestimento esconde o tipo incompatível. Na edição, os lotes que já estão no envio vêm sempre."""
    if tipo_servico and tipo_servico not in TIPOS_ENVIO:
        raise HTTPException(422, "Tipo de serviço inválido.")
    no_envio: set[int] = set()
    if envio_id:
        no_envio = set(db.scalars(select(EnvioPrestadorLote.lote_id).where(EnvioPrestadorLote.envio_id == envio_id)))
    lotes = db.scalars(select(Lote).where((Lote.cancelado_em.is_(None)) | (Lote.id.in_(no_envio))).order_by(Lote.op, Lote.id)).all()
    etapas = etapas_atuais(db, lotes)
    cad = cadastro_ops(db, [lote.op for lote in lotes])
    padrao_cliente = parametros.ler(db, "cliente_nome_curto")
    saida = []
    for lote in lotes:
        indice, rotulo = etapas[lote.id]
        if lote.id not in no_envio and (indice >= fluxo.CONCLUIDO or not tipo_compativel(tipo_servico, lote.tipo)):
            continue
        op = cad.get((lote.op or "").strip())
        saida.append({
            "id": lote.id, "op": lote.op, "tipo": lote.tipo, "numero": lote.numero, "qtd": lote.qtd or 0,
            "corrida": lote.corrida, "coditem": lote.coditem or (op.coditem if op else ""),
            "cliente": cliente_curto(db, op.cliente if op else "", padrao_cliente), "etapa_atual": rotulo,
        })  # fmt: skip
    return {"lotes": saida, "natureza": natureza(tipo_servico) if tipo_servico else None}


@rota.get("/envios/especificacao")
def previa_especificacao(
    tipo_servico: str = Query(""),
    lote_ids: str = Query(""),
    db: Session = Depends(get_db),
    _: Contexto = Depends(EXPEDICAO),
) -> dict:
    """Especificação aplicável ao envio em montagem, ao vivo, conforme os lotes marcados."""
    ids = [int(x) for x in lote_ids.split(",") if x.strip().isdigit()]
    tipos = sorted(set(db.scalars(select(Lote.tipo).where(Lote.id.in_(ids))))) if ids else []
    return {
        "tipos_pecas": tipos,
        "especificacao": especificacao_para_envio(db, tipo_servico, tipos),
        "norma_codigo": parametros.ler(db, "especificacao_codigo"),
    }


@rota.get("/envios/{envio_id}")
def detalhe(envio_id: int, db: Session = Depends(get_db), _: Contexto = Depends(EXPEDICAO)) -> dict:
    return dados_envio(db, _buscar_envio(db, envio_id))


# ---------------------------------------------------------------- gravação


class ItemEnvio(BaseModel):
    lote_id: int
    qt_cp_tracao: int = 0
    qt_cp_impacto: int = 0
    qt_liberar: int = 0
    volumes: int = 0
    peso_liq: float | str | None = None
    peso_bruto: float | str | None = None


class EnvioEntrada(BaseModel):
    tipo_servico: str
    prestador: str
    data_emissao: date | None = None
    data_envio: date | None = None
    responsavel: str = ""
    observacoes: str = ""
    itens: list[ItemEnvio] = []


LIMITE_QTD = 1_000_000  # quantidade absurda é erro de digitação (e não cabe na coluna)


def _validar(db: Session, corpo: EnvioEntrada, ja_no_envio: set[int]) -> tuple[dict, list[tuple[ItemEnvio, Lote]]]:
    tipo = (corpo.tipo_servico or "").strip()
    if tipo not in TIPOS_ENVIO:
        raise HTTPException(422, "Escolha um tipo de serviço da lista.")
    prestador = limpar_texto(corpo.prestador or "").strip()
    if not prestador:
        raise HTTPException(422, "Selecione o prestador.")
    if not corpo.data_envio:
        raise HTTPException(422, "Informe a data de envio.")
    vistos: set[int] = set()
    itens: list[tuple[ItemEnvio, Lote]] = []
    for item in corpo.itens:
        if item.lote_id in vistos:
            continue
        vistos.add(item.lote_id)
        lote = db.get(Lote, item.lote_id)
        if lote is None:
            raise HTTPException(422, f"O lote #{item.lote_id} não existe.")
        novo = lote.id not in ja_no_envio
        if novo and lote.cancelado_em is not None:
            raise HTTPException(422, f"O lote {lote.numero} foi cancelado e não pode entrar no envio.")
        if novo and not tipo_compativel(tipo, lote.tipo):
            raise HTTPException(422, f"O lote {lote.numero} ({lote.tipo}) não passa por {tipo.lower()}.")
        quantidades = (item.qt_cp_tracao, item.qt_cp_impacto, item.qt_liberar, item.volumes)
        if min(quantidades) < 0:
            raise HTTPException(422, f"As quantidades do lote {lote.numero} não podem ser negativas.")
        if max(quantidades) > LIMITE_QTD:
            raise HTTPException(422, f"Quantidade grande demais no lote {lote.numero}.")
        item.peso_liq = str(ler_peso(item.peso_liq, lote.numero))
        item.peso_bruto = str(ler_peso(item.peso_bruto, lote.numero))
        itens.append((item, lote))
    if not itens:
        raise HTTPException(422, "Selecione ao menos um lote.")
    campos = {
        "tipo_servico": tipo,
        "prestador": prestador[:160],
        "data_emissao": corpo.data_emissao or agora_local().date(),
        "data_envio": corpo.data_envio,
        "responsavel": limpar_texto(corpo.responsavel or "").strip()[:120],
        "observacoes": limpar_texto(corpo.observacoes or "").strip(),
    }
    return campos, itens


def _gravar_item(vinculo: EnvioPrestadorLote, item: ItemEnvio) -> None:
    vinculo.qt_cp_tracao = item.qt_cp_tracao
    vinculo.qt_cp_impacto = item.qt_cp_impacto
    vinculo.qt_liberar = item.qt_liberar
    vinculo.volumes = item.volumes
    vinculo.peso_liq = decimal(item.peso_liq)
    vinculo.peso_bruto = decimal(item.peso_bruto)


def _quantidades(vinculo: EnvioPrestadorLote) -> dict:
    return {
        "qt_cp_tracao": vinculo.qt_cp_tracao or 0, "qt_cp_impacto": vinculo.qt_cp_impacto or 0,
        "qt_liberar": vinculo.qt_liberar or 0, "volumes": vinculo.volumes or 0,
        "peso_liq": str(decimal(vinculo.peso_liq)), "peso_bruto": str(decimal(vinculo.peso_bruto)),
    }  # fmt: skip


@rota.post("/envios", status_code=201)
def criar(corpo: EnvioEntrada, db: Session = Depends(get_db), ctx: Contexto = Depends(EXPEDICAO)) -> dict:
    campos, itens = _validar(db, corpo, set())
    agora = agora_local()
    envio = EnvioPrestador(
        numero=proximo_numero(db, "EP"),
        status="enviado",
        spec_snapshot=especificacao_para_envio(db, campos["tipo_servico"], [lote.tipo for _, lote in itens]),
        qtd_cp_tracao=sum(i.qt_cp_tracao for i, _ in itens),
        qtd_cp_impacto=sum(i.qt_cp_impacto for i, _ in itens),
        criado_em=agora,
        criado_por=ctx.usuario.nome,
        **{**campos, "responsavel": campos["responsavel"] or ctx.usuario.nome},
    )
    db.add(envio)
    db.flush()
    for ordem, (item, lote) in enumerate(itens, start=1):
        vinculo = EnvioPrestadorLote(envio_id=envio.id, lote_id=lote.id, ordem=ordem)
        _gravar_item(vinculo, item)
        db.add(vinculo)
        registrar_evento(
            db, lote.id, f"Lote enviado ao prestador externo ({envio.prestador}) — {envio.tipo_servico} — envio {envio.numero}"
        )
    auditar(db, ctx, "CRIAR", "envio_prestador", envio.id,
            {"numero": envio.numero, "prestador": envio.prestador, "tipo": envio.tipo_servico, "data_envio": envio.data_envio,
             "lotes": [lote.numero for _, lote in itens]},
            lote_id=itens[0][1].id if len(itens) == 1 else None)  # fmt: skip
    db.commit()
    return {"id": envio.id, "numero": envio.numero}


@rota.put("/envios/{envio_id}")
def editar(envio_id: int, corpo: EnvioEntrada, db: Session = Depends(get_db), ctx: Contexto = Depends(EXPEDICAO)) -> dict:
    envio = _buscar_envio(db, envio_id)
    if envio.status == "cancelado":
        raise HTTPException(409, "Este envio foi cancelado e não pode mais ser alterado.")
    atuais = {v.lote_id: v for v in db.scalars(select(EnvioPrestadorLote).where(EnvioPrestadorLote.envio_id == envio.id))}
    campos, itens = _validar(db, corpo, set(atuais))
    lotes_antes = {lid: db.get(Lote, lid) for lid in atuais}
    antes = {k: getattr(envio, k) for k in campos} | {"qtd_cp_tracao": envio.qtd_cp_tracao, "qtd_cp_impacto": envio.qtd_cp_impacto}
    quantidades_antes = {lid: _quantidades(v) for lid, v in atuais.items()}
    tipos_antes = sorted({lote.tipo for lote in lotes_antes.values() if lote})
    tipo_antes = envio.tipo_servico

    for chave, valor in campos.items():
        setattr(envio, chave, valor)
    envio.qtd_cp_tracao = sum(i.qt_cp_tracao for i, _ in itens)
    envio.qtd_cp_impacto = sum(i.qt_cp_impacto for i, _ in itens)
    # A especificação fica congelada; só é refeita se o serviço ou os tipos de peça mudaram
    tipos_depois = sorted({lote.tipo for _, lote in itens})
    if tipo_antes != envio.tipo_servico or tipos_antes != tipos_depois:
        envio.spec_snapshot = especificacao_para_envio(db, envio.tipo_servico, tipos_depois)

    novos_ids = [lote.id for _, lote in itens]
    for lid in set(atuais) - set(novos_ids):
        db.delete(atuais[lid])  # o vínculo some do envio; a auditoria guarda o antes e o depois
        if lotes_antes.get(lid):
            registrar_evento(db, lid, f"Lote retirado do envio {envio.numero} ({envio.prestador})")
    proxima_ordem = max((v.ordem or 0 for v in atuais.values()), default=0)
    quantidades_depois = {}
    for item, lote in itens:
        vinculo = atuais.get(lote.id)
        if vinculo is None:
            proxima_ordem += 1
            vinculo = EnvioPrestadorLote(envio_id=envio.id, lote_id=lote.id, ordem=proxima_ordem)
            db.add(vinculo)
            registrar_evento(
                db, lote.id, f"Lote incluído no envio {envio.numero} ao prestador externo ({envio.prestador}) — {envio.tipo_servico}"
            )
        _gravar_item(vinculo, item)
        quantidades_depois[lote.id] = _quantidades(vinculo)

    depois = {k: getattr(envio, k) for k in campos} | {"qtd_cp_tracao": envio.qtd_cp_tracao, "qtd_cp_impacto": envio.qtd_cp_impacto}
    detalhes = diferencas(antes, depois)
    nomes_antes = sorted(lote.numero for lote in lotes_antes.values() if lote)
    nomes_depois = sorted(lote.numero for _, lote in itens)
    if nomes_antes != nomes_depois:
        detalhes["lotes"] = [nomes_antes, nomes_depois]
    numero_do_lote = {lote.id: lote.numero for _, lote in itens}
    mudou_qtd = {
        numero_do_lote[lid]: [quantidades_antes.get(lid), q]
        for lid, q in quantidades_depois.items() if quantidades_antes.get(lid) != q
    }  # fmt: skip
    if mudou_qtd:
        detalhes["quantidades"] = mudou_qtd
    if detalhes:
        auditar(db, ctx, "ALTERAR", "envio_prestador", envio.id, {"numero": envio.numero, **detalhes},
                lote_id=novos_ids[0] if len(novos_ids) == 1 else None)  # fmt: skip
    db.commit()
    return {"id": envio.id, "numero": envio.numero}


class MudancaStatus(BaseModel):
    status: str
    motivo: str = ""
    data_retorno: date | None = None


@rota.post("/envios/{envio_id}/status")
def mudar_status(envio_id: int, corpo: MudancaStatus, db: Session = Depends(get_db), ctx: Contexto = Depends(EXPEDICAO)) -> dict:
    """enviado → retornado | cancelado; retornado → enviado (reabrir). Cancelar exige motivo (nada é apagado)."""
    envio = _buscar_envio(db, envio_id)
    novo = (corpo.status or "").strip()
    if novo not in TRANSICOES:
        raise HTTPException(422, "Situação inválida.")
    if novo not in TRANSICOES[envio.status]:
        raise HTTPException(409, f"Um envio {NOME_STATUS[envio.status]} não pode passar para {NOME_STATUS[novo]}.")
    antes = {"status": envio.status, "data_retorno": envio.data_retorno}
    motivo = limpar_texto(corpo.motivo or "").strip()
    agora = agora_local()
    if novo == "retornado":
        retorno = corpo.data_retorno or agora.date()
        if envio.data_envio and retorno < envio.data_envio:
            raise HTTPException(422, "A data de retorno não pode ser antes da data de envio.")
        envio.data_retorno = retorno
        texto = f"Envio {envio.numero} ({envio.prestador}) marcado como retornado em {retorno:%d/%m/%Y}"
    elif novo == "enviado":
        envio.data_retorno = None
        texto = f"Envio {envio.numero} ({envio.prestador}) reaberto como enviado"
    else:
        if len(motivo) < 5:
            raise HTTPException(422, "Escreva o motivo do cancelamento (pelo menos 5 letras).")
        envio.cancelado_em, envio.cancelado_por, envio.cancelado_motivo = agora, ctx.usuario.nome, motivo
        texto = f"Envio {envio.numero} ({envio.prestador}) cancelado: {motivo}"
    envio.status = novo
    lote_ids = list(db.scalars(select(EnvioPrestadorLote.lote_id).where(EnvioPrestadorLote.envio_id == envio.id)))
    for lid in lote_ids:
        registrar_evento(db, lid, texto)
    detalhes = {"numero": envio.numero, **diferencas(antes, {"status": envio.status, "data_retorno": envio.data_retorno})}
    if motivo:
        detalhes["motivo"] = motivo
    auditar(db, ctx, "CANCELAR" if novo == "cancelado" else "STATUS", "envio_prestador", envio.id, detalhes,
            lote_id=lote_ids[0] if len(lote_ids) == 1 else None)  # fmt: skip
    db.commit()
    return {"id": envio.id, "status": envio.status}


# ---------------------------------------------------------------- fotos


@rota.post("/envios/{envio_id}/fotos", status_code=201)
def adicionar_fotos(
    envio_id: int,
    arquivos: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    ctx: Contexto = Depends(EXPEDICAO),
) -> dict:
    envio = _buscar_envio(db, envio_id)
    if envio.status == "cancelado":
        raise HTTPException(409, "Este envio foi cancelado: não recebe mais fotos.")
    arquivos = [a for a in arquivos if a and a.filename]
    if not arquivos:
        raise HTTPException(422, "Escolha uma ou mais fotos (JPG ou PNG).")
    agora = agora_local()
    nomes = []
    for arquivo in arquivos:
        relativo, nome = salvar_upload(arquivo, PASTA_FOTOS.format(id=envio.id), IMAGENS)
        db.add(EnvioPrestadorFoto(envio_id=envio.id, nome=nome[:255], arquivo=relativo, quando=agora))
        nomes.append(nome)
    auditar(db, ctx, "ANEXAR", "envio_prestador", envio.id, {"numero": envio.numero, "fotos": nomes})
    db.commit()
    return {"adicionadas": len(nomes)}


class Remocao(BaseModel):
    motivo: str = ""


@rota.post("/envios/fotos/{foto_id}/remover")
def remover_foto(foto_id: int, corpo: Remocao, db: Session = Depends(get_db), ctx: Contexto = Depends(EXPEDICAO)) -> dict:
    """A foto some do envio e do PDF, mas o arquivo e o registro ficam (nada é apagado)."""
    foto = db.get(EnvioPrestadorFoto, foto_id)
    if not foto or foto.removido_em:
        raise HTTPException(404, "Foto não encontrada.")
    motivo = limpar_texto(corpo.motivo or "").strip()
    if len(motivo) < 5:
        raise HTTPException(422, "Escreva o motivo da remoção (pelo menos 5 letras).")
    foto.removido_em, foto.removido_por, foto.removido_motivo = agora_local(), ctx.usuario.nome, motivo
    envio = db.get(EnvioPrestador, foto.envio_id)
    detalhes = {"envio": envio.numero if envio else foto.envio_id, "foto": foto.nome, "motivo": motivo}
    auditar(db, ctx, "REMOVER", "foto_envio", foto.id, detalhes)
    db.commit()
    return {"id": foto.id}


@rota.get("/envios/fotos/{foto_id}/arquivo")
def arquivo_foto(foto_id: int, db: Session = Depends(get_db), _: Contexto = Depends(EXPEDICAO)):
    foto = db.get(EnvioPrestadorFoto, foto_id)
    if not foto or foto.removido_em:
        raise HTTPException(404, "Foto não encontrada.")
    return resposta_arquivo(foto.arquivo, foto.nome)


# ---------------------------------------------------------------- documentos


@rota.get("/envios/{envio_id}/pdf")
def pdf(envio_id: int, db: Session = Depends(get_db), ctx: Contexto = Depends(EXPEDICAO)) -> Response:
    """Comprovante interno do envio. Pode ir junto com o material: NUNCA cita o cliente final."""
    envio = _buscar_envio(db, envio_id)
    conteudo = pdf_envio(db, dados_envio(db, envio))
    auditar(db, ctx, "GERAR_PDF", "envio_prestador", envio.id, {"numero": envio.numero})
    db.commit()
    nome = f"Envio_{envio.numero}.pdf"
    return Response(conteudo, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{nome}"'})


@rota.get("/envios/{envio_id}/modelo-ensaio")
def modelo_ensaio(envio_id: int, db: Session = Depends(get_db), ctx: Contexto = Depends(EXPEDICAO)) -> Response:
    """Modelo .docx de requisição de ensaio do laboratório, com as células "Preencher" preenchidas."""
    envio = _buscar_envio(db, envio_id)
    if not prestador_usa_modelo(db, envio.prestador):
        raise HTTPException(409, "O modelo de requisição de ensaio só vale para o laboratório configurado nos parâmetros.")
    caminho = arquivo_modelo(db)
    if caminho is None:
        raise HTTPException(404, "O modelo de requisição de ensaio não foi encontrado no servidor. Avise o administrador.")
    conteudo = preencher_modelo(db, caminho, dados_envio(db, envio))
    auditar(db, ctx, "GERAR_DOCX", "envio_prestador", envio.id, {"numero": envio.numero, "modelo": caminho.name})
    db.commit()
    nome = f"Requisicao_ensaio_{envio.numero}.docx"
    return Response(
        conteudo,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )
