"""Databook: geração do PDF final, conferência e controle de envio ao cliente ("Enviado-DB").

Porte de legado/app.py: gerar_databook e baixar_databook (SECOES_DB), conferir_databook_lote e o controle de envio
(listar_databooks_a_enviar, databooks_pagina, databooks_enviar, databooks_desfazer, databooks_baixar...).

Onde ficam os PDFs, dentro da pasta de arquivos (mesmo layout que a carga traz do sistema antigo):
- lotes/<id>/databook/saida/Databook_DB-<lote>-<tipo>_Rev<n>.pdf   cada revisão gerada (nunca sobrescrita), com o
  Relatorio_Conferencia_DB-<lote>-<tipo>_Rev<n>.txt (alertas da montagem: checklist, arquivo que não abriu)
- databooks/LOTE-OP<op>-<tipo>/                                    cópia de cada revisão gerada ("a enviar")
- databooks/Enviados/                                              cópia do que foi marcado como Enviado-DB

"Enviado-DB" é o envio do DOCUMENTO ao cliente. Não é a saída física do lote (essa é a Ordem de Faturamento).
O antigo MOVIA o PDF para Enviados e APAGAVA a linha ao desfazer. Aqui nada é apagado: o envio COPIA o PDF para
Enviados e desfazer só marca a linha (desfeito_em/por/motivo); o PDF original continua na pasta da OP.

Funções para outros módulos: `ops_com_databook_enviado`, `databook_enviado` (bloqueio do cancelamento de lote),
`databooks_pendentes` (alerta do painel: gerado há 3+ dias e não enviado), `concluidos_sem_databook`.
"""
import re
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import fluxo, parametros
from app.api_recursos import listar_desenhos
from app.arquivos import DOCUMENTOS, caminho_seguro, nome_seguro, resposta_arquivo
from app.conferencia_databook import conferir_databook
from app.config import FUSO, agora_local, config
from app.databook_pdf import Capa, Documento, Secao, SemDocumentos, limpar_titulo, montar
from app.db import get_db
from app.estado import estado_lotes
from app.historico import registrar_evento
from app.lotes import buscar_lote
from app.models import TIPOS_LOTE, Anexo, DatabookEnviado, Lote, OrdemProducao, Usuario
from app.pdf_comum import LOGO, caminho_assinatura
from app.seguranca import QUALIDADE, Contexto, auditar, limpar_texto

rota = APIRouter()

PASTA_DEPOSITO = "databooks"
PASTA_ENVIADOS = "databooks/Enviados"
RE_PASTA_OP = re.compile(r"^LOTE-OP(\d+)-(PIN|BOX|ARK)$", re.IGNORECASE)
RE_ARQUIVO = re.compile(r"^Databook_DB-(.+)-(PIN|BOX|ARK)_Rev(\d+)\.pdf$", re.IGNORECASE)

# Seções do databook, na ordem do índice: (nome da seção, palavra do checklist, [(etapa, sub)]).
# Os nomes saem no PDF como estão (o antigo usava o nome da pasta: "01_..." vira "Certificado Composicao Quimica").
SECOES_DB: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    ("01_Certificado_Composicao_Quimica", "composicao", (("receb_mp", ""),)),
    ("02_Relatorio_Tratamento_Termico", "termico", (("trat_termico", ""),)),
    ("03_Relatorio_Dureza_HRC", "dureza", (("dureza", ""),)),
    ("04_Ensaio_de_Tracao", "tracao", (("lab_ext", "tracao"),)),
    ("05_Ensaio_de_Impacto_Charpy", "charpy", (("lab_ext", "charpy"),)),
    ("06_Relatorio_Dimensional", "dimensional", (("usinagem", ""), ("dim_final", ""))),
    ("07_Ensaio_Liquido_Penetrante", "penetrante", (("lp", ""),)),
    ("08_Certificado_Fosfato_de_Manganes", "fosfato", (("fosfato", ""),)),
    ("09_Inspecao_Visual_e_Marcacao_Laser", "visual", (("visual", ""),)),
)  # fmt: skip
# ARK é revestido com oxidação negra (fluxo.py muda o nome da etapa); a seção acompanha
SECOES_POR_TIPO = {("ARK", "08_Certificado_Fosfato_de_Manganes"): ("08_Certificado_Oxidacao_Negra", "oxidacao")}


# ----------------------------------------------------------------- nomes e pastas


def _seguro(texto: str) -> str:
    return re.sub(r"[^\w\-]+", "_", texto)


def nome_base(numero: str, tipo: str, revisao: int) -> str:
    """'DB-26-4-900001-PIN_Rev0': o mesmo nome que o sistema antigo dava (Databook_<isto>.pdf)."""
    return _seguro(f"DB-{numero}-{tipo}_Rev{revisao}")


