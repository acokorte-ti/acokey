"""Cadastros: equipamentos, prestadores, fornecedores de MP, ordens de produção, parâmetros e assinaturas.

No sistema antigo os quatro primeiros eram planilhas Excel lidas a cada acesso (legado/app.py: equipamentos_pagina,
prestadores_pagina, fornecedores_mp_pagina e a atualização da planilha de OPs). Agora são tabelas. Regras que mudaram:
- Nada é excluído: equipamento, prestador e fornecedor saem de uso com "inativar" (e podem ser reativados).
- Toda gravação vai para a auditoria (o antigo fazia uma cópia de segurança da planilha a cada gravação).
- Equipamentos: Qualidade ou Cadastros consultam; só Cadastros grava. Prestadores, fornecedores e OPs: Cadastros.
  As listas curtas para os seletores das outras telas (`/opcoes`) podem ser lidas por qualquer usuário logado.
- Parâmetros e assinatura digital dos usuários: só o administrador.
"""
import io
import json
import re
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import parametros
from app.api_auth import _usuario as usuario_para_tela
from app.arquivos import IMAGENS, PLANILHAS, conferir_conteudo, resposta_arquivo, salvar_bytes, salvar_upload
from app.config import agora_local
from app.db import get_db
from app.models import TIPOS_LOTE, Equipamento, FornecedorMP, Lote, OrdemProducao, Parametro, Prestador, Usuario
from app.ordens_producao import COLUNAS, ErroPlanilha, comparar, incluir_novas, ler_planilha
from app.seguranca import ADMIN, QUALQUER, Contexto, auditar, celula_segura, diferencas, exigir, limpar_texto

rota = APIRouter()

CADASTROS = exigir("cadastros")
VER_EQUIPAMENTOS = exigir("qualidade", "cadastros")

# Lista fechada de tipos de serviço (legado/app.py: TIPOS_PRESTADOR). Os seletores das etapas filtram por este rótulo.
TIPOS_PRESTADOR = (
    "TT externo",
    "Revestimento fosfato",
    "Revestimento oxidação negra",
    "Lab mecânico (tração/Charpy)",
    "NDT - líquido penetrante",
    "Calibração equipamentos",
    "Calibração fornos",
    "Outro",
)
# Sugestões do campo "Materiais fornecidos" (legado/app.py: MATERIAIS_MP)
MATERIAIS_MP = ("SC4330 (ASTM A958)", "H11 Modified", "TENAX300IM", "Outros")
# Etapa do lote -> tipos de prestador que aparecem para escolher nela (legado/app.py: prestadores_para_etapa).
# "*" vale para qualquer tipo de chaveta. Na Receb. MP a escolha é de fornecedor de MP (/fornecedores-mp/opcoes).
PRESTADORES_POR_ETAPA: dict[str, dict[str, tuple[str, ...]]] = {
    "lab_ext": {"*": ("Lab mecânico (tração/Charpy)",)},
    "fosfato": {"ARK": ("Revestimento oxidação negra",), "*": ("Revestimento fosfato",)},
    "lp": {"*": ("NDT - líquido penetrante",)},
    "trat_termico": {"*": ("TT externo",)},
}
AVISO_VENCIMENTO_DIAS = 30  # o painel do sistema antigo avisava 30 dias antes


def _colunas(obj) -> dict:
    return {c.key: getattr(obj, c.key) for c in inspect(type(obj)).columns}


def _limpo(dados: BaseModel) -> dict:
    return {k: limpar_texto(v).strip() if isinstance(v, str) else v for k, v in dados.model_dump().items()}


def _gravar(db: Session, mensagem_duplicado: str) -> None:
    """Manda ao banco e troca a violação de chave única por uma frase clara."""
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, mensagem_duplicado) from None


def _codigo_em_uso(db: Session, modelo, codigo: str, exceto: int | None) -> bool:
    consulta = select(modelo.id).where(func.lower(modelo.codigo) == codigo.lower())
    if exceto:
        consulta = consulta.where(modelo.id != exceto)
    return db.scalar(consulta) is not None


