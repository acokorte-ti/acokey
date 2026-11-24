"""Peças do ciclo do lote usadas pela página do lote (api_lotes.py) e pela página da etapa (api_etapas.py).

Regras do sistema antigo (legado/app.py): importação em massa por prefixo do nome do arquivo (IMPORT_INDEX),
avanço automático do cursor do lote, matéria-prima e carga de TT ligadas ao lote, envios a prestador da etapa,
prestadores e fornecedores oferecidos em cada etapa e a frase do equipamento usado.
"""
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import fluxo
from app.config import agora_local
from app.estado import estado_lotes
from app.historico import registrar_evento
from app.models import (
    Anexo,
    CargaTT,
    CargaTTLote,
    DatabookEnviado,
    EnvioPrestador,
    EnvioPrestadorLote,
    Equipamento,
    FornecedorMP,
    Lote,
    MateriaPrima,
    Prestador,
    Registro,
)

# Prefixo numérico do nome do arquivo -> [(etapa, sub, título do documento)], pelo checklist do databook de cada tipo.
# No sistema antigo a chave de PIN/BOX tinha o nome do produto do cliente; aqui é "PIN_BOX".
IMPORT_INDEX: dict[str, dict[str, list[tuple[str, str, str]]]] = {
    "PIN_BOX": {
        "1": [("receb_mp", "", "Certificado de Matéria Prima")],
        "2": [("trat_termico", "", "Relatório de Tratamento Térmico")],
        "3": [("dureza", "", "Relatório de Dureza")],
        "4": [("dim_final", "", "Relatório de Inspeção Dimensional")],
        "5": [("visual", "", "Relatório Inspeção Visual")],
        "6": [("lab_ext", "tracao", "Ensaio de Tração")],
        "7": [("lab_ext", "charpy", "Ensaio de Charpy")],
        "8": [("lp", "", "Ensaio de Líquido Penetrante")],
        "9": [("fosfato", "", "Certificado Revestimento - Fosfato de Manganês")],
        "10": [("embalagem", "", "Certificado Parafuso M6x1x10mm")],
    },
    "ARK": {
        "0": [("dim_final", "", "Relatório Dimensional + Visual (Capa)"), ("visual", "", "Relatório Dimensional + Visual (Capa)")],
        "1": [("receb_mp", "", "Certificado de Matéria Prima")],
        "2": [("trat_termico", "", "Relatório de Tratamento Térmico (Certificado ARC + CP)")],
        "3": [("lp", "", "Ensaio de Líquido Penetrante")],
        "4": [("lab_ext", "charpy", "Ensaio Mecânico - Charpy")],
        "5": [("fosfato", "", "Certificado Revestimento - Oxidação Negra")],
        "6": [("embalagem", "", "Certificado Parafuso M10x10mm / M10x12mm")],
    },
}
PERFIL_INDICE = {"PIN": "PIN_BOX", "BOX": "PIN_BOX", "ARK": "ARK"}
NOME_INDICE = {"PIN_BOX": "PIN/BOX", "ARK": "ARK"}
# Etapas aplicáveis sem documento próprio no checklist: a importação as aprova sozinhas
ETAPAS_AUTO_APROVAR = {"PIN_BOX": [("tambor", ""), ("usinagem", "")], "ARK": []}

# Tipo de serviço do envio a prestador -> etapa do lote em que o laudo/retorno é lançado
ETAPA_POR_TIPO_ENVIO = {
    "Ensaio de tração": "lab_ext",
    "Ensaio Charpy": "lab_ext",
    "Ensaio de tração + Charpy": "lab_ext",
    "NDT - líquido penetrante": "lp",
    "Revestimento fosfato": "fosfato",
    "Revestimento oxidação negra": "fosfato",
}

# Rótulo do prestador no registro aprovado por documento
ROTULO_PRESTADOR = {
    "lab_ext": "Laboratório externo",
    "fosfato": "Revestidor",
    "lp": "Laboratório NDT",
    "trat_termico": "Tratamento térmico externo",
}
ROTULO_PRESTADOR_TELA = {
    "lab_ext": "Laboratório externo",
    "fosfato": "Prestador do revestimento",
    "lp": "Laboratório NDT",
    "trat_termico": "Tratamento térmico externo",
    "receb_mp": "Fornecedor da matéria-prima",
}