def pasta_saida(lote_id: int) -> str:
    return f"lotes/{lote_id}/databook/saida"


def pasta_op(op: str, tipo: str) -> str:
    """'databooks/LOTE-OP900001-PIN' (a antiga pasta de depósito DATABOOK\\LOTE-OP...)."""
    return f"{PASTA_DEPOSITO}/LOTE-OP{re.sub(r'[^\w\-]', '_', op.strip())}-{re.sub(r'[^\w\-]', '_', tipo.strip())}"


def _absoluto(relativo: str) -> Path:
    return config().pasta_arquivos / relativo


def _quando(caminho: Path) -> datetime:
    return datetime.fromtimestamp(caminho.stat().st_mtime, FUSO).replace(tzinfo=None, microsecond=0)


def _gravar_novo(relativo: str, conteudo: bytes) -> bool:
    """Grava sem nunca sobrescrever. False se já existe um arquivo com esse nome."""
    destino = _absoluto(relativo)
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(destino, "xb") as arquivo:
            arquivo.write(conteudo)
    except FileExistsError:
        return False
    return True


# ----------------------------------------------------------------- revisões geradas de um lote


def revisoes_do_lote(lote_id: int) -> list[dict]:
    """Databooks gerados do lote, do mais antigo para o mais novo (o último é o que vale, como no antigo)."""
    pasta = _absoluto(pasta_saida(lote_id))
    saida = []
    for arquivo in pasta.glob("Databook_*.pdf") if pasta.is_dir() else []:
        achado = RE_ARQUIVO.match(arquivo.name)
        saida.append({
            "arquivo": arquivo.name,
            "relativo": f"{pasta_saida(lote_id)}/{arquivo.name}",
            "revisao": int(achado.group(3)) if achado else None,
            "gerado_em": _quando(arquivo),
            "tamanho_kb": max(1, round(arquivo.stat().st_size / 1024)),
        })  # fmt: skip
    saida.sort(key=lambda r: (r["gerado_em"], -1 if r["revisao"] is None else r["revisao"], r["arquivo"]))
    return saida


def _revisao_escolhida(lote: Lote, arquivo: str = "") -> dict:
    """A revisão pedida (pelo nome do arquivo) ou a mais recente do lote."""
    revisoes = revisoes_do_lote(lote.id)
    if arquivo:
        achada = next((r for r in revisoes if r["arquivo"] == arquivo), None)
        relativo = f"{pasta_op(lote.op, lote.tipo)}/{arquivo}"
        if not achada and RE_ARQUIVO.match(arquivo) and Path(arquivo).name == arquivo and caminho_seguro(relativo):
            # só na pasta da OP (ex.: databook trazido do sistema antigo sem a cópia na pasta do lote)
            caminho = _absoluto(relativo)
            achada = {"arquivo": arquivo, "relativo": relativo, "revisao": int(RE_ARQUIVO.match(arquivo).group(3)),
                      "gerado_em": _quando(caminho), "tamanho_kb": max(1, round(caminho.stat().st_size / 1024))}  # fmt: skip
        if not achada:
            raise HTTPException(404, "Esta revisão do databook não foi encontrada.")
        return achada
    if not revisoes:
        raise HTTPException(404, "Este lote ainda não tem databook gerado.")
    return revisoes[-1]


def alertas_da_revisao(lote_id: int, arquivo: str) -> list[str]:
    """Alertas gravados na geração (parte "ALERTAS" do Relatorio_Conferencia_*.txt). Vazio = nenhum."""
    pasta = _absoluto(pasta_saida(lote_id))
    txt = pasta / f"Relatorio_Conferencia_{Path(arquivo).stem.removeprefix('Databook_')}.txt"
    if not txt.is_file():  # databook antigo com outro nome: o relatório mais recente (como o antigo fazia)
        candidatos = sorted(pasta.glob("Relatorio_Conferencia_*.txt"), key=lambda p: p.stat().st_mtime) if pasta.is_dir() else []
        if not candidatos:
            return []
        txt = candidatos[-1]
    try:
        trecho = txt.read_text(encoding="utf-8").split("ALERTAS")[-1]
    except (OSError, UnicodeDecodeError):
        return []
    linhas = [linha.strip() for linha in trecho.splitlines() if linha.strip()]
    return [] if linhas == ["Nenhum."] else linhas


