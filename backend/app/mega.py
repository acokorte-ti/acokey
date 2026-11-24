"""Integração com o ERP Mega (Oracle) — SOMENTE LEITURA. Ligada por MEGA_HABILITADO=true no .env do servidor.

Padrão dos sistemas internos (o mesmo do EstoqueACK e dos Indicadores de Manutenção):
- Um usuário de banco PRÓPRIO deste sistema (`acokey_ro`), só com SELECT nas tabelas usadas, criado pelo DBA com
  `scripts/mega/01_criar_usuario_leitura.sql`. Assim o acesso de um sistema não amplia o do outro, e a auditoria
  do Oracle mostra qual sistema fez cada consulta.
- Conexão em modo thick (o banco do Mega exige criptografia nativa de rede), só a partir do servidor system-lab.
- Toda sessão começa com SET TRANSACTION READ ONLY. O sistema nunca grava no ERP: copia o que leu para as tabelas
  dele (PostgreSQL).
- A senha vai direto para o .env do servidor por `deploy/configurar_mega.sh`; nunca para o repositório ou conversa.

O que vem do Mega hoje: as ORDENS DE PRODUÇÃO das chavetas (antiga planilha "Cadastro_Lote_*.xlsx") e, como
referência, o pedido de origem, o cliente, o pedido do cliente (PO) e as notas fiscais de saída; e as ENTRADAS de
peças fundidas (NF, data, fornecedor, peça e quantidade), lidas na hora para ajudar a lançar a corrida na tela
Matéria-prima. A corrida não existe no Mega. Mapeamento e validação: docs/integracao_mega.md.

Regras da busca (24/11/2026, depois de comparar com a planilha de OPs do sistema antigo):
- Só OPs da filial MEGA_FILIAL abertas desde MEGA_OPS_DESDE, de item de chaveta: item já cadastrado aqui ou
  descrição com um dos termos de DESCRICOES_CHAVETA.
- OP NOVA entra no cadastro (origem "mega") se não estiver encerrada nem cancelada e se a descrição der o tipo
  PIN, BOX ou ARK. As encerradas que a Qualidade nunca cadastrou ficam de fora (são histórico).
- OP EXISTENTE: como no sistema antigo com a planilha, nada digitado é sobrescrito. O Mega só preenche campo
  vazio (item, descrição, tipo, cliente, QT lote); quando o cadastro tem outro valor, a diferença vai para o
  resumo da busca e para a tela da OP, para alguém da Qualidade decidir.
- PIV, NF, data e quantidade faturada NUNCA são preenchidos sozinhos. O pedido de origem da OP no Mega nem sempre é
  o pedido pelo qual ela foi faturada (4 de 13 OPs comparadas), e a nota fiscal não diz a OP. A OP guarda, como
  referência (`dados_mega`), as notas de saída do item no pedido: o PIV digitado (pedido do faturamento) ou, sem
  ele, o pedido de origem. Quando várias OPs dividem o mesmo pedido e item, a tela avisa que não dá para saber
  qual nota é de cada OP. O PO só é preenchido (se vazio) a partir do PIV digitado.
"""
import logging
import re
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import parametros
from app.config import config
from app.models import Auditoria, FornecedorMP, MateriaPrima, OrdemProducao
from app.ordens_producao import TAMANHOS, classificar
from app.seguranca import Contexto, auditar

log = logging.getLogger("uvicorn.error")

_cliente_iniciado = False
_trava_cliente = threading.Lock()

# Termos da descrição do item que identificam chaveta (validado em 24/11/2026 contra a planilha de OPs)
DESCRICOES_CHAVETA = ("TRAVAMENTO", "ANTI-ROTACIONAL")
SITUACOES_FECHADAS = ("EN", "CA")  # encerrada e cancelada: não entram como OP nova
ACAO_AUDITORIA = "SINCRONIZAR_MEGA"
_LOTE_IN = 900  # o Oracle aceita até 1000 valores num IN (...)


class MegaIndisponivel(Exception):
    pass


def situacao() -> tuple[bool, str]:
    """(pronto para ler?, motivo quando não está)."""
    cfg = config()
    if not cfg.mega_habilitado:
        return False, "A integração com o Mega está desligada."
    if not (cfg.mega_dsn and cfg.mega_usuario and cfg.mega_senha):
        return False, "Os dados de conexão com o Mega não foram configurados no servidor."
    return True, ""


def conectar():
    """Conexão com o Oracle do Mega em modo thick (o banco exige criptografia nativa de rede)."""
    import oracledb

    global _cliente_iniciado
    cfg = config()
    with _trava_cliente:
        if not _cliente_iniciado:
            oracledb.init_oracle_client(lib_dir=cfg.mega_instant_client)
            _cliente_iniciado = True
    return oracledb.connect(user=cfg.mega_usuario, password=cfg.mega_senha, dsn=cfg.mega_dsn)


