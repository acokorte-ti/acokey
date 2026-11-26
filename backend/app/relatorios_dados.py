"""Dados comuns às cargas de TT e aos relatórios gerados pelo sistema (Dureza RIP-35, Tratamento Térmico, Visual).

Regras trazidas do sistema antigo (legado/app.py: carregar_equipamentos, _equip_para_js, _formatar_equipamento,
_primeiro_nome, _produto_sem_instr, _ctx_relatorio_dureza, _ctx_relatorio_visual, _br_date, _lote_completo).
Diferenças:
- Nada do cliente fica no código: nome curto, código da especificação, designações do produto e desenho padrão
  vêm dos parâmetros (o antigo tinha no código).
- Especificação de dureza não cadastrada BLOQUEIA o relatório (o antigo usava 30/39 HRc no relatório de TT).
"""
import re
import unicodedata
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import fluxo, parametros
from app.api_recursos import listar_desenhos
from app.config import agora_local
from app.estado import estado_lotes
from app.historico import registrar_evento
from app.models import Equipamento, EspecificacaoTipo, Lote, MateriaPrima, OrdemProducao, Usuario
from app.seguranca import Contexto, auditar

# Material por tipo (CLAUDE.md, seção 3). O antigo punha "SC 4330" também no relatório de TT do ARK.
MATERIAL = {"PIN": "SC 4330", "BOX": "SC 4330", "ARK": "H11 Modified"}

# Parâmetros novos deste módulo (valor padrão SEM dado do cliente; a Qualidade preenche na tela Parâmetros)
PARAM_NOME_PECA = "relatorio_nome_peca_padrao"  # item quando a OP não tem descrição ({tipo} vira PIN/BOX/ARK)
PARAM_DESENHO = "relatorio_desenho_padrao"  # desenho quando não há PDF do desenho para o item ({tipo})
PARAM_ITEM_TT = "relatorio_tt_item"  # coluna "Item" do relatório de TT ({tipo})
PARAM_DESIGNACAO = "visual_designacao_pin_box"  # "acabamento das <designação>'s" (PIN/BOX) na inspeção visual
PARAM_DESIGNACAO_LASER = "visual_designacao_laser_pin_box"  # "gravado a laser: <designação> + R.." (PIN/BOX)
PADROES_PARAM = {
    PARAM_NOME_PECA: "",
    PARAM_DESENHO: "",
    PARAM_ITEM_TT: "Chaveta {tipo}",
    PARAM_DESIGNACAO: "PIN/BOX",
    PARAM_DESIGNACAO_LASER: "PIN/BOX",
}


def ler_param(db: Session, chave: str, tipo: str = "") -> str:
    return parametros.ler(db, chave, PADROES_PARAM.get(chave, "")).replace("{tipo}", tipo)


def normalizar(texto: str | None) -> str:
    """'Têmpera' -> 'tempera' (para achar o forno pela descrição do cadastro)."""
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()


def data_br(valor: date | None) -> str:
    return valor.strftime("%d/%m/%Y") if valor else ""


def numero_limite(valor: Decimal | float | None) -> str:
    """Limite da especificação como texto: 30 -> '30'; 30.5 -> '30,5'."""
    if valor is None:
        return ""
    numero = float(valor)
    return str(int(numero)) if numero == int(numero) else f"{numero:g}".replace(".", ",")


# ---------------------------------------------------------------- equipamentos (fornos e durômetros)


def rotulo_equipamento(e: Equipamento) -> str:
    """'Forno de têmpera - Marca (FO 1)': como aparece na lista e na legenda do forno no PDF de TT."""
    return f"{e.descricao} - {e.marca} ({e.codigo})" if e.marca else f"{e.descricao} ({e.codigo})"


def texto_equipamento(e: Equipamento) -> str:
    """Frase do 'Equipamento' no RIP-35, com a calibração (antigo _formatar_equipamento)."""
    partes = [e.descricao or ""]
    if e.marca:
        partes.append(f"Marca {e.marca}")
    partes.append(f"COD.{e.codigo}")
    texto = " - ".join(p for p in partes if p)
    if e.certificado and (e.data_calibracao or e.validade_calibracao):
        texto += (f" - Calibração Certificado {e.certificado} emitido em {data_br(e.data_calibracao)} "
                  f"e vencimento em {data_br(e.validade_calibracao)}.")  # fmt: skip
    elif e.certificado:
        texto += f" - Certificado {e.certificado}."
    return texto


def equipamento_dict(e: Equipamento) -> dict:
    hoje = agora_local().date()
    return {
        "codigo": e.codigo,
        "descricao": e.descricao,
        "marca": e.marca,
        "rotulo": rotulo_equipamento(e),
        "certificado": e.certificado,
        "data_calibracao": e.data_calibracao,
        "validade_calibracao": e.validade_calibracao,
        "vencida": bool(e.validade_calibracao and e.validade_calibracao < hoje),
        "ativo": e.ativo,
    }