def proxima_revisao(lote: Lote) -> int:
    """Uma a mais que a maior revisão já gerada do lote (na pasta dele ou na pasta da OP): nunca sobrescreve."""
    revisoes = [r["revisao"] for r in revisoes_do_lote(lote.id)]
    contagem = len(revisoes)  # o antigo numerava pela quantidade de arquivos
    revisoes = [r for r in revisoes if r is not None]
    pasta = _absoluto(pasta_op(lote.op, lote.tipo))
    prefixo = nome_base(lote.numero, lote.tipo, 0).rsplit("_Rev", 1)[0].lower()
    for arquivo in pasta.glob("Databook_*.pdf") if pasta.is_dir() else []:
        achado = RE_ARQUIVO.match(arquivo.name)
        if achado and arquivo.name.lower().startswith(f"databook_{prefixo}_rev"):
            revisoes.append(int(achado.group(3)))
    return max([contagem, *(r + 1 for r in revisoes)])


# ----------------------------------------------------------------- conteúdo do databook


def _aplica(etapa: str, sub: str, tipo: str) -> bool:
    e = fluxo.POR_CHAVE[etapa]
    return e.aplicavel(tipo) and (sub == "" or sub in e.subs_de(tipo))


def secoes_do_lote(db: Session, lote: Lote) -> tuple[list[Secao], list[str]]:
    """Seções com os documentos anexados nas etapas, na ordem do índice, e o checklist do tipo.

    Regras do antigo: só os documentos originais anexados (foto "só registro interno" e anexo removido não entram);
    anexo da etapa sem subdivisão também entra na seção da subdivisão (laudo único de tração + Charpy); dentro da
    seção, ordem alfabética do nome do arquivo e, com o mesmo nome, só o anexo mais recente (o antigo copiava todos
    para a mesma pasta e o último substituía o anterior). Seção de etapa que não se aplica ao tipo fica de fora.
    """
    anexos = list(db.scalars(
        select(Anexo)
        .where(Anexo.lote_id == lote.id, Anexo.apenas_registro.is_(False), Anexo.removido_em.is_(None))
        .order_by(Anexo.id)
    ))  # fmt: skip
    secoes: list[Secao] = []
    checklist: list[str] = []
    for pasta, palavra, itens in SECOES_DB:
        aplicaveis = [(e, s) for e, s in itens if _aplica(e, s, lote.tipo)]
        if not aplicaveis:
            continue
        pasta, palavra = SECOES_POR_TIPO.get((lote.tipo, pasta), (pasta, palavra))
        checklist.append(palavra)
        por_nome: dict[str, Documento] = {}
        for etapa, sub in aplicaveis:
            for a in anexos:
                if a.etapa != etapa or a.sub not in (sub, ""):
                    continue
                nome = nome_seguro(a.nome)
                if Path(nome).suffix.lower() not in DOCUMENTOS or nome.startswith((".", "~")):
                    continue
                por_nome[nome.lower()] = Documento(nome=nome, caminho=caminho_seguro(a.arquivo))
        if por_nome:
            secoes.append(Secao(limpar_titulo(pasta), [por_nome[k] for k in sorted(por_nome)]))
    return secoes, checklist


def _primeiro_nome(cliente: str) -> str:
    """'EXEMPLO INDUSTRIAL S.A.' -> 'Exemplo'."""
    partes = (cliente or "").strip().split()
    return partes[0].capitalize() if partes else ""


def _produto_sem_instr(descricao: str) -> str:
    """'INSTR. CONTROLE TRAVAMENTO ARK 18-24 ...' -> 'ARK 18-24 ...'. Sem o prefixo, a descrição inteira."""
    if not descricao:
        return ""
    achado = re.search(r"INSTR\.?\s*CONTROLE\s*TRAVAMENTO\s*(?:DES\s+)?", descricao, re.IGNORECASE)
    return descricao[achado.end():].strip() if achado else descricao.strip()


def sugerir_produto_nome(lote: Lote) -> str:
    """Palpite de nome do produto para ARK, pelo desenho do item: 'ANTI-ROTATIONAL KEY 18-24"'. PIN/BOX: vazio."""
    if lote.tipo != "ARK":
        return ""
    desenho = next((d for d in listar_desenhos() if d["coditem"] == lote.coditem), None) if lote.coditem else None
    achado = re.search(r"ARK\s*([\w/\-]+)", (desenho or {}).get("descricao", ""), re.IGNORECASE)
    if achado:
        medida = achado.group(1).replace("18-24", '18-24"').replace("32NF36", '32NF-36"')
        return f"ANTI-ROTATIONAL KEY {medida}"
    return "ANTI-ROTATIONAL KEY"