def _mensagem_publica(erro: Exception) -> str:
    """Só o código e o texto do erro do Oracle (sem DSN, usuário ou senha)."""
    if isinstance(erro, MegaIndisponivel):
        return str(erro)
    achado = re.search(r"(ORA|DPI|DPY)-\d+[^\n]*", str(erro))
    return achado.group(0)[:300] if achado else type(erro).__name__


# ---------------------------------------------------------------- consultas


def _esquema() -> str:
    esquema = config().mega_esquema.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_$#]{0,29}", esquema):
        raise MegaIndisponivel("MEGA_ESQUEMA inválido no .env do servidor.")
    return esquema


def _texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float | Decimal) and valor == int(valor):
        valor = int(valor)
    return str(valor).strip()


def _inteiros(valores) -> list[int]:
    """Só números inteiros (o que não for número é descartado): é o que pode entrar no texto da consulta."""
    return sorted({int(t) for t in (_texto(v) for v in valores) if t.isdigit()})


def _em(coluna: str, numeros: list[int]) -> str:
    """`(coluna IN (1, 2) OR coluna IN (...))` em blocos de até 900; lista vazia não acha nada."""
    if not numeros:
        return "1 = 0"
    blocos = [numeros[i : i + _LOTE_IN] for i in range(0, len(numeros), _LOTE_IN)]
    return "(" + " OR ".join(f"{coluna} IN ({', '.join(str(int(n)) for n in bloco)})" for bloco in blocos) + ")"


def _igual(a: str, b: str, colunas: tuple[str, ...], prefixo_a: str = "", prefixo_b: str = "") -> str:
    return " AND ".join(f"{a}.{prefixo_a}{c} = {b}.{prefixo_b}{c}" for c in colunas)


_ORG = ("ORG_TAB_IN_CODIGO", "ORG_PAD_IN_CODIGO", "ORG_IN_CODIGO", "ORG_TAU_ST_CODIGO")
_CHAVE_OP = (*_ORG, "ORD_TAB_IN_CODIGO", "ORD_SEQ_IN_CODIGO", "ORD_IN_CODIGO")


def consulta_ops(itens_conhecidos: list[str]) -> tuple[str, dict]:
    """SELECT das OPs de chaveta, uma linha por OP, com o pedido de origem e o cliente. Caminho OP -> pedido ->
    cliente: o mesmo do EstoqueACK (validado lá em 79/79 OPs). Itens já cadastrados entram como inteiros
    conferidos; o resto vai como parâmetro."""
    e = _esquema()
    filtros = [f"UPPER(p.PRO_ST_DESCRICAO) LIKE :termo{n}" for n in range(len(DESCRICOES_CHAVETA))]
    itens = _inteiros(itens_conhecidos)
    if itens:
        filtros.append(_em("o.PRO_IN_CODIGO", itens))
    parametros_sql: dict = {f"termo{n}": f"%{t}%" for n, t in enumerate(DESCRICOES_CHAVETA)}
    parametros_sql |= {"filial": int(config().mega_filial),
                       "desde": datetime.combine(config().mega_ops_desde, datetime.min.time())}  # fmt: skip
    sql = f"""
WITH base AS (
  SELECT {', '.join(f'o.{c}' for c in _CHAVE_OP)}, o.PRO_IN_CODIGO, p.PRO_ST_DESCRICAO,
         o.ORD_ST_SITUACAO, o.ORD_RE_QTDE_ORDEM, o.ORD_ST_ALTERNATIVO
    FROM {e}.PRO_ORDENS o
    JOIN {e}.EST_PRODUTOS p ON p.PRO_IN_CODIGO = o.PRO_IN_CODIGO
   WHERE o.FIL_IN_CODIGO = :filial
     AND o.ORD_DT_ABERTURA_REAL >= :desde
     AND ({' OR '.join(filtros)})
), ori AS (
  SELECT {', '.join(f'r.{c}' for c in _CHAVE_OP)},
         MIN(r.PED_SER_ST_CODIGO) KEEP (DENSE_RANK FIRST ORDER BY r.ORI_IN_SEQUENCIA) AS PED_SER_ST_CODIGO,
         MIN(r.PED_IN_CODIGO) KEEP (DENSE_RANK FIRST ORDER BY r.ORI_IN_SEQUENCIA) AS PED_IN_CODIGO
    FROM {e}.PRO_ORIGEM r
   WHERE r.ORI_CH_TIPOORIGEM = 'D' AND r.ORD_IN_CODIGO IN (SELECT ORD_IN_CODIGO FROM base)
   GROUP BY {', '.join(f'r.{c}' for c in _CHAVE_OP)}
)
SELECT b.ORD_IN_CODIGO AS OP, b.PRO_IN_CODIGO AS ITEM, b.PRO_ST_DESCRICAO AS DESCRICAO, b.ORD_ST_SITUACAO AS SITUACAO,
       b.ORD_RE_QTDE_ORDEM AS QTDE, ag.AGN_ST_FANTASIA AS CLIENTE, NVL(vo.PED_IN_CODIGO, va.PED_IN_CODIGO) AS PEDIDO
  FROM base b
  LEFT JOIN ori ON {_igual('ori', 'b', _CHAVE_OP)}
  LEFT JOIN {e}.VEN_PEDIDOVENDA vo
    ON {_igual('vo', 'ori', _ORG)} AND vo.SER_ST_CODIGO = ori.PED_SER_ST_CODIGO AND vo.PED_IN_CODIGO = ori.PED_IN_CODIGO
  LEFT JOIN {e}.VEN_PEDIDOVENDA va
    ON ori.PED_IN_CODIGO IS NULL AND {_igual('va', 'b', _ORG)}
   AND va.SER_ST_CODIGO = '1' AND TO_CHAR(va.PED_IN_CODIGO) = b.ORD_ST_ALTERNATIVO
  LEFT JOIN {e}.GLO_AGENTES ag
    ON ag.AGN_TAB_IN_CODIGO = NVL(vo.CLI_TAB_IN_CODIGO, va.CLI_TAB_IN_CODIGO)
   AND ag.AGN_PAD_IN_CODIGO = NVL(vo.CLI_PAD_IN_CODIGO, va.CLI_PAD_IN_CODIGO)
   AND ag.AGN_IN_CODIGO = NVL(vo.CLI_IN_CODIGO, va.CLI_IN_CODIGO)"""
    return sql, parametros_sql