# ---------------------------------------------------------------- cadastros simples (equipamentos, prestadores, fornecedores)


class EquipamentoEntrada(BaseModel):
    codigo: str = Field(max_length=30)
    descricao: str = Field(max_length=200)
    setor: str = Field("", max_length=80)
    marca: str = Field("", max_length=80)
    data_calibracao: date | None = None
    validade_calibracao: date | None = None
    certificado: str = Field("", max_length=80)
    empresa_calibracao: str = Field("", max_length=160)


class PrestadorEntrada(BaseModel):
    codigo: str = Field(max_length=30)
    razao_social: str = Field(max_length=160)
    tipo_servico: str = Field(max_length=60)
    contato: str = Field("", max_length=200)
    observacoes: str = Field("", max_length=2000)


class FornecedorEntrada(BaseModel):
    codigo: str = Field(max_length=30)
    razao_social: str = Field(max_length=160)
    materiais: str = Field("", max_length=200)
    contato: str = Field("", max_length=200)
    observacoes: str = Field("", max_length=2000)


def _ajustar_equipamento(valores: dict, _atual) -> None:
    if not valores["codigo"] or not valores["descricao"]:
        raise HTTPException(422, "Informe pelo menos o código e a descrição do equipamento.")
    feita, validade = valores["data_calibracao"], valores["validade_calibracao"]
    if feita and validade and validade < feita:
        raise HTTPException(422, "A validade da calibração não pode ser antes da data da calibração.")


def _ajustar_prestador(valores: dict, atual: Prestador | None) -> None:
    valores["codigo"] = valores["codigo"].upper()
    if not valores["codigo"] or not valores["razao_social"]:
        raise HTTPException(422, "Informe o código e a razão social do prestador.")
    # Tipo fora da lista só passa se já estava gravado assim (planilha antiga) e não foi mexido
    if valores["tipo_servico"] not in TIPOS_PRESTADOR and not (atual and atual.tipo_servico == valores["tipo_servico"]):
        raise HTTPException(422, "Escolha o tipo de serviço na lista.")


def _ajustar_fornecedor(valores: dict, _atual) -> None:
    valores["codigo"] = valores["codigo"].upper()
    if not valores["codigo"] or not valores["razao_social"]:
        raise HTTPException(422, "Informe o código e a razão social do fornecedor.")


def _saida_equipamento(e: Equipamento) -> dict:
    hoje = agora_local().date()
    dias = (e.validade_calibracao - hoje).days if e.validade_calibracao else None
    return {**_colunas(e), "vencido": dias is not None and dias < 0, "dias_para_vencer": dias,
            "vence_logo": dias is not None and 0 <= dias <= AVISO_VENCIMENTO_DIAS}  # fmt: skip