def dados_capa(db: Session, lote: Lote) -> dict:
    """Dados da capa que vêm do cadastro: cliente (primeiro nome), projeto, pedido (PO) e o produto sugerido."""
    op = db.scalar(select(OrdemProducao).where(OrdemProducao.op == lote.op))
    cliente = (
        _primeiro_nome(op.cliente if op else "")
        or parametros.ler(db, "cliente_nome_curto")
        or _primeiro_nome(parametros.ler(db, "cliente_nome"))
    )
    sugestoes = [s for s in (_produto_sem_instr(op.descricao if op else ""), sugerir_produto_nome(lote)) if s]
    return {
        "empresa": parametros.ler(db, "empresa_razao_social"),
        "cliente": cliente,
        "projeto": op.projeto if op else "",
        "pedido": op.po if op else "",
        "produto": sugestoes[0] if sugestoes else "",
        "produto_sugestoes": list(dict.fromkeys(sugestoes)),
        "lote": lote.numero,
        "qtd": lote.qtd,
        "numero_documento": f"DB-{lote.numero}",
        "op_cadastrada": op is not None,
    }


def lote_concluido(db: Session, lote: Lote) -> bool:
    estados, _ = estado_lotes(db, [lote.id])
    return fluxo.etapa_real(lote.tipo, estados.get(lote.id, {})) >= fluxo.CONCLUIDO


# ----------------------------------------------------------------- envios (Enviado-DB)


def envios_ativos(db: Session) -> list[DatabookEnviado]:
    return list(db.scalars(select(DatabookEnviado).where(DatabookEnviado.desfeito_em.is_(None))))


def ops_com_databook_enviado(db: Session) -> set[tuple[str, str]]:
    """(OP, TIPO) com databook enviado ao cliente (envio não desfeito). Para o painel e a coluna "Enviado-DB"."""
    return {(e.op.strip(), e.tipo.strip().upper()) for e in envios_ativos(db)}


def databook_enviado(db: Session, op: str, tipo: str) -> bool:
    """Se o databook desta OP/tipo já foi enviado ao cliente (bloqueia o cancelamento do lote)."""
    return (op.strip(), tipo.strip().upper()) in ops_com_databook_enviado(db)


def lotes_concluidos(db: Session) -> list[Lote]:
    lotes = list(db.scalars(select(Lote).where(Lote.cancelado_em.is_(None)).order_by(Lote.id)))
    estados, _ = estado_lotes(db, [lote.id for lote in lotes])
    return [lote for lote in lotes if fluxo.etapa_real(lote.tipo, estados.get(lote.id, {})) >= fluxo.CONCLUIDO]


def databooks_pendentes(db: Session, dias: int = 3, concluidos: Iterable[Lote] | None = None) -> list[dict]:
    """Lotes concluídos com databook gerado há `dias` ou mais e ainda não enviado (alerta do painel).

    `concluidos`: os lotes concluídos, se quem chama já os tiver (evita reler o estado de todos os lotes).
    """
    enviados = ops_com_databook_enviado(db)
    agora = agora_local()
    saida = []
    for lote in concluidos if concluidos is not None else lotes_concluidos(db):
        if (lote.op.strip(), lote.tipo.upper()) in enviados:
            continue
        revisoes = revisoes_do_lote(lote.id)
        if not revisoes:
            continue
        gerado = max(r["gerado_em"] for r in revisoes)
        idade = (agora - gerado).total_seconds() / 86400
        if idade >= dias:
            saida.append({"lote_id": lote.id, "numero": lote.numero, "op": lote.op, "tipo": lote.tipo,
                          "gerado_em": gerado, "dias": int(idade)})  # fmt: skip
    return saida


def concluidos_sem_databook(db: Session, concluidos: Iterable[Lote] | None = None) -> list[dict]:
    """Lotes concluídos que ainda não têm databook gerado (alerta "aguardando geração do databook")."""
    return [
        {"lote_id": lote.id, "numero": lote.numero, "op": lote.op, "tipo": lote.tipo}
        for lote in (concluidos if concluidos is not None else lotes_concluidos(db))
        if not revisoes_do_lote(lote.id)
    ]