def consulta_notas(pedidos: list[int], itens: list[int]) -> str:
    """SELECT dos itens dos pedidos (com o PO) e das notas de saída ligadas a eles, uma linha por item do pedido x
    item de nota. Nota cancelada fica de fora. Pedidos e itens entram como inteiros conferidos."""
    e = _esquema()
    return f"""
SELECT ip.PED_IN_CODIGO AS PEDIDO, ip.PRO_IN_CODIGO AS ITEM, ip.SER_ST_CODIGO AS SERIE, ip.ITP_IN_SEQUENCIA AS SEQ_ITEM,
       ip.ITP_ST_PEDIDOCLIENTE AS PO, l.NF_NOT_IN_CODIGO AS NOTA_ID, l.NF_ITN_IN_SEQUENCIA AS SEQ_ITEM_NOTA,
       l.IPN_RE_QUANTIDADE AS QTD_NOTA, n.NOT_IN_NUMERO AS NF, n.NOT_DT_EMISSAO AS DATA_NF
  FROM {e}.VEN_ITEMPEDIDOVENDA ip
  LEFT JOIN {e}.VEN_ITEMPEDI_VEN_ITEMNOT l
    ON {_igual('l', 'ip', _ORG, prefixo_a='PE_')}
   AND l.PE_SER_ST_CODIGO = ip.SER_ST_CODIGO AND l.PE_PED_IN_CODIGO = ip.PED_IN_CODIGO
   AND l.PE_ITP_IN_SEQUENCIA = ip.ITP_IN_SEQUENCIA
  LEFT JOIN {e}.VEN_NOTAFISCAL n
    ON {_igual('n', 'l', _ORG, prefixo_b='NF_')}
   AND n.SEQ_TAB_IN_CODIGO = l.NF_SEQ_TAB_IN_CODIGO AND n.SEQ_IN_CODIGO = l.NF_SEQ_IN_CODIGO
   AND n.NOT_IN_CODIGO = l.NF_NOT_IN_CODIGO AND n.NOT_DT_CANCELAMENTO IS NULL
 WHERE {_em('ip.PED_IN_CODIGO', pedidos)}
   AND {_em('ip.PRO_IN_CODIGO', itens)}"""


def _dicionarios(cursor) -> list[dict]:
    nomes = [d[0].upper() for d in cursor.description]
    return [dict(zip(nomes, linha, strict=True)) for linha in cursor]


def ler(itens_conhecidos: list[str], pivs_cadastro: list[str]) -> tuple[list[dict], list[dict]]:
    """(linhas das OPs, linhas dos itens de pedido e notas). As notas são dos pedidos de origem e dos PIVs já
    digitados no cadastro, só para os itens das OPs lidas."""
    pronto, motivo = situacao()
    if not pronto:
        raise MegaIndisponivel(motivo)
    sql, parametros_sql = consulta_ops(itens_conhecidos)
    with conectar() as conexao, conexao.cursor() as cursor:
        conexao.call_timeout = 2 * 60 * 1000  # ms: uma consulta presa não pode segurar o ERP nem a tela
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.arraysize = 2000
        cursor.execute(sql, parametros_sql)
        ops = _dicionarios(cursor)
        pedidos = _inteiros([*(linha.get("PEDIDO") for linha in ops), *pivs_cadastro])
        itens = _inteiros(linha.get("ITEM") for linha in ops)
        notas: list[dict] = []
        if pedidos and itens:
            cursor.execute(consulta_notas(pedidos, itens))
            notas = _dicionarios(cursor)
    return ops, notas