def _registrar_cadastro(caminho: str, modelo, entrada, entidade: str, nome: str, ver, ajustar, saida=_colunas) -> None:
    """Rotas de um cadastro simples: GET lista, POST novo, PUT alterar, POST inativar / reativar."""

    @rota.get(caminho, name=f"listar_{entidade}")
    def listar(_: Contexto = Depends(ver), db: Session = Depends(get_db)) -> list[dict]:
        return [saida(o) for o in db.scalars(select(modelo).order_by(modelo.codigo))]

    @rota.post(caminho, status_code=201, name=f"criar_{entidade}")
    def criar(dados: entrada, ctx: Contexto = Depends(CADASTROS), db: Session = Depends(get_db)) -> dict:
        valores = _limpo(dados)
        ajustar(valores, None)
        if _codigo_em_uso(db, modelo, valores["codigo"], None):
            raise HTTPException(409, f"Já existe um {nome} com o código {valores['codigo']}.")
        obj = modelo(**valores, ativo=True)
        db.add(obj)
        _gravar(db, f"Já existe um {nome} com o código {valores['codigo']}.")
        auditar(db, ctx, "CRIAR", entidade, obj.id, valores)
        db.commit()
        return saida(obj)

    @rota.put(caminho + "/{item_id}", name=f"alterar_{entidade}")
    def alterar(item_id: int, dados: entrada, ctx: Contexto = Depends(CADASTROS), db: Session = Depends(get_db)) -> dict:
        obj = db.get(modelo, item_id)
        if not obj:
            raise HTTPException(404, "Cadastro não encontrado.")
        valores = _limpo(dados)
        ajustar(valores, obj)
        if _codigo_em_uso(db, modelo, valores["codigo"], obj.id):
            raise HTTPException(409, f"Já existe outro {nome} com o código {valores['codigo']}.")
        mudou = diferencas(_colunas(obj), valores)
        for campo, valor in valores.items():
            setattr(obj, campo, valor)
        _gravar(db, f"Já existe outro {nome} com o código {valores['codigo']}.")
        if mudou:
            auditar(db, ctx, "ALTERAR", entidade, obj.id, {"codigo": obj.codigo, **mudou})
        db.commit()
        return saida(obj)

    def _situacao(item_id: int, ativo: bool, ctx: Contexto, db: Session) -> dict:
        obj = db.get(modelo, item_id)
        if not obj:
            raise HTTPException(404, "Cadastro não encontrado.")
        if obj.ativo != ativo:
            auditar(db, ctx, "ALTERAR", entidade, obj.id, {"codigo": obj.codigo, "ativo": [obj.ativo, ativo]})
            obj.ativo = ativo
            db.commit()
        return saida(obj)

    @rota.post(caminho + "/{item_id}/inativar", name=f"inativar_{entidade}")
    def inativar(item_id: int, ctx: Contexto = Depends(CADASTROS), db: Session = Depends(get_db)) -> dict:
        return _situacao(item_id, False, ctx, db)

    @rota.post(caminho + "/{item_id}/reativar", name=f"reativar_{entidade}")
    def reativar(item_id: int, ctx: Contexto = Depends(CADASTROS), db: Session = Depends(get_db)) -> dict:
        return _situacao(item_id, True, ctx, db)


# As listas para os seletores vêm antes das rotas com {item_id}
@rota.get("/equipamentos/opcoes")
def opcoes_equipamentos(_: Contexto = Depends(QUALQUER), db: Session = Depends(get_db)) -> list[dict]:
    """Equipamentos ativos (durômetro, fornos...) para os relatórios das etapas."""
    return [_saida_equipamento(e) for e in db.scalars(select(Equipamento).where(Equipamento.ativo).order_by(Equipamento.codigo))]


