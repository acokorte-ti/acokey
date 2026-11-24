"""Cadastro de ordens de produção (OPs): leitura da planilha, comparação com o cadastro e inclusão das OPs novas.

Hoje a fonte é a planilha mantida pelo PCP (aba "Dados", colunas A..L). A sincronização com o ERP (somente
leitura), quando vier, deve seguir o mesmo caminho: montar `LinhaOP`s a partir da fonte e chamar `comparar` e
`incluir_novas`. As telas e a auditoria continuam iguais.

Regra do sistema antigo (legado/app.py: comparação e aplicação da planilha de OPs):
só as OPs NOVAS entram; OPs alteradas ou que sumiram da planilha aparecem só como aviso. Nada é sobrescrito
nem removido sozinho: mudar uma OP existente é pela tela de edição, uma por uma.
"""
import io
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TIPOS_LOTE, OrdemProducao
from app.seguranca import limpar_texto

ABA = "Dados"
# Campo do cadastro -> título da coluna na planilha (A..L, nesta ordem)
COLUNAS: tuple[tuple[str, str], ...] = (
    ("cliente", "Cliente"),
    ("op", "OP"),
    ("coditem", "CODITEM"),
    ("descricao", "Descrição"),
    ("tipo", "Classificação"),
    ("data_faturamento", "Data Fat."),
    ("nf", "NF"),
    ("piv", "Pedido"),
    ("qt_lote", "QT_Lote"),
    ("qt_faturada", "Qtd.Faturada"),
    ("projeto", "PROJETO"),
    ("po", "PO"),
)
ROTULO = dict(COLUNAS)
TAMANHOS = {"op": 20, "cliente": 160, "coditem": 40, "descricao": 300, "nf": 40, "piv": 40, "projeto": 120, "po": 60}
CAMPOS_COMPARADOS = [c for c, _ in COLUNAS if c != "op"]


class ErroPlanilha(Exception):
    """Mensagem pronta para o usuário."""


def classificar(descricao: str | None) -> str | None:
    """Tipo da chaveta pela descrição do item. Regra do sistema antigo (legado/app.py, `classificar`): procura PIN,
    depois BOX, depois ARK, nessa ordem. A ordem importa: há descrições de PIN e BOX que também contêm "ARK"."""
    texto = (descricao or "").upper()
    return next((tipo for tipo in TIPOS_LOTE if tipo in texto), None)


@dataclass
class LinhaOP:
    op: str
    cliente: str = ""
    coditem: str = ""
    descricao: str = ""
    tipo: str | None = None  # PIN/BOX/ARK; outro valor da planilha fica sem tipo
    data_faturamento: date | None = None
    nf: str = ""
    piv: str = ""
    qt_lote: int | None = None
    qt_faturada: int | None = None
    projeto: str = ""
    po: str = ""

    def valores(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- conversão das células


def texto(valor: Any) -> str:
    """Célula como texto. Número inteiro vindo como 99019.0 vira '99019'."""
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    if isinstance(valor, datetime):
        valor = valor.date()
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    return limpar_texto(str(valor)).strip()


def inteiro(valor: Any) -> int | None:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int | float):
        return int(valor)
    return int(float(str(valor).strip().replace(",", ".")))  # o mesmo da carga do sistema antigo


def data(valor: Any) -> date | None:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(str(valor).strip()[:10], formato).date()
        except ValueError:
            pass
    raise ValueError(str(valor))