# ---------------------------------------------------------------- de linhas para OPs e itens de pedido


@dataclass
class OpMega:
    op: str
    coditem: str
    descricao: str
    situacao: str
    qtde: int | None
    cliente: str
    pedido_origem: str


@dataclass
class ItemPedido:
    """Um item (produto) dentro de um pedido de venda: os POs e as notas de saída, somadas por número de nota."""

    pos: set[str] = field(default_factory=set)
    notas: dict[str, dict] = field(default_factory=dict)  # número da NF -> {"nf", "data", "qtd"}
    _vistos: set[tuple] = field(default_factory=set)

    @property
    def po(self) -> str:
        return "; ".join(sorted(self.pos))[: TAMANHOS["po"]]

    def lista_notas(self) -> list[dict]:
        return sorted(self.notas.values(), key=lambda n: (n["data"] or "", n["nf"]))


def _numero(valor) -> int | float | None:
    if valor is None:
        return None
    numero = Decimal(str(valor))
    return int(numero) if numero == numero.to_integral_value() else float(numero)


def montar_ops(linhas: list[dict]) -> dict[str, OpMega]:
    ops: dict[str, OpMega] = {}
    for linha in linhas:
        numero = _texto(linha["OP"])[: TAMANHOS["op"]]
        if not numero or numero in ops:
            continue
        qtde = _numero(linha.get("QTDE"))
        ops[numero] = OpMega(
            op=numero, coditem=_texto(linha.get("ITEM"))[: TAMANHOS["coditem"]],
            descricao=_texto(linha.get("DESCRICAO"))[: TAMANHOS["descricao"]], situacao=_texto(linha.get("SITUACAO"))[:4],
            qtde=round(qtde) if qtde is not None else None, cliente=_texto(linha.get("CLIENTE"))[: TAMANHOS["cliente"]],
            pedido_origem=_texto(linha.get("PEDIDO"))[: TAMANHOS["piv"]],
        )  # fmt: skip
    return ops


def montar_itens_pedido(linhas: list[dict]) -> dict[tuple[str, str], ItemPedido]:
    """{(pedido, item): ItemPedido}. O mesmo vínculo repetido conta uma vez; vínculo de nota cancelada não conta."""
    itens: dict[tuple[str, str], ItemPedido] = defaultdict(ItemPedido)
    for linha in linhas:
        item = itens[(_texto(linha.get("PEDIDO")), _texto(linha.get("ITEM")))]
        if _texto(linha.get("PO")):
            item.pos.add(_texto(linha["PO"]))
        nf = _texto(linha.get("NF"))
        if not nf:
            continue
        vinculo = (_texto(linha.get("SERIE")), _texto(linha.get("SEQ_ITEM")), _texto(linha.get("NOTA_ID")),
                   _texto(linha.get("SEQ_ITEM_NOTA")))  # fmt: skip
        if vinculo in item._vistos:
            continue
        item._vistos.add(vinculo)
        data_nf = linha.get("DATA_NF")
        data_nf = data_nf.date() if isinstance(data_nf, datetime) else data_nf
        nota = item.notas.setdefault(nf, {"nf": nf, "data": data_nf.isoformat() if data_nf else None, "qtd": 0})
        nota["qtd"] = _numero(Decimal(str(nota["qtd"])) + Decimal(str(linha.get("QTD_NOTA") or 0)))
    return dict(itens)


# ---------------------------------------------------------------- gravação no cadastro


@dataclass
class Resumo:
    lidas: int = 0
    novas: list[str] = field(default_factory=list)
    atualizadas: dict[str, list[str]] = field(default_factory=dict)  # OP -> campos que mudaram
    divergentes: dict[str, list[str]] = field(default_factory=dict)  # OP -> campos digitados diferentes do Mega
    fechadas_ignoradas: int = 0  # OP nova já encerrada ou cancelada no Mega
    sem_tipo_ignoradas: int = 0  # OP nova cuja descrição não dá PIN, BOX nem ARK
    notas_compartilhadas: int = 0  # OPs cujo pedido tem várias OPs do mesmo item

    def para_auditoria(self) -> dict:
        return {
            "lidas": self.lidas, "novas": len(self.novas), "atualizadas": len(self.atualizadas),
            "divergentes": len(self.divergentes), "fechadas_ignoradas": self.fechadas_ignoradas,
            "sem_tipo_ignoradas": self.sem_tipo_ignoradas, "notas_compartilhadas": self.notas_compartilhadas,
            "ops_novas": self.novas[:200], "ops_divergentes": dict(list(self.divergentes.items())[:200]),
        }  # fmt: skip