def listar_a_enviar(db: Session) -> list[dict]:
    """Databooks das pastas databooks/LOTE-OP<op>-<tipo>/ ainda não enviados: só a revisão mais recente de cada lote.

    Igual ao antigo: se a maior revisão já foi enviada (ou outra igual ou mais nova), nada aparece, para revisões
    velhas não voltarem à lista. Diferença: o antigo olhava só a maior revisão da OP; aqui é de cada lote da OP
    (uma OP com dois lotes não esconde o databook do segundo).
    """
    base = _absoluto(PASTA_DEPOSITO)
    if not base.is_dir():
        return []
    ativos = envios_ativos(db)
    arquivos_enviados = {e.arquivo for e in ativos}
    maior_enviada: dict[tuple[str, str, str], int] = {}
    for e in ativos:
        chave = (e.op.strip(), e.tipo.strip().upper(), e.lote.strip().lower())
        maior_enviada[chave] = max(maior_enviada.get(chave, -1), e.revisao or 0)
    lotes = {lote.numero.strip().lower(): lote for lote in db.scalars(select(Lote))}
    agora = agora_local()
    saida = []
    for pasta in sorted(base.iterdir()):
        achado = RE_PASTA_OP.match(pasta.name)
        if not achado or not pasta.is_dir():
            continue
        op, tipo = achado.group(1), achado.group(2).upper()
        por_lote: dict[str, tuple[int, Path, str]] = {}
        for arquivo in pasta.iterdir():
            achado_arq = RE_ARQUIVO.match(arquivo.name)
            if not achado_arq or not arquivo.is_file():
                continue
            numero, revisao = achado_arq.group(1), int(achado_arq.group(3))
            if numero.lower() not in por_lote or revisao > por_lote[numero.lower()][0]:
                por_lote[numero.lower()] = (revisao, arquivo, numero)
        for chave, (revisao, arquivo, numero) in por_lote.items():
            if arquivo.name in arquivos_enviados or revisao <= maior_enviada.get((op, tipo, chave), -1):
                continue
            lote = lotes.get(chave)
            if lote and lote.cancelado_em:
                continue  # lote cancelado: o databook dele não vai para o cliente
            modificado = _quando(arquivo)
            saida.append({
                "op": op, "tipo": tipo, "lote": numero, "revisao": revisao, "arquivo": arquivo.name,
                "tamanho_mb": round(arquivo.stat().st_size / 1024 / 1024, 1), "modificado": modificado,
                "dias": (agora - modificado).days, "lote_id": lote.id if lote else None,
            })  # fmt: skip
    saida.sort(key=lambda d: (d["op"], d["tipo"], d["lote"]))
    return saida


def _envio(e: DatabookEnviado, lotes: dict[str, int]) -> dict:
    return {
        "id": e.id, "op": e.op, "tipo": e.tipo, "lote": e.lote, "revisao": e.revisao, "arquivo": e.arquivo,
        "data_envio": e.data_envio, "destinatario": e.destinatario, "nf_saida": e.nf_saida,
        "observacoes": e.observacoes, "enviado_em": e.enviado_em, "enviado_por": e.enviado_por,
        "desfeito_em": e.desfeito_em, "desfeito_por": e.desfeito_por, "desfeito_motivo": e.desfeito_motivo,
        "lote_id": lotes.get(e.lote.strip().lower()), "tem_arquivo": caminho_seguro(e.caminho) is not None,
    }  # fmt: skip


def _ids_dos_lotes(db: Session) -> dict[str, int]:
    return {numero.strip().lower(): id_ for id_, numero in db.execute(select(Lote.id, Lote.numero))}


def _lote_do_numero(db: Session, numero: str) -> Lote | None:
    return next((lote for lote in db.scalars(select(Lote).where(Lote.numero == numero.strip()))), None)


def _ordenar_envios(envios: list[DatabookEnviado]) -> list[DatabookEnviado]:
    return sorted(envios, key=lambda e: (e.data_envio or date.min, e.id), reverse=True)


# ----------------------------------------------------------------- rotas: controle de envio


@rota.get("/databooks")
def painel_databooks(
    tipo: str = "", incluir_desfeitos: bool = False, _: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)
) -> dict:
    """As duas abas: "A enviar" (revisão mais recente de cada lote) e "Enviados-DB" (histórico)."""
    tipo = tipo.strip().upper()
    if tipo not in TIPOS_LOTE:
        tipo = ""
    a_enviar = listar_a_enviar(db)
    consulta = select(DatabookEnviado)
    if not incluir_desfeitos:
        consulta = consulta.where(DatabookEnviado.desfeito_em.is_(None))
    enviados = _ordenar_envios(list(db.scalars(consulta)))
    # as contagens das abas são o total, sem o filtro de tipo (como no antigo)
    n_a_enviar, n_enviados = len(a_enviar), sum(1 for e in enviados if e.desfeito_em is None)
    if tipo:
        a_enviar = [d for d in a_enviar if d["tipo"] == tipo]
        enviados = [e for e in enviados if e.tipo.upper() == tipo]
    lotes = _ids_dos_lotes(db)
    return {
        "a_enviar": a_enviar,
        "enviados": [_envio(e, lotes) for e in enviados],
        "n_a_enviar": n_a_enviar,
        "n_enviados": n_enviados,
        "hoje": agora_local().date(),
    }