def linha_de_celulas(celulas: tuple, avisos: list[str]) -> LinhaOP | None:
    """Uma linha da aba Dados (A..L). None se não tem OP."""

    def col(i: int) -> Any:
        return celulas[i] if i < len(celulas) else None

    op = texto(col(1))
    if not op:
        return None
    linha = LinhaOP(op=op)
    for i, (campo, rotulo) in enumerate(COLUNAS):
        if campo == "op":
            continue
        bruto = col(i)
        try:
            if campo in ("qt_lote", "qt_faturada"):
                valor: Any = inteiro(bruto)
            elif campo == "data_faturamento":
                valor = data(bruto)
            elif campo == "tipo":
                classificacao = texto(bruto).upper()
                valor = classificacao if classificacao in TIPOS_LOTE else None
                if classificacao and valor is None:
                    avisos.append(f"OP {op}: classificação {classificacao!r} não é PIN, BOX nem ARK (fica sem tipo)")
            else:
                valor = texto(bruto)
        except ValueError:
            avisos.append(f"OP {op}: {rotulo} {texto(bruto)!r} não foi reconhecido (fica vazio)")
            valor = None
        if isinstance(valor, str) and campo in TAMANHOS and len(valor) > TAMANHOS[campo]:
            avisos.append(f"OP {op}: {rotulo} muito longo, cortado em {TAMANHOS[campo]} caracteres")
            valor = valor[: TAMANHOS[campo]]
        setattr(linha, campo, valor)
    if len(op) > TAMANHOS["op"]:
        avisos.append(f"OP {op[:30]}: número da OP muito longo (linha ignorada)")
        return None
    return linha


def ler_planilha(conteudo: bytes) -> tuple[dict[str, LinhaOP], list[str]]:
    """{OP: linha} da aba Dados e os avisos de leitura. OP repetida: fica a última linha (igual ao antigo)."""
    import openpyxl
    from openpyxl.utils.exceptions import InvalidFileException

    try:
        livro = openpyxl.load_workbook(io.BytesIO(conteudo), data_only=True, read_only=True)
    except (InvalidFileException, KeyError, OSError, ValueError) as erro:
        raise ErroPlanilha("Não foi possível abrir a planilha. Confira se é um arquivo .xlsx do Excel.") from erro
    try:
        if ABA not in livro.sheetnames:
            raise ErroPlanilha(f"A planilha não tem a aba '{ABA}'. Use o mesmo formato do cadastro (aba '{ABA}', colunas A a L).")
        linhas: dict[str, LinhaOP] = {}
        avisos: list[str] = []
        for celulas in livro[ABA].iter_rows(min_row=2, values_only=True):
            linha = linha_de_celulas(celulas or (), avisos)
            if linha is None:
                continue
            if linha.op in linhas:
                avisos.append(f"OP {linha.op} aparece mais de uma vez na planilha: vale a última linha")
            linhas[linha.op] = linha
        return linhas, avisos
    finally:
        livro.close()


# ---------------------------------------------------------------- comparação e inclusão


def _mostrar(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    return str(valor)


def resumo(linha: LinhaOP) -> dict:
    return {"op": linha.op, "cliente": linha.cliente, "coditem": linha.coditem, "descricao": linha.descricao,
            "tipo": linha.tipo, "qt_lote": linha.qt_lote, "projeto": linha.projeto}  # fmt: skip


def comparar(db: Session, linhas: dict[str, LinhaOP]) -> dict:
    """OPs novas (vão entrar), alteradas e que não vieram (só aviso)."""
    atuais = {o.op: o for o in db.scalars(select(OrdemProducao))}
    novas = sorted(set(linhas) - set(atuais))
    alteradas = []
    for op in sorted(set(linhas) & set(atuais)):
        nova, atual = linhas[op], atuais[op]
        mudou = {
            ROTULO[campo]: [_mostrar(getattr(atual, campo)), _mostrar(getattr(nova, campo))]
            for campo in CAMPOS_COMPARADOS
            if getattr(atual, campo) != getattr(nova, campo) and _mostrar(getattr(atual, campo)) != _mostrar(getattr(nova, campo))
        }
        if mudou:
            alteradas.append({"op": op, "diferencas": mudou})
    ausentes = sorted(set(atuais) - set(linhas))
    return {
        "novas": [resumo(linhas[op]) for op in novas],
        "alteradas": alteradas,
        "ausentes": ausentes,
        "iguais": len(set(linhas) & set(atuais)) - len(alteradas),
    }


def incluir_novas(db: Session, linhas: dict[str, LinhaOP], confirmadas: set[str]) -> list[OrdemProducao]:
    """Grava (flush, sem commit) só as OPs que ainda não existem E que o usuário confirmou."""
    existentes = set(db.scalars(select(OrdemProducao.op)))
    novas = [OrdemProducao(**linhas[op].valores(), origem="planilha")
             for op in sorted(confirmadas) if op in linhas and op not in existentes]  # fmt: skip
    db.add_all(novas)
    db.flush()
    return novas