_CAMPOS_VISIVEIS = ("coditem", "descricao", "tipo", "cliente", "qt_lote", "po", "situacao_op", "dados_mega")


def _mesmo_texto(a: str | None, b: str | None) -> bool:
    return " ".join((a or "").upper().split()) == " ".join((b or "").upper().split())


def _nomes_de_cliente(atuais: dict[str, OrdemProducao], ops: dict[str, OpMega]) -> dict[str, str]:
    """Nome do cliente no Mega -> nome que a Qualidade usa no cadastro (o mais comum nas OPs já cadastradas).
    Mantém nas OPs novas o mesmo nome das antigas, que é o que sai nos relatórios."""
    contagem: dict[str, Counter] = defaultdict(Counter)
    for numero, mega in ops.items():
        cadastro = atuais.get(numero)
        if cadastro and cadastro.cliente and mega.cliente:
            contagem[mega.cliente][cadastro.cliente] += 1
    return {nome_mega: nomes.most_common(1)[0][0] for nome_mega, nomes in contagem.items()}


def aplicar(db: Session, ops: dict[str, OpMega], itens_pedido: dict[tuple[str, str], ItemPedido],
            agora: datetime | None = None) -> Resumo:  # fmt: skip
    """Grava no cadastro (flush, sem commit) o que veio do Mega, seguindo as regras do topo do módulo."""
    agora = agora or datetime.now(UTC)
    resumo = Resumo(lidas=len(ops))
    atuais = {o.op: o for o in db.scalars(select(OrdemProducao))}
    projeto_padrao = parametros.ler(db, "especificacao_codigo", "")[: TAMANHOS["projeto"]]
    nomes = _nomes_de_cliente(atuais, ops)

    def piv_digitado(numero: str) -> str:
        piv = (atuais[numero].piv or "").strip() if numero in atuais else ""
        return piv if piv.isdigit() else ""

    # Pedido de onde vêm as notas: o PIV digitado (pedido do faturamento) ou, sem ele, o de origem da OP no Mega
    pedido_notas = {n: piv_digitado(n) or o.pedido_origem for n, o in ops.items() if o.situacao != "CA"}
    ops_no_pedido = Counter((pedido_notas[n], ops[n].coditem) for n in pedido_notas if pedido_notas[n])

    for numero in sorted(ops):
        mega = ops[numero]
        cadastro = atuais.get(numero)
        tipo = classificar(mega.descricao)
        if cadastro is None:
            if mega.situacao in SITUACOES_FECHADAS:
                resumo.fechadas_ignoradas += 1
                continue
            if tipo is None:
                resumo.sem_tipo_ignoradas += 1
                continue
            cadastro = OrdemProducao(op=numero, origem="mega", coditem=mega.coditem, descricao=mega.descricao, tipo=tipo,
                                     cliente=nomes.get(mega.cliente, mega.cliente), qt_lote=mega.qtde,
                                     projeto=projeto_padrao)  # fmt: skip
            db.add(cadastro)
            resumo.novas.append(numero)
            antes = None
        else:
            antes = {c: getattr(cadastro, c) for c in _CAMPOS_VISIVEIS}
            if mega.situacao != "CA":
                _preencher_vazios(cadastro, mega, tipo, nomes)
                diferentes = [campo for campo, digitado, do_mega in (("coditem", cadastro.coditem, mega.coditem),
                                                                      ("descricao", cadastro.descricao, mega.descricao),
                                                                      ("tipo", cadastro.tipo, tipo))
                              if digitado and do_mega and not _mesmo_texto(digitado, do_mega)]  # fmt: skip
                if diferentes:
                    resumo.divergentes[numero] = diferentes

        pedido = pedido_notas.get(numero, "")
        item_pedido = itens_pedido.get((pedido, mega.coditem)) if pedido else None
        if item_pedido and item_pedido.po and not cadastro.po and pedido == piv_digitado(numero):
            cadastro.po = item_pedido.po
        mesmo_pedido = ops_no_pedido.get((pedido, mega.coditem), 0) if pedido else 0
        if mesmo_pedido > 1:
            resumo.notas_compartilhadas += 1
        cadastro.situacao_op = mega.situacao or None
        cadastro.dados_mega = {
            "coditem": mega.coditem, "descricao": mega.descricao, "cliente": mega.cliente, "qtde": mega.qtde,
            "pedido_origem": mega.pedido_origem or None, "pedido_notas": pedido or None,
            "notas_do_piv": bool(pedido) and pedido == piv_digitado(numero),
            "po": item_pedido.po if item_pedido else "", "notas": item_pedido.lista_notas() if item_pedido else [],
            "ops_mesmo_pedido": mesmo_pedido,
        }  # fmt: skip
        cadastro.sincronizado_em = agora
        if antes is not None:
            mudou = [c for c in _CAMPOS_VISIVEIS if getattr(cadastro, c) != antes[c]]
            if mudou:
                resumo.atualizadas[numero] = mudou
    db.flush()
    return resumo