def _validar_nome(op: str, tipo: str, arquivo: str) -> tuple[str, str, str, re.Match]:
    """Só nomes no formato que o sistema gera, sem subpasta (nada de '../' vindo da tela)."""
    op, tipo, arquivo = (op or "").strip(), (tipo or "").strip().upper(), (arquivo or "").strip()
    achado = RE_ARQUIVO.match(arquivo)
    if not re.fullmatch(r"[\w\-]{1,20}", op) or tipo not in TIPOS_LOTE or Path(arquivo).name != arquivo or not achado:
        raise HTTPException(404, "Databook não encontrado.")
    return op, tipo, arquivo, achado


@rota.get("/databooks/arquivo")
def baixar_a_enviar(op: str, tipo: str, arquivo: str, _: Contexto = Depends(QUALIDADE)) -> FileResponse:
    """PDF ainda na pasta da OP (aba "A enviar")."""
    op, tipo, arquivo, _achado = _validar_nome(op, tipo, arquivo)
    return resposta_arquivo(f"{pasta_op(op, tipo)}/{arquivo}", arquivo)


class EnvioEntrada(BaseModel):
    op: str = Field(max_length=20)
    tipo: str = Field(max_length=3)
    arquivo: str = Field(max_length=255)
    data_envio: date | None = None
    destinatario: str = Field(default="", max_length=300)
    nf_saida: str = Field(default="", max_length=40)
    observacoes: str = Field(default="", max_length=2000)


@rota.post("/databooks/envios", status_code=201)
def marcar_enviado(dados: EnvioEntrada, ctx: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> dict:
    """Marca como Enviado-DB: copia o PDF para databooks/Enviados/ e registra data, destinatário, NF e observações."""
    op, tipo, arquivo, achado = _validar_nome(dados.op, dados.tipo, dados.arquivo)
    destinatario = limpar_texto(dados.destinatario).strip()
    if not destinatario:
        raise HTTPException(422, "Informe o destinatário (campo obrigatório).")
    origem = caminho_seguro(f"{pasta_op(op, tipo)}/{arquivo}")
    if not origem:
        raise HTTPException(404, f"Arquivo não encontrado: {arquivo}")
    numero, revisao = achado.group(1), int(achado.group(3))
    for e in envios_ativos(db):
        mesmo_lote = (e.op.strip(), e.tipo.upper(), e.lote.strip().lower()) == (op, tipo, numero.lower())
        if e.arquivo == arquivo or (mesmo_lote and (e.revisao or 0) >= revisao):
            raise HTTPException(409, f"O databook OP {op}/{tipo} (Rev {revisao}) já está marcado como Enviado-DB.")

    agora = agora_local()
    conteudo = origem.read_bytes()
    destino = f"{PASTA_ENVIADOS}/{arquivo}"
    if not _gravar_novo(destino, conteudo):  # já existe um com esse nome: acrescenta a data e hora
        destino = f"{PASTA_ENVIADOS}/{Path(arquivo).stem}_{agora:%Y%m%d%H%M%S}.pdf"
        if not _gravar_novo(destino, conteudo):
            raise HTTPException(409, "Outra pessoa acabou de marcar este databook. Recarregue a página.")
    envio = DatabookEnviado(
        op=op, tipo=tipo, lote=numero, revisao=revisao, arquivo=arquivo, caminho=destino,
        data_envio=dados.data_envio or agora.date(), destinatario=destinatario,
        nf_saida=limpar_texto(dados.nf_saida).strip(), observacoes=limpar_texto(dados.observacoes).strip(),
        enviado_em=agora, enviado_por=ctx.usuario.nome,
    )  # fmt: skip
    db.add(envio)
    db.flush()
    lote = _lote_do_numero(db, numero)
    # Como no antigo, o envio não entra na linha do tempo do lote (fica na auditoria e na aba Enviados-DB)
    auditar(db, ctx, "ENVIAR", "databook_envio", envio.id,
            {"op": op, "tipo": tipo, "lote": numero, "revisao": revisao, "arquivo": arquivo,
             "destinatario": destinatario, "nf_saida": envio.nf_saida, "data_envio": envio.data_envio},
            lote_id=lote.id if lote else None)  # fmt: skip
    db.commit()
    return _envio(envio, _ids_dos_lotes(db))


class DesfazerEntrada(BaseModel):
    motivo: str = Field(default="", max_length=500)


@rota.post("/databooks/envios/{envio_id}/desfazer")
def desfazer_envio(
    envio_id: int, dados: DesfazerEntrada, ctx: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)
) -> dict:
    """Desfaz a marcação: o databook volta para "A enviar". A linha fica (marcada como desfeita) e nada é apagado."""
    envio = db.get(DatabookEnviado, envio_id)
    if not envio:
        raise HTTPException(404, "Envio não encontrado.")
    if envio.desfeito_em:
        raise HTTPException(409, "Este envio já foi desfeito.")
    motivo = limpar_texto(dados.motivo).strip()
    if len(motivo) < 3:
        raise HTTPException(422, "Escreva o motivo para desfazer o envio.")
    # O antigo devolvia o PDF para a pasta da OP. Envios trazidos do antigo não têm mais o PDF lá: copia de volta
    nome = envio.arquivo if RE_ARQUIVO.match(envio.arquivo) else f"Databook_{nome_base(envio.lote, envio.tipo, envio.revisao)}.pdf"
    origem = caminho_seguro(envio.caminho)
    de_volta = f"{pasta_op(envio.op, envio.tipo)}/{nome}"
    if origem and not caminho_seguro(de_volta):
        _gravar_novo(de_volta, origem.read_bytes())
    envio.desfeito_em = agora_local()
    envio.desfeito_por = ctx.usuario.nome
    envio.desfeito_motivo = motivo
    lote = _lote_do_numero(db, envio.lote)
    auditar(db, ctx, "DESFAZER", "databook_envio", envio.id,
            {"op": envio.op, "tipo": envio.tipo, "lote": envio.lote, "revisao": envio.revisao,
             "destinatario": envio.destinatario, "motivo": motivo},
            lote_id=lote.id if lote else None)  # fmt: skip
    db.commit()
    return _envio(envio, _ids_dos_lotes(db))