@rota.get("/prestadores/opcoes")
def opcoes_prestadores(
    etapa: str | None = None,
    tipo_lote: str | None = None,
    tipo_servico: str | None = None,
    _: Contexto = Depends(QUALQUER),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Prestadores ativos. Com `etapa` (e `tipo_lote`), só os que atendem aquela etapa; com `tipo_servico`, só desse tipo."""
    consulta = select(Prestador).where(Prestador.ativo).order_by(Prestador.codigo)
    if etapa:
        por_tipo = PRESTADORES_POR_ETAPA.get(etapa)
        if not por_tipo:
            return []
        tipos = por_tipo.get((tipo_lote or "").upper()) or por_tipo["*"]
        consulta = consulta.where(Prestador.tipo_servico.in_(tipos))
    if tipo_servico:
        consulta = consulta.where(Prestador.tipo_servico == tipo_servico)
    return [
        {"id": p.id, "codigo": p.codigo, "razao_social": p.razao_social, "tipo_servico": p.tipo_servico, "contato": p.contato}
        for p in db.scalars(consulta)
    ]


@rota.get("/fornecedores-mp/opcoes")
def opcoes_fornecedores(_: Contexto = Depends(QUALQUER), db: Session = Depends(get_db)) -> list[dict]:
    consulta = select(FornecedorMP).where(FornecedorMP.ativo).order_by(FornecedorMP.codigo)
    return [{"id": f.id, "codigo": f.codigo, "razao_social": f.razao_social, "materiais": f.materiais} for f in db.scalars(consulta)]


@rota.get("/cadastros/listas")
def listas(_: Contexto = Depends(QUALQUER)) -> dict:
    """Listas fixas usadas nos formulários."""
    return {"tipos_prestador": list(TIPOS_PRESTADOR), "materiais_mp": list(MATERIAIS_MP)}


_registrar_cadastro("/equipamentos", Equipamento, EquipamentoEntrada, "equipamento", "equipamento",
                    VER_EQUIPAMENTOS, _ajustar_equipamento, _saida_equipamento)  # fmt: skip
_registrar_cadastro("/prestadores", Prestador, PrestadorEntrada, "prestador", "prestador", CADASTROS, _ajustar_prestador)
_registrar_cadastro("/fornecedores-mp", FornecedorMP, FornecedorEntrada, "fornecedor_mp", "fornecedor", CADASTROS,
                    _ajustar_fornecedor)  # fmt: skip


# ---------------------------------------------------------------- ordens de produção (antiga planilha de OPs)


class OrdemEntrada(BaseModel):
    op: str = Field(max_length=20)
    cliente: str = Field("", max_length=160)
    coditem: str = Field("", max_length=40)
    descricao: str = Field("", max_length=300)
    tipo: str | None = Field(None, max_length=3)
    data_faturamento: date | None = None
    nf: str = Field("", max_length=40)
    piv: str = Field("", max_length=40)
    qt_lote: int | None = Field(None, ge=0, le=10_000_000)
    qt_faturada: int | None = Field(None, ge=0, le=10_000_000)
    projeto: str = Field("", max_length=120)
    po: str = Field("", max_length=60)


def _valores_op(dados: OrdemEntrada) -> dict:
    valores = _limpo(dados)
    if not valores["op"]:
        raise HTTPException(422, "Informe o número da OP.")
    tipo = (valores["tipo"] or "").upper()
    if tipo and tipo not in TIPOS_LOTE:
        raise HTTPException(422, "A classificação precisa ser PIN, BOX ou ARK (ou ficar em branco).")
    valores["tipo"] = tipo or None
    return valores


def _lotes_por_op(db: Session) -> dict[str, int]:
    consulta = select(Lote.op, func.count(Lote.id)).where(Lote.cancelado_em.is_(None)).group_by(Lote.op)
    return {op: n for op, n in db.execute(consulta)}


@rota.get("/ordens-producao")
def listar_ops(_: Contexto = Depends(CADASTROS), db: Session = Depends(get_db)) -> list[dict]:
    lotes = _lotes_por_op(db)
    return [{**_colunas(o), "lotes": lotes.get(o.op, 0)} for o in db.scalars(select(OrdemProducao).order_by(OrdemProducao.op.desc()))]


@rota.get("/ordens-producao/opcoes")
def opcoes_ops(tipo: str | None = None, _: Contexto = Depends(QUALQUER), db: Session = Depends(get_db)) -> list[dict]:
    """OPs para escolher em outras telas (novo lote, OF...): OP, item, descrição e quantidade do lote."""
    consulta = select(OrdemProducao).order_by(OrdemProducao.op.desc())
    if tipo:
        consulta = consulta.where(OrdemProducao.tipo == tipo.strip().upper())
    return [{k: getattr(o, k) for k in ("op", "cliente", "coditem", "descricao", "tipo", "qt_lote", "piv", "po", "projeto")}
            for o in db.scalars(consulta)]  # fmt: skip


@rota.post("/ordens-producao", status_code=201)
def criar_op(dados: OrdemEntrada, ctx: Contexto = Depends(CADASTROS), db: Session = Depends(get_db)) -> dict:
    valores = _valores_op(dados)
    if db.scalar(select(OrdemProducao.id).where(OrdemProducao.op == valores["op"])):
        raise HTTPException(409, f"A OP {valores['op']} já está cadastrada.")
    ordem = OrdemProducao(**valores)
    db.add(ordem)
    _gravar(db, f"A OP {valores['op']} já está cadastrada.")
    auditar(db, ctx, "CRIAR", "ordem_producao", ordem.id, valores)
    db.commit()
    return {**_colunas(ordem), "lotes": 0}


@rota.put("/ordens-producao/{ordem_id}")
def alterar_op(ordem_id: int, dados: OrdemEntrada, ctx: Contexto = Depends(CADASTROS), db: Session = Depends(get_db)) -> dict:
    ordem = db.get(OrdemProducao, ordem_id)
    if not ordem:
        raise HTTPException(404, "OP não encontrada.")
    valores = _valores_op(dados)
    lotes = _lotes_por_op(db).get(ordem.op, 0)
    if valores["op"] != ordem.op:
        if lotes:
            raise HTTPException(409, f"Já há {lotes} lote(s) com a OP {ordem.op}: o número da OP não pode mudar.")
        if db.scalar(select(OrdemProducao.id).where(OrdemProducao.op == valores["op"])):
            raise HTTPException(409, f"A OP {valores['op']} já está cadastrada.")
    mudou = diferencas(_colunas(ordem), valores)
    for campo, valor in valores.items():
        setattr(ordem, campo, valor)
    _gravar(db, f"A OP {valores['op']} já está cadastrada.")
    if mudou:
        auditar(db, ctx, "ALTERAR", "ordem_producao", ordem.id, {"op": ordem.op, **mudou})
    db.commit()
    return {**_colunas(ordem), "lotes": _lotes_por_op(db).get(ordem.op, 0)}


@rota.get("/ordens-producao/exportar")
def exportar_ops(_: Contexto = Depends(CADASTROS), db: Session = Depends(get_db)) -> Response:
    """Planilha no mesmo formato da importação (aba Dados, colunas A a L)."""
    import openpyxl
    from openpyxl.styles import Font

    livro = openpyxl.Workbook()
    aba = livro.active
    aba.title = "Dados"
    aba.append([titulo for _, titulo in COLUNAS])
    for celula in aba[1]:
        celula.font = Font(bold=True)
    for ordem in db.scalars(select(OrdemProducao).order_by(OrdemProducao.op)):
        aba.append([celula_segura(getattr(ordem, campo)) for campo, _ in COLUNAS])
        aba.cell(row=aba.max_row, column=6).number_format = "DD/MM/YYYY"
    for coluna, largura in zip("ABCDEFGHIJKL", (28, 10, 12, 50, 14, 12, 10, 12, 10, 12, 20, 16), strict=True):
        aba.column_dimensions[coluna].width = largura
    aba.freeze_panes = "A2"
    saida = io.BytesIO()
    livro.save(saida)
    nome = f"Ordens_de_Producao_{agora_local():%Y%m%d}.xlsx"
    return Response(
        saida.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


LIMITE_PLANILHA_MB = 10


def _ler_xlsx(arquivo: UploadFile) -> tuple[bytes, str]:
    nome = (arquivo.filename or "").strip() or "planilha.xlsx"
    if not nome.lower().endswith(tuple(PLANILHAS)):
        raise HTTPException(422, "Envie a planilha no formato .xlsx do Excel.")
    conteudo = arquivo.file.read(LIMITE_PLANILHA_MB * 1024 * 1024 + 1)
    if len(conteudo) > LIMITE_PLANILHA_MB * 1024 * 1024:
        raise HTTPException(413, f"A planilha passa do limite de {LIMITE_PLANILHA_MB} MB.")
    if not conteudo or not conferir_conteudo(conteudo[:16], ".xlsx"):
        raise HTTPException(422, "O arquivo enviado não é uma planilha .xlsx válida.")
    return conteudo, nome


def _planilha(conteudo: bytes):
    try:
        return ler_planilha(conteudo)
    except ErroPlanilha as erro:
        raise HTTPException(422, str(erro)) from None


@rota.post("/ordens-producao/importacao/comparar")
def comparar_planilha(arquivo: UploadFile = File(...), _: Contexto = Depends(CADASTROS), db: Session = Depends(get_db)) -> dict:
    """Mostra o que a planilha nova traz de diferente. Não grava nada."""
    conteudo, nome = _ler_xlsx(arquivo)
    linhas, avisos = _planilha(conteudo)
    if not linhas:
        raise HTTPException(422, "Nenhuma OP encontrada na aba 'Dados' (a OP fica na coluna B, a partir da linha 2).")
    return {"arquivo": nome, "total_planilha": len(linhas), "avisos": avisos, **comparar(db, linhas)}


@rota.post("/ordens-producao/importacao/aplicar")
def aplicar_planilha(
    arquivo: UploadFile = File(...),
    ops: str = Form(...),
    ctx: Contexto = Depends(CADASTROS),
    db: Session = Depends(get_db),
) -> dict:
    """Inclui SÓ as OPs novas que o usuário confirmou na comparação. Alteradas e ausentes não são tocadas."""
    try:
        confirmadas = {str(op).strip() for op in json.loads(ops) if str(op).strip()}
    except (ValueError, TypeError):
        raise HTTPException(422, "Lista de OPs inválida. Compare a planilha de novo.") from None
    if not confirmadas:
        raise HTTPException(422, "Nenhuma OP nova foi confirmada.")
    conteudo, nome = _ler_xlsx(arquivo)
    linhas, _avisos = _planilha(conteudo)
    incluidas = incluir_novas(db, linhas, confirmadas)
    if not incluidas:
        raise HTTPException(409, "Nenhuma das OPs confirmadas é nova (alguém pode ter incluído antes). Compare a planilha de novo.")
    guardada = salvar_bytes(conteudo, "ordens_producao/importacoes", nome)
    resultado = comparar(db, linhas)
    auditar(db, ctx, "IMPORTAR", "ordem_producao", None,
            {"arquivo": nome, "guardado_em": guardada, "incluidas": [o.op for o in incluidas],
             "alteradas_nao_aplicadas": len(resultado["alteradas"]), "ausentes_na_planilha": len(resultado["ausentes"])})  # fmt: skip
    db.commit()
    return {"incluidas": [o.op for o in incluidas], "mensagem": f"{len(incluidas)} OP(s) nova(s) incluída(s) no cadastro."}


# ---------------------------------------------------------------- parâmetros (administrador)

_CHAVE = re.compile(r"^[a-z][a-z0-9_]{1,59}$")


class ValorParametro(BaseModel):
    valor: str = Field(max_length=2000)


def _parametro(db: Session, chave: str) -> dict:
    linha = db.get(Parametro, chave)
    padrao, descricao = parametros.PADROES.get(chave, ("", ""))
    return {
        "chave": chave,
        "valor": linha.valor if linha else "",
        "padrao": padrao,
        "descricao": descricao,
        "conhecido": chave in parametros.PADROES,
        "em_uso": parametros.ler(db, chave),
        "alterado_em": linha.alterado_em if linha else None,
        "alterado_por": linha.alterado_por if linha else "",
    }


@rota.get("/parametros")
def listar_parametros(_: Contexto = Depends(ADMIN), db: Session = Depends(get_db)) -> list[dict]:
    gravadas = sorted(set(db.scalars(select(Parametro.chave))) - set(parametros.PADROES))
    return [_parametro(db, chave) for chave in [*parametros.PADROES, *gravadas]]


def _validar_parametro(chave: str, valor: str) -> None:
    if chave == "laser_formato" and valor:
        try:
            valor.format(ano="2026", tri="4", corrida="M999", lote="900001", seq=1)  # como as etapas aplicam
        except (KeyError, IndexError, ValueError):
            raise HTTPException(
                422, "Formato do laser inválido. Use só {ano}, {tri}, {corrida}, {lote} e {seq} (ex.: {seq:03d})."
            ) from None
    if chave == "elementos_quimicos" and valor and any(not e.strip() for e in valor.split(",")):
        raise HTTPException(422, "Separe os elementos por vírgula, sem itens vazios (ex.: C,Mn,Si).")


@rota.put("/parametros/{chave}")
def gravar_parametro(chave: str, dados: ValorParametro, ctx: Contexto = Depends(ADMIN), db: Session = Depends(get_db)) -> dict:
    if not _CHAVE.match(chave):
        raise HTTPException(422, "Nome de parâmetro inválido: use letras minúsculas, números e sublinhado (ex.: cliente_nome).")
    valor = limpar_texto(dados.valor).strip()
    _validar_parametro(chave, valor)
    atual = db.get(Parametro, chave)
    if (atual.valor if atual else "") != valor:  # sem mudança, nem a data de alteração muda
        antes, depois = parametros.gravar(db, chave, valor, ctx.usuario.login)
        auditar(db, ctx, "ALTERAR", "parametro", chave, {"valor": [antes, depois]})
        db.commit()
    return _parametro(db, chave)


# ---------------------------------------------------------------- assinatura digital dos usuários

LIMITE_ASSINATURA_MB = 5


def _usuario_ou_404(db: Session, usuario_id: int) -> Usuario:
    usuario = db.get(Usuario, usuario_id)
    if not usuario:
        raise HTTPException(404, "Usuário não encontrado.")
    return usuario


@rota.post("/usuarios/{usuario_id}/assinatura")
def gravar_assinatura(
    usuario_id: int, arquivo: UploadFile = File(...), ctx: Contexto = Depends(ADMIN), db: Session = Depends(get_db)
) -> dict:
    """PNG ou JPG da assinatura (vai nos relatórios e no carimbo APROVADO). A imagem anterior fica guardada."""
    from PIL import Image, UnidentifiedImageError

    usuario = _usuario_ou_404(db, usuario_id)
    conteudo = arquivo.file.read(LIMITE_ASSINATURA_MB * 1024 * 1024 + 1)
    if len(conteudo) > LIMITE_ASSINATURA_MB * 1024 * 1024:
        raise HTTPException(413, f"A imagem da assinatura passa do limite de {LIMITE_ASSINATURA_MB} MB.")
    try:
        with Image.open(io.BytesIO(conteudo)) as imagem:
            imagem.verify()  # confere que é mesmo uma imagem inteira, não só o começo
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise HTTPException(422, "A assinatura precisa ser uma imagem PNG ou JPG.") from None
    arquivo.file.seek(0)
    relativo, _original = salvar_upload(arquivo, "assinaturas", IMAGENS, LIMITE_ASSINATURA_MB)
    antes = usuario.assinatura_arquivo
    usuario.assinatura_arquivo = relativo
    auditar(db, ctx, "ALTERAR", "usuario", usuario.id, {"login": usuario.login, "assinatura": [antes, relativo]})
    db.commit()
    return usuario_para_tela(usuario)


@rota.delete("/usuarios/{usuario_id}/assinatura")
def tirar_assinatura(usuario_id: int, ctx: Contexto = Depends(ADMIN), db: Session = Depends(get_db)) -> dict:
    """Desliga a assinatura do usuário. O arquivo continua guardado (nada é apagado)."""
    usuario = _usuario_ou_404(db, usuario_id)
    if usuario.assinatura_arquivo:
        auditar(db, ctx, "ALTERAR", "usuario", usuario.id, {"login": usuario.login, "assinatura": [usuario.assinatura_arquivo, None]})
        usuario.assinatura_arquivo = None
        db.commit()
    return usuario_para_tela(usuario)


@rota.get("/usuarios/{usuario_id}/assinatura")
def ver_assinatura(usuario_id: int, ctx: Contexto = Depends(QUALQUER), db: Session = Depends(get_db)) -> FileResponse:
    if not (ctx.usuario.admin or ctx.usuario.pode_aprovar or ctx.usuario.id == usuario_id):
        raise HTTPException(403, "Só o administrador e quem pode aprovar veem as assinaturas.")
    usuario = _usuario_ou_404(db, usuario_id)
    if not usuario.assinatura_arquivo:
        raise HTTPException(404, "Este usuário não tem assinatura cadastrada.")
    return resposta_arquivo(usuario.assinatura_arquivo, f"assinatura_{usuario.login}{_extensao(usuario.assinatura_arquivo)}")


def _extensao(caminho: str) -> str:
    achado = re.search(r"\.[A-Za-z0-9]+$", caminho)
    return achado.group(0).lower() if achado else ""