def _preencher_vazios(cadastro: OrdemProducao, mega: OpMega, tipo: str | None, nomes: dict[str, str]) -> None:
    if not cadastro.coditem and mega.coditem:
        cadastro.coditem = mega.coditem
    if not cadastro.descricao and mega.descricao:
        cadastro.descricao = mega.descricao
    if not cadastro.tipo and tipo:
        cadastro.tipo = tipo
    if not cadastro.cliente and mega.cliente:
        cadastro.cliente = nomes.get(mega.cliente, mega.cliente)
    if cadastro.qt_lote is None and mega.qtde is not None:
        cadastro.qt_lote = mega.qtde


def sincronizar(db: Session, ctx: Contexto | None = None, simular: bool = False) -> Resumo:
    """Lê o Mega e atualiza o cadastro de OPs. `simular` faz tudo e desfaz no fim (nada fica gravado)."""
    itens = [i for i in db.scalars(select(OrdemProducao.coditem).distinct()) if i]
    pivs = [p for p in db.scalars(select(OrdemProducao.piv).distinct()) if p]
    linhas_ops, linhas_notas = ler(itens, pivs)
    ops = montar_ops(linhas_ops)
    if not ops and db.scalar(select(OrdemProducao.id).where(OrdemProducao.sincronizado_em.is_not(None)).limit(1)):
        # Consulta vazia depois de outras que trouxeram OPs quase sempre é permissão perdida ou filtro errado.
        raise MegaIndisponivel("A consulta ao Mega não devolveu nenhuma OP. O cadastro não foi alterado.")
    resumo = aplicar(db, ops, montar_itens_pedido(linhas_notas))
    if simular:
        db.rollback()
        return resumo
    auditar(db, ctx, ACAO_AUDITORIA, "ordens_producao", None, resumo.para_auditoria(), login="(agendador)")
    db.commit()
    return resumo


def mensagem_para_tela(erro: Exception, o_que: str = "falha ao gravar as OPs lidas") -> str:
    """Código e texto do Oracle, o motivo de MegaIndisponivel ou uma frase genérica (o detalhe fica no log)."""
    mensagem = _mensagem_publica(erro)
    if not re.match(r"(ORA|DPI|DPY)-", mensagem) and not isinstance(erro, MegaIndisponivel):
        mensagem = f"{o_que} (o detalhe está no log do servidor)"
    return mensagem


def registrar_falha(db: Session, ctx: Contexto | None, erro: Exception) -> str:
    """Desfaz o que estava pela metade e deixa a falha na auditoria. Devolve a mensagem para a tela."""
    db.rollback()
    mensagem = mensagem_para_tela(erro)
    auditar(db, ctx, ACAO_AUDITORIA, "ordens_producao", None, {"erro": mensagem}, login="(agendador)")
    db.commit()
    return mensagem


def ultima_busca(db: Session) -> dict | None:
    linha = db.scalar(select(Auditoria).where(Auditoria.acao == ACAO_AUDITORIA).order_by(Auditoria.id.desc()).limit(1))
    if linha is None:
        return None
    detalhes = linha.detalhes or {}
    return {
        "quando": linha.quando.isoformat() if linha.quando else None, "por": linha.login or "",
        "erro": detalhes.get("erro"), "lidas": detalhes.get("lidas"), "novas": detalhes.get("novas"),
        "atualizadas": detalhes.get("atualizadas"), "divergentes": detalhes.get("divergentes"),
        "ops_divergentes": sorted(detalhes.get("ops_divergentes") or {}),
    }  # fmt: skip


# ---------------------------------------------------------------- entradas de matéria-prima (peças fundidas)

# A peça fundida tem "FUNDID" e o tipo (PIN, BOX ou ARK) na descrição do produto (validado em 24/11/2026: 4 produtos,
# 27 entradas desde 2025, tipo igual ao das corridas do sistema antigo)
DESCRICAO_FUNDIDO = "FUNDID"
_CHAVE_NOTA_ENTRADA = (*_ORG, "AGN_TAB_IN_CODIGO", "AGN_PAD_IN_CODIGO", "AGN_IN_CODIGO", "AGN_TAU_ST_CODIGO",
                       "RCB_ST_NOTA", "RCB_DT_DOCUMENTO")  # fmt: skip