@rota.get("/databooks/envios/{envio_id}/arquivo")
def baixar_enviado(envio_id: int, _: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> FileResponse:
    envio = db.get(DatabookEnviado, envio_id)
    if not envio:
        raise HTTPException(404, "Envio não encontrado.")
    return resposta_arquivo(envio.caminho, envio.arquivo or "databook.pdf")


# ----------------------------------------------------------------- rotas: databook do lote


def _aprovadores(db: Session) -> list[dict]:
    usuarios = db.scalars(select(Usuario).where(Usuario.ativo.is_(True), Usuario.pode_aprovar.is_(True)).order_by(Usuario.nome))
    return [{"id": u.id, "nome": u.nome, "cargo": u.cargo, "tem_assinatura": bool(u.assinatura_arquivo)} for u in usuarios]


@rota.get("/databooks/lote/{lote_id}")
def databook_do_lote(lote_id: int, ctx: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> dict:
    """Tudo o que o bloco "Databook do cliente" da página do lote mostra."""
    lote = buscar_lote(db, lote_id)
    revisoes = revisoes_do_lote(lote.id)
    ultimo = revisoes[-1] if revisoes else None
    lotes = _ids_dos_lotes(db)
    envios = [
        e for e in _ordenar_envios(envios_ativos(db))
        if (e.op.strip(), e.tipo.strip().upper()) == (lote.op.strip(), lote.tipo.upper())
    ]  # fmt: skip
    pendente = next((d for d in listar_a_enviar(db) if d["lote_id"] == lote.id), None)
    capa = dados_capa(db, lote)
    capa |= {
        "proxima_revisao": proxima_revisao(lote),
        "elaborado_por": ctx.usuario.nome,
        "elaborado_cargo": ctx.usuario.cargo,
        "elaborado_tem_assinatura": bool(ctx.usuario.assinatura_arquivo),
    }
    sem_relativo = [{k: v for k, v in r.items() if k != "relativo"} for r in reversed(revisoes)]
    return {
        "lote": {"id": lote.id, "numero": lote.numero, "op": lote.op, "tipo": lote.tipo, "qtd": lote.qtd},
        "concluido": lote_concluido(db, lote),
        "databook": sem_relativo[0] if ultimo else None,
        "revisoes": sem_relativo,
        "alertas": alertas_da_revisao(lote.id, ultimo["arquivo"]) if ultimo else [],
        "envios": [_envio(e, lotes) for e in envios],
        "pendente_envio": pendente,
        "aprovadores": _aprovadores(db),
        "capa": capa,
        "hoje": agora_local().date(),
    }


class GerarEntrada(BaseModel):
    data_aprovacao: date | None = None
    aprovador_id: int | None = None
    produto: str = Field(default="", max_length=200)


@rota.post("/databooks/lote/{lote_id}/gerar", status_code=201)
def gerar_databook(lote_id: int, dados: GerarEntrada, ctx: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> dict:
    """Gera uma revisão nova do databook (a primeira é a Rev 0) e guarda uma cópia na pasta da OP ("A enviar")."""
    lote = buscar_lote(db, lote_id)
    if not lote_concluido(db, lote):
        raise HTTPException(409, "O databook só é gerado depois que todas as etapas do lote forem aprovadas (até a embalagem).")
    if not dados.data_aprovacao:
        raise HTTPException(422, "Digite a DATA DE APROVAÇÃO antes de gerar o databook.")
    aprovador = db.get(Usuario, dados.aprovador_id) if dados.aprovador_id else None
    if not aprovador or not aprovador.ativo or not aprovador.pode_aprovar:
        raise HTTPException(422, "Escolha em \"Aprovado por\" um usuário que pode aprovar pela Qualidade.")

    info = dados_capa(db, lote)
    produto = limpar_texto(dados.produto).strip() or info["produto"]
    data = dados.data_aprovacao.strftime("%d/%m/%Y")
    secoes, checklist = secoes_do_lote(db, lote)
    resultado, revisao, nome = None, -1, ""
    for _tentativa in range(5):  # duas pessoas gerando ao mesmo tempo: a segunda fica com a revisão seguinte
        revisao = max(proxima_revisao(lote), revisao + 1)
        capa = Capa(
            empresa=info["empresa"], cliente=info["cliente"], projeto=info["projeto"], produto=produto,
            pedido=info["pedido"], lote=lote.numero, qtd=str(lote.qtd), numero_documento=info["numero_documento"],
            revisao=str(revisao), data=data,
            elaborado_por=ctx.usuario.nome, elaborado_cargo=ctx.usuario.cargo,
            assinatura_elaborado=caminho_assinatura(ctx.usuario),
            aprovado_por=aprovador.nome, aprovado_cargo=aprovador.cargo,
            assinatura_aprovado=caminho_assinatura(aprovador), data_aprovacao=data,
        )  # fmt: skip
        try:
            resultado = montar(capa, secoes, checklist, logo=LOGO)
        except SemDocumentos as erro:
            raise HTTPException(422, f"Não foi possível gerar o databook: {erro} Anexe os documentos nas etapas e tente de novo.") from erro
        base = nome_base(lote.numero, lote.tipo, revisao)
        nome = f"Databook_{base}.pdf"
        if _gravar_novo(f"{pasta_saida(lote.id)}/{nome}", resultado.pdf):
            break
    else:
        raise HTTPException(409, "Não foi possível reservar o número da revisão. Tente de novo.")
    _absoluto(f"{pasta_saida(lote.id)}/Relatorio_Conferencia_{base}.txt").write_text(resultado.relatorio, encoding="utf-8")
    # Cópia na pasta da OP: é dali que a tela Databooks lista o que falta enviar ao cliente
    _gravar_novo(f"{pasta_op(lote.op, lote.tipo)}/{nome}", resultado.pdf)

    registrar_evento(db, lote.id, f"Databook gerado (rev. {revisao})")
    auditar(db, ctx, "GERAR", "databook", f"{lote.id}/rev{revisao}",
            {"arquivo": nome, "revisao": revisao, "paginas": resultado.paginas, "data_aprovacao": data,
             "elaborado_por": ctx.usuario.nome, "aprovado_por": aprovador.nome, "produto": produto,
             "alertas": resultado.alertas},
            lote_id=lote.id)  # fmt: skip
    db.commit()
    return {
        "arquivo": nome,
        "revisao": revisao,
        "paginas": resultado.paginas,
        "tamanho_kb": max(1, round(len(resultado.pdf) / 1024)),
        "alertas": resultado.alertas,
        "mensagem": f"Databook do lote {lote.numero} (OP {lote.op}) gerado com sucesso. Clique em Baixar para visualizar.",
    }


@rota.get("/databooks/lote/{lote_id}/pdf")
def baixar_databook(lote_id: int, arquivo: str = "", _: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> FileResponse:
    """O databook mais recente do lote (ou a revisão pedida), para abrir no navegador."""
    lote = buscar_lote(db, lote_id)
    revisao = _revisao_escolhida(lote, arquivo)
    return resposta_arquivo(revisao["relativo"], revisao["arquivo"])


@rota.get("/databooks/lote/{lote_id}/conferencia")
def conferir_databook_lote(lote_id: int, arquivo: str = "", _: Contexto = Depends(QUALIDADE), db: Session = Depends(get_db)) -> dict:
    """Procura no PDF páginas que citam OP ou lote diferente do lote (documento trocado por engano)."""
    lote = buscar_lote(db, lote_id)
    revisao = _revisao_escolhida(lote, arquivo)
    caminho = caminho_seguro(revisao["relativo"])
    if not caminho:
        raise HTTPException(404, "Este lote ainda não tem databook gerado.")
    return {
        "lote": {"id": lote.id, "numero": lote.numero, "op": lote.op, "tipo": lote.tipo},
        "arquivo": revisao["arquivo"],
        "revisao": revisao["revisao"],
        "gerado_em": revisao["gerado_em"],
        "resultado": conferir_databook(caminho, lote.op, lote.numero),
    }