def _equipamentos(db: Session) -> list[Equipamento]:
    return list(db.scalars(select(Equipamento).where(Equipamento.ativo.is_(True)).order_by(Equipamento.codigo)))


def fornos(db: Session) -> tuple[list[Equipamento], list[Equipamento]]:
    """(fornos de têmpera, fornos de revenimento), pela descrição do cadastro, como no antigo."""
    todos = _equipamentos(db)
    tempera = [e for e in todos if "tempera" in normalizar(e.descricao) and "revenimento" not in normalizar(e.descricao)]
    revenimento = [e for e in todos if "revenimento" in normalizar(e.descricao)]
    return tempera, revenimento


def durometros(db: Session) -> list[Equipamento]:
    return [e for e in _equipamentos(db) if e.codigo.upper().startswith("DUR") or "dur" in normalizar(e.descricao)]


def equipamento(db: Session, codigo: str) -> Equipamento | None:
    codigo = (codigo or "").strip()
    return db.scalar(select(Equipamento).where(Equipamento.codigo == codigo)) if codigo else None


# ---------------------------------------------------------------- OP, cliente, peça e desenho


def primeiro_nome(cliente: str | None) -> str:
    """'EMPRESA EXEMPLO SOCIEDADE ANONIMA' -> 'Empresa' (como o antigo mostrava o cliente)."""
    partes = (cliente or "").strip().split()
    return partes[0].capitalize() if partes else ""


_RE_INSTR = re.compile(r"INSTR\.?\s*CONTROLE\s*TRAVAMENTO\s*(?:DES\s+)?", re.IGNORECASE)


def produto_sem_instr(descricao: str | None) -> str:
    """Tira o prefixo de instrução da descrição da OP ('INSTR. CONTROLE TRAVAMENTO X' -> 'X')."""
    if not descricao:
        return ""
    achado = _RE_INSTR.search(descricao)
    return descricao[achado.end():].strip() if achado else descricao.strip()


def cadastros_op(db: Session, ops: list[str]) -> dict[str, OrdemProducao]:
    ops = sorted({(o or "").strip() for o in ops if o})
    if not ops:
        return {}
    return {o.op: o for o in db.scalars(select(OrdemProducao).where(OrdemProducao.op.in_(ops)))}


def cliente_da_op(db: Session, cadastro: OrdemProducao | None) -> str:
    """Primeiro nome do cliente no cadastro da OP; sem cadastro, o nome curto dos parâmetros."""
    return primeiro_nome(cadastro.cliente if cadastro else "") or parametros.ler(db, "cliente_nome_curto")


# Primeira medida "N x N" da descrição (ex.: "ARK... -51,5x26x120mm DESENHO R0"): o Item do relatório para antes dela
_RE_DIMENSOES = re.compile(r"[\s-]*\d+(?:[.,]\d+)?\s*[xX×]\s*\d")


def item_sem_dimensoes(descricao: str | None) -> str:
    """Item do cabeçalho dos relatórios: a descrição até as dimensões (sem elas e sem o que vem depois)."""
    texto = (descricao or "").strip()
    achado = _RE_DIMENSOES.search(texto)
    return texto[: achado.start()].strip(" -") if achado and achado.start() > 0 else texto


def nome_peca(db: Session, lote: Lote, cadastro: OrdemProducao | None) -> str:
    descricao = cadastro.descricao if cadastro else ""
    return item_sem_dimensoes(produto_sem_instr(descricao)) or ler_param(db, PARAM_NOME_PECA, lote.tipo) or f"Chaveta {lote.tipo}"


# Código do desenho dentro do nome do PDF, copiado como está escrito (nunca "arrumado"):
# depois de "DES" ("... 51x26mm DES ABC123 REV 0" -> "ABC123 REV 0") ou, sem "DES", o código com hífens
# ("ABC-DE-XYZ-PIN-18-22 REV 0")
_RE_DEPOIS_DE_DES = re.compile(r"\bDES\.?\s+(\S+(?:\s+REV\.?\s*\d+)?)", re.IGNORECASE)
_RE_CODIGO_DESENHO = re.compile(r"\b[A-Z0-9]+(?:-[A-Z0-9]+){3,}(?:\s+REV\.?\s*\d+)?", re.IGNORECASE)


def descricao_do_desenho(lote: Lote) -> str:
    """Nome do PDF do desenho cadastrado para o item do lote ('' se não houver)."""
    coditem = (lote.coditem or "").strip()
    achado = next((d for d in listar_desenhos() if d["coditem"] == coditem), None) if coditem else None
    return achado["descricao"] if achado else ""


def codigo_do_desenho(descricao: str) -> str:
    codigo = _RE_DEPOIS_DE_DES.search(descricao) or _RE_CODIGO_DESENHO.search(descricao)
    return codigo.group(codigo.lastindex or 0) if codigo else descricao