def consulta_entradas(desde: date) -> tuple[str, dict]:
    """SELECT dos itens de nota de entrada de peças fundidas da filial. A chave da nota inclui o fornecedor: o mesmo
    número de NF existe para fornecedores diferentes."""
    e = _esquema()
    sql = f"""
SELECT r.RCB_ST_NOTA AS NF, r.RCB_DT_MOVIMENTO AS ENTRADA, r.RCB_DT_DOCUMENTO AS EMISSAO, r.AGN_IN_CODIGO AS FORNECEDOR_CODIGO,
       a.AGN_ST_NOME AS FORNECEDOR, a.AGN_ST_FANTASIA AS FORNECEDOR_FANTASIA, i.RCI_IN_SEQUENCIA AS SEQ_ITEM,
       i.PRO_IN_CODIGO AS PRODUTO, p.PRO_ST_DESCRICAO AS DESCRICAO, i.UNI_ST_UNIDADE AS UNIDADE, i.RCI_RE_QUANTIDADE AS QTDE
  FROM {e}.EST_ITENSRECEB i
  JOIN {e}.EST_RECEBIMENTO r ON {_igual('i', 'r', _CHAVE_NOTA_ENTRADA)}
  JOIN {e}.EST_PRODUTOS p ON p.PRO_IN_CODIGO = i.PRO_IN_CODIGO
  LEFT JOIN {e}.GLO_AGENTES a
    ON a.AGN_TAB_IN_CODIGO = r.AGN_TAB_IN_CODIGO AND a.AGN_PAD_IN_CODIGO = r.AGN_PAD_IN_CODIGO AND a.AGN_IN_CODIGO = r.AGN_IN_CODIGO
 WHERE r.FIL_IN_CODIGO = :filial
   AND r.RCB_DT_MOVIMENTO >= :desde
   AND UPPER(p.PRO_ST_DESCRICAO) LIKE :fundido
   AND (UPPER(p.PRO_ST_DESCRICAO) LIKE :pin OR UPPER(p.PRO_ST_DESCRICAO) LIKE :box OR UPPER(p.PRO_ST_DESCRICAO) LIKE :ark)"""
    parametros_sql = {"filial": int(config().mega_filial), "desde": datetime.combine(desde, datetime.min.time()),
                      "fundido": f"%{DESCRICAO_FUNDIDO}%", "pin": "%PIN%", "box": "%BOX%", "ark": "%ARK%"}  # fmt: skip
    return sql, parametros_sql


def ler_entradas(desde: date) -> list[dict]:
    pronto, motivo = situacao()
    if not pronto:
        raise MegaIndisponivel(motivo)
    sql, parametros_sql = consulta_entradas(desde)
    with conectar() as conexao, conexao.cursor() as cursor:
        conexao.call_timeout = 60 * 1000  # ms: é uma consulta da tela
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute(sql, parametros_sql)
        return _dicionarios(cursor)


@dataclass
class EntradaMega:
    chave: str  # fornecedor | NF | emissão | item da nota
    nf: str
    entrada: date | None
    emissao: date | None
    fornecedor_codigo: str
    fornecedor: str  # razão social no Mega
    descricao: str
    tipo: str | None
    unidade: str
    qtde: int | None


def _data(valor) -> date | None:
    return valor.date() if isinstance(valor, datetime) else valor


def montar_entradas(linhas: list[dict]) -> list[EntradaMega]:
    entradas: dict[str, EntradaMega] = {}
    for linha in linhas:
        emissao = _data(linha.get("EMISSAO"))
        chave = "|".join((_texto(linha.get("FORNECEDOR_CODIGO")), _texto(linha.get("NF")),
                          emissao.isoformat() if emissao else "", _texto(linha.get("SEQ_ITEM"))))  # fmt: skip
        if chave in entradas:
            continue
        qtde = _numero(linha.get("QTDE"))
        descricao = _texto(linha.get("DESCRICAO"))
        entradas[chave] = EntradaMega(
            chave=chave, nf=_texto(linha.get("NF"))[:40], entrada=_data(linha.get("ENTRADA")), emissao=emissao,
            fornecedor_codigo=_texto(linha.get("FORNECEDOR_CODIGO")),
            fornecedor=(_texto(linha.get("FORNECEDOR")) or _texto(linha.get("FORNECEDOR_FANTASIA")))[:160],
            descricao=descricao, tipo=classificar(descricao), unidade=_texto(linha.get("UNIDADE")),
            qtde=round(qtde) if qtde is not None else None,
        )  # fmt: skip
    return list(entradas.values())


def _nf(numero: str | None) -> str:
    return (numero or "").strip().lstrip("0")