def checklist_importacao(tipo: str) -> tuple[str, list[dict]]:
    indice = PERFIL_INDICE.get(tipo, "")
    linhas = []
    for prefixo, destinos in IMPORT_INDEX.get(indice, {}).items():
        for chave, sub, titulo in destinos:
            etapa = fluxo.POR_CHAVE[chave]
            curto = etapa.curto_de(tipo) + (f" / {fluxo.SUB_NOME[sub]}" if sub and tipo != "ARK" else "")
            linhas.append({"prefixo": prefixo, "etapa": chave, "sub": sub, "curto": curto, "titulo": titulo})
    return indice, linhas


def avancar_automatico(db: Session, lote: Lote) -> int:
    """Anda o cursor enquanto a etapa atual estiver resolvida (pulando as que não se aplicam ao tipo).

    Chamado depois de aprovar por documento e da importação em massa, como no sistema antigo.
    """
    db.flush()
    estados, _ = estado_lotes(db, [lote.id])
    estado = estados.get(lote.id, {})
    passos = 0
    while fluxo.pode_avancar(lote.etapa, lote.tipo, estado):
        lote.etapa += 1
        passos += 1
    if passos:
        lote.etapa_desde = agora_local()
        if lote.etapa >= fluxo.CONCLUIDO:
            registrar_evento(db, lote.id, "Todas as etapas aprovadas: lote concluído")
        else:
            registrar_evento(db, lote.id, f"Lote liberado automaticamente até a etapa '{fluxo.ETAPAS[lote.etapa].curto_de(lote.tipo)}'")
    return passos


def tem_dados_salvos(db: Session, lote_id: int) -> bool:
    """Lote que já tem registro ou anexo (mesmo anulado ou removido): editar e cancelar exigem quem pode aprovar."""
    registros = db.scalar(select(func.count(Registro.id)).where(Registro.lote_id == lote_id)) or 0
    anexos = db.scalar(select(func.count(Anexo.id)).where(Anexo.lote_id == lote_id)) or 0
    return registros + anexos > 0


def databook_enviado(db: Session, lote: Lote) -> bool:
    return (
        db.scalar(
            select(DatabookEnviado.id)
            .where(DatabookEnviado.op == (lote.op or "").strip(), func.upper(DatabookEnviado.tipo) == (lote.tipo or "").upper(),
                   DatabookEnviado.desfeito_em.is_(None))  # envio desfeito não bloqueia o cancelamento
            .limit(1)
        )
        is not None
    )


def mp_da_corrida(db: Session, corrida: str) -> MateriaPrima | None:
    """Corrida mais recente (não cancelada) com esse número em Matéria-prima."""
    corrida = (corrida or "").strip()
    if not corrida:
        return None
    return db.scalar(
        select(MateriaPrima)
        .where(MateriaPrima.corrida == corrida, MateriaPrima.cancelado_em.is_(None))
        .order_by(MateriaPrima.id.desc())
        .limit(1)
    )


def mp_do_lote(db: Session, lote: Lote) -> MateriaPrima | None:
    if lote.materia_prima_id:
        mp = db.get(MateriaPrima, lote.materia_prima_id)
        if mp and not mp.cancelado_em and (mp.corrida or "").strip() == (lote.corrida or "").strip():
            return mp
    return mp_da_corrida(db, lote.corrida)


def mp_json(mp: MateriaPrima | None) -> dict | None:
    if not mp:
        return None
    qt_real = mp.qt_real or 0
    return {
        "id": mp.id,
        "corrida": mp.corrida,
        "nf_entrada": mp.nf_entrada,
        "fornecedor": mp.fornecedor,
        "tipo_destino": mp.tipo_destino,
        "status": mp.status,
        "qt_ok": mp.qt_ok,
        "pct_refugo": round((mp.qt_rej or 0) / qt_real * 100, 1) if qt_real else 0.0,
        "obs_aprovacao": mp.obs_aprovacao,
    }


def carga_tt_ativa(db: Session, lote_id: int) -> dict | None:
    carga = db.scalar(
        select(CargaTT)
        .join(CargaTTLote, CargaTTLote.carga_id == CargaTT.id)
        .where(CargaTTLote.lote_id == lote_id, CargaTT.status != "cancelada")
        .order_by(CargaTT.id.desc())
        .limit(1)
    )
    if not carga:
        return None
    return {"id": carga.id, "numero": carga.numero, "status": carga.status, "data_planejada": carga.data_planejada}