def desenho_do_item(db: Session, lote: Lote) -> str:
    """Desenho / revisão: do PDF do desenho cadastrado para o item; sem desenho, o padrão dos parâmetros."""
    descricao = descricao_do_desenho(lote)
    return codigo_do_desenho(descricao) if descricao else ler_param(db, PARAM_DESENHO, lote.tipo)


def fornecedor_da_corrida(db: Session, lote: Lote) -> str:
    mp = db.get(MateriaPrima, lote.materia_prima_id) if lote.materia_prima_id else None
    if mp is None and lote.corrida:
        mp = db.scalar(
            select(MateriaPrima)
            .where(MateriaPrima.corrida == lote.corrida, MateriaPrima.cancelado_em.is_(None))
            .order_by(MateriaPrima.id.desc())
        )
    return mp.fornecedor if mp else ""


# ---------------------------------------------------------------- especificação (nunca inventar)


def especificacao_dureza(db: Session, tipo: str) -> tuple[float, float, str, str]:
    """(mínimo, máximo, '30 a 39 HRc', '30/39 HRc'). Sem os dois limites cadastrados, o relatório não sai."""
    spec = db.get(EspecificacaoTipo, tipo)
    if not spec or spec.dureza_min is None or spec.dureza_max is None:
        raise HTTPException(
            422,
            f"A especificação de dureza do tipo {tipo} ainda não está cadastrada. "
            "Cadastre os limites em Especificações antes de gerar o relatório.",
        )
    minimo, maximo = numero_limite(spec.dureza_min), numero_limite(spec.dureza_max)
    return float(spec.dureza_min), float(spec.dureza_max), f"{minimo} a {maximo} HRc", f"{minimo}/{maximo} HRc"


# ---------------------------------------------------------------- quem executa e quem aprova


def pessoa(u: Usuario) -> dict:
    return {"id": u.id, "nome": u.nome, "cargo": u.cargo, "tem_assinatura": bool(u.assinatura_arquivo)}


def executores(db: Session, ctx: Contexto, modulos: tuple[str, ...]) -> list[dict]:
    """Quem pode constar como "Executado por": usuários ativos do(s) módulo(s), e sempre quem está logado."""
    lista = [
        u for u in db.scalars(select(Usuario).where(Usuario.ativo.is_(True)).order_by(Usuario.nome))
        if u.id == ctx.usuario.id or any(getattr(u, f"mod_{m}") for m in modulos)
    ]  # fmt: skip
    return [pessoa(u) for u in lista]


def aprovadores(db: Session) -> list[dict]:
    """Só quem tem "pode aprovar" assina como "Aprovado por" (ser administrador não basta)."""
    consulta = select(Usuario).where(Usuario.ativo.is_(True), Usuario.pode_aprovar.is_(True)).order_by(Usuario.nome)
    return [pessoa(u) for u in db.scalars(consulta)]


def buscar_executor(db: Session, usuario_id: int) -> Usuario:
    u = db.get(Usuario, usuario_id)
    if not u or not u.ativo:
        raise HTTPException(422, "Escolha quem executou o ensaio (usuário ativo do sistema).")
    return u


def buscar_aprovador(db: Session, usuario_id: int) -> Usuario:
    u = db.get(Usuario, usuario_id)
    if not u or not u.ativo or not u.pode_aprovar:
        raise HTTPException(422, "O campo 'Aprovado por' só aceita quem pode aprovar pela Qualidade.")
    return u


# ---------------------------------------------------------------- avanço do lote


def avancar_se_parado(db: Session, ctx: Contexto, lote: Lote, chave: str, origem: str) -> bool:
    """Avança o cursor do lote SÓ se ele está parado nesta etapa e ela ficou resolvida (antigo: relatório de TT).

    Lote que já passou da etapa (ex.: relatório gerado de novo para uma carga concluída) não é mexido.
    Continua andando enquanto a etapa seguinte não se aplica ao tipo ou já está resolvida.
    """
    if lote.etapa != fluxo.INDICE[chave]:
        return False
    db.flush()
    estados, _ = estado_lotes(db, [lote.id])
    estado = estados.get(lote.id, {})
    antes = lote.etapa
    while fluxo.pode_avancar(lote.etapa, lote.tipo, estado):
        lote.etapa += 1
    if lote.etapa == antes:
        return False
    lote.etapa_desde = agora_local()
    nome = fluxo.ETAPAS[antes].curto_de(lote.tipo)
    registrar_evento(db, lote.id, f"Etapa '{nome}' concluída e liberada (automático, ao gerar o {origem})")
    auditar(db, ctx, "AVANCAR", "lote", lote.id, {"etapa": [antes, lote.etapa], "via": origem}, lote_id=lote.id)
    return True