def entradas_para_tela(db: Session, entradas: list[EntradaMega]) -> list[dict]:
    """Cada entrada com o que já foi lançado na tela Matéria-prima (mesma NF, data de recebimento e tipo), quanto
    falta e o nome de fornecedor a sugerir: o que a Qualidade já usou para esse fornecedor do Mega, senão o código do
    cadastro de fornecedores com a mesma razão social, senão a razão social do Mega."""
    lancadas: dict[tuple, list[MateriaPrima]] = defaultdict(list)
    for mp in db.scalars(select(MateriaPrima).where(MateriaPrima.cancelado_em.is_(None))):
        lancadas[(_nf(mp.nf_entrada), mp.data_recebimento, mp.tipo_destino)].append(mp)
    apelidos: dict[str, Counter] = defaultdict(Counter)
    for e in entradas:
        for mp in lancadas.get((_nf(e.nf), e.entrada, e.tipo), []):
            if mp.fornecedor.strip():
                apelidos[e.fornecedor_codigo][mp.fornecedor.strip()] += 1
    cadastro = {" ".join(f.razao_social.upper().split()): f.codigo for f in db.scalars(select(FornecedorMP).where(FornecedorMP.ativo))}
    saida = []
    for e in sorted(entradas, key=lambda x: (x.entrada or date.min, x.nf), reverse=True):
        mps = lancadas.get((_nf(e.nf), e.entrada, e.tipo), [])
        lancado = sum(mp.qt_fund for mp in mps)
        sugerido = (apelidos[e.fornecedor_codigo].most_common(1)[0][0] if apelidos.get(e.fornecedor_codigo)
                    else cadastro.get(" ".join(e.fornecedor.upper().split()), e.fornecedor))  # fmt: skip
        saida.append({
            "chave": e.chave, "nf": e.nf, "entrada": e.entrada, "emissao": e.emissao, "fornecedor": e.fornecedor,
            "fornecedor_sugerido": sugerido, "descricao": e.descricao, "tipo": e.tipo, "unidade": e.unidade,
            "qtde": e.qtde, "lancado": lancado, "falta": max((e.qtde or 0) - lancado, 0),
            "corridas": [{"id": mp.id, "corrida": mp.corrida} for mp in mps],
        })  # fmt: skip
    return saida


# ---------------------------------------------------------------- linha de comando


def testar() -> None:
    """`python -m app.mega testar`: confere a conexão e o que o usuário do banco pode fazer. Não altera nada."""
    cfg = config()
    if not (cfg.mega_dsn and cfg.mega_usuario and cfg.mega_senha):
        raise SystemExit("MEGA_DSN, MEGA_USUARIO e MEGA_SENHA ainda não estão no .env do servidor.")
    try:
        with conectar() as conexao, conexao.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            usuario = cursor.execute("select user from dual").fetchone()[0]
            privilegios = [linha[0] for linha in cursor.execute("select privilege from session_privs order by 1")]
            visiveis = cursor.execute(
                "select count(*) from all_objects where owner = :dono and object_type in ('TABLE', 'VIEW')",
                dono=cfg.mega_esquema,
            ).fetchone()[0]
    except Exception as erro:  # noqa: BLE001 — ferramenta de diagnóstico: mostra o motivo e sai
        raise SystemExit(f"Não conectou: {_mensagem_publica(erro)}") from None
    de_escrita = [p for p in privilegios if not p.startswith(("SELECT", "READ", "CREATE SESSION"))]
    print(f"Conexão OK como {usuario}.")
    print(f"Tabelas e visões de {cfg.mega_esquema} visíveis: {visiveis}.")
    print(f"Privilégios: {', '.join(privilegios) or '(nenhum de sistema)'}.")
    if de_escrita:
        print(f"ATENÇÃO: este usuário tem privilégios além de leitura: {', '.join(de_escrita)}. Peça ao DBA para revogar.")
    else:
        print("Somente leitura: confirmado.")


def _linha_de_comando(simular: bool) -> None:
    """`python -m app.mega sincronizar [--simular]`, usado pelo cron do servidor. Imprime só contagens."""
    from app.db import SessionLocal

    pronto, motivo = situacao()
    if not pronto:
        print(motivo)
        return
    with SessionLocal() as db:
        try:
            resumo = sincronizar(db, simular=simular)
        except Exception as erro:  # noqa: BLE001 — a falha fica na auditoria e no log; o cron segue
            log.exception("Falha na busca de OPs no Mega")
            mensagem = _mensagem_publica(erro) if simular else registrar_falha(db, None, erro)
            raise SystemExit(f"Falha: {mensagem}") from None
    prefixo = "SIMULAÇÃO (nada gravado): " if simular else ""
    print(f"{prefixo}{resumo.lidas} OPs lidas, {len(resumo.novas)} novas, {len(resumo.atualizadas)} atualizadas, "
          f"{len(resumo.divergentes)} com dados digitados diferentes do Mega, {resumo.fechadas_ignoradas} encerradas ou "
          f"canceladas e {resumo.sem_tipo_ignoradas} sem tipo ignoradas.")  # fmt: skip


if __name__ == "__main__":
    import sys

    argumentos = sys.argv[1:]
    if argumentos == ["testar"]:
        testar()
    elif argumentos in (["sincronizar"], ["sincronizar", "--simular"]):
        _linha_de_comando(simular="--simular" in argumentos)
    else:
        raise SystemExit("Uso: python -m app.mega testar | sincronizar [--simular]")