def envios_da_etapa(db: Session, lote: Lote, chave: str) -> list[dict]:
    """Envios a prestador (não cancelados) deste lote que correspondem à etapa, do mais novo para o mais antigo.

    `laudo_lancado`: todos os sub-registros aplicáveis já têm registro aprovado/reprovado mais novo que o envio
    (só leitura; quem marca o envio como retornado é a tela de envios).
    """
    tipos = [t for t, k in ETAPA_POR_TIPO_ENVIO.items() if k == chave]
    if not tipos:
        return []
    envios = list(
        db.scalars(
            select(EnvioPrestador)
            .join(EnvioPrestadorLote, EnvioPrestadorLote.envio_id == EnvioPrestador.id)
            .where(EnvioPrestadorLote.lote_id == lote.id, EnvioPrestador.status != "cancelado", EnvioPrestador.tipo_servico.in_(tipos))
            .order_by(EnvioPrestador.id.desc())
        ).unique()
    )
    if not envios:
        return []
    _, ultimos = estado_lotes(db, [lote.id])
    etapa = fluxo.POR_CHAVE[chave]
    registros = [ultimos.get((lote.id, chave, s)) for s in etapa.subs_de(lote.tipo)]
    saida = []
    for e in envios:
        lancado = bool(e.data_envio) and all(
            r is not None and r.status in ("aprovado", "reprovado") and r.quando is not None and r.quando.date() >= e.data_envio
            for r in registros
        )
        saida.append({
            "id": e.id, "numero": e.numero, "prestador": e.prestador, "tipo_servico": e.tipo_servico, "status": e.status,
            "data_envio": e.data_envio, "data_retorno": e.data_retorno, "responsavel": e.responsavel, "laudo_lancado": lancado,
        })  # fmt: skip
    return saida


def prestadores_para_etapa(db: Session, chave: str, tipo: str) -> list[dict]:
    """Prestadores do cadastro que fazem o serviço da etapa (laboratório, revestidor, NDT, TT externo)."""
    if chave == "lab_ext":
        alvo = {"Lab mecânico (tração/Charpy)"}
    elif chave == "fosfato":
        alvo = {"Revestimento oxidação negra"} if tipo == "ARK" else {"Revestimento fosfato"}
    elif chave == "lp":
        alvo = {"NDT - líquido penetrante"}
    elif chave == "trat_termico":
        alvo = {"TT externo"}
    else:
        return []
    consulta = select(Prestador).where(Prestador.ativo.is_(True), Prestador.tipo_servico.in_(alvo)).order_by(Prestador.codigo)
    return [{"codigo": p.codigo, "razao_social": p.razao_social, "tipo_servico": p.tipo_servico} for p in db.scalars(consulta)]


def fornecedores_mp(db: Session) -> list[dict]:
    consulta = select(FornecedorMP).where(FornecedorMP.ativo.is_(True)).order_by(FornecedorMP.codigo)
    return [{"codigo": f.codigo, "razao_social": f.razao_social, "materiais": f.materiais} for f in db.scalars(consulta)]


def _data_br(valor: date | None) -> str:
    return valor.strftime("%d/%m/%Y") if valor else ""


def formatar_equipamento(e: Equipamento) -> str:
    """'Durômetro - Marca X - COD.DU-01 - Calibração Certificado 123 emitido em ... e vencimento em ...'."""
    partes = [e.descricao or ""]
    if e.marca:
        partes.append(f"Marca {e.marca}")
    partes.append(f"COD.{e.codigo}")
    base = " - ".join(p for p in partes if p)
    if e.certificado and (e.data_calibracao or e.validade_calibracao):
        base += (f" - Calibração Certificado {e.certificado} emitido em {_data_br(e.data_calibracao)} "
                 f"e vencimento em {_data_br(e.validade_calibracao)}.")  # fmt: skip
    elif e.certificado:
        base += f" - Certificado {e.certificado}."
    return base


def equipamentos(db: Session) -> list[dict]:
    hoje = agora_local().date()
    consulta = select(Equipamento).where(Equipamento.ativo.is_(True)).order_by(Equipamento.codigo)
    return [
        {
            "codigo": e.codigo,
            "descricao": e.descricao,
            "setor": e.setor,
            "texto": formatar_equipamento(e),
            "validade": e.validade_calibracao,
            "vencido": bool(e.validade_calibracao and e.validade_calibracao < hoje),
        }
        for e in db.scalars(consulta)
    ]
