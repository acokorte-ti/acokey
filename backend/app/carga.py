"""Carga inicial a partir do sistema antigo (Flask + SQLite + planilhas Excel, pasta legado/).

Uso, na pasta backend (o .env aponta para o banco NOVO):

    python -m app.carga ../legado                       # só confere e mostra o relatório
    python -m app.carga ../legado --aplicar             # grava
    python -m app.carga ../legado --dados data_teste    # usa a base de TESTES do sistema antigo
    python -m app.carga ../legado --renomear fulano=fulano.tal --admin fulano.tal   # troca um login e o torna administrador

No servidor, com a pasta do sistema antigo copiada para ~/acokey-carga/ (permissão 700):

    docker compose run --rm --no-deps -v ~/acokey-carga:/carga:ro api python -m app.carga /carga --aplicar

Regras:
- Só roda com o banco sem lotes, sem matéria-prima e sem OPs (o administrador inicial pode existir).
- Os ids do sistema antigo são mantidos (lote 7 continua lote 7), e os arquivos mantêm o caminho relativo.
- Senhas NÃO são migradas: o sistema antigo usava pbkdf2/scrypt e algumas ainda estavam em texto puro.
  Todos os usuários entram sem senha utilizável; o administrador define uma senha provisória para cada
  um na tela Usuários, e a pessoa troca no primeiro acesso.
- Nenhum valor de especificação é inventado: um limite que não seja número interrompe a carga.
- Nada do sistema antigo é alterado (o banco é aberto só para leitura).
"""
import argparse
import json
import re
import secrets
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import FUSO, config
from app.models import (
    MODULOS,
    STATUS_CARGA_TT,
    STATUS_ENVIO,
    STATUS_MP,
    STATUS_NC,
    STATUS_OF,
    STATUS_REGISTRO,
    TIPOS_LOTE,
    Anexo,
    Auditoria,
    CargaTT,
    CargaTTLote,
    DatabookEnviado,
    EnvioPrestador,
    EnvioPrestadorFoto,
    EnvioPrestadorLote,
    Equipamento,
    EspecificacaoCota,
    EspecificacaoTipo,
    Evento,
    FornecedorMP,
    Lote,
    MateriaPrima,
    MateriaPrimaAnexo,
    NaoConformidade,
    OrdemFaturamento,
    OrdemFaturamentoLote,
    OrdemProducao,
    Parametro,
    Prestador,
    Registro,
    Usuario,
)
from app.seguranca import hash_senha

CAMPOS_SPEC_NUMERICOS = (
    "dureza_min", "dureza_max", "tr_le_min", "tr_le_max", "tr_lr_min", "tr_lr_max", "tr_al_min", "tr_ra_min",
    "ch_med_min", "ch_ind_min",
)  # fmt: skip
_LOGIN_VALIDO = re.compile(r"^[a-z0-9._-]{3,60}$")


class ErroCarga(Exception):
    pass


@dataclass
class Relatorio:
    contagens: dict[str, int] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)  # informativo
    pendencias: list[str] = field(default_factory=list)  # algo a corrigir depois, mas a carga segue
    bloqueios: list[str] = field(default_factory=list)  # impede gravar
    arquivos_copiados: int = 0
    bytes_copiados: int = 0
    arquivos_faltando: list[str] = field(default_factory=list)
    nao_referenciados: dict[str, int] = field(default_factory=dict)

    def contar(self, nome: str, n: int) -> None:
        self.contagens[nome] = self.contagens.get(nome, 0) + n

    def texto(self, aplicado: bool) -> str:
        linhas = ["", "=== Carga do sistema antigo: " + ("GRAVADA" if aplicado else "SIMULAÇÃO (nada foi gravado)") + " ==="]
        linhas.append("\nRegistros por tabela:")
        linhas += [f"  {nome:28} {n:6}" for nome, n in self.contagens.items()]
        linhas.append(f"\nArquivos: {self.arquivos_copiados} {'copiados' if aplicado else 'a copiar'} "
                      f"({self.bytes_copiados / 1024 / 1024:.1f} MB); {len(self.arquivos_faltando)} referenciados no banco "
                      "mas ausentes no disco")  # fmt: skip
        linhas += [f"  faltando: {a}" for a in self.arquivos_faltando[:30]]
        if len(self.arquivos_faltando) > 30:
            linhas.append(f"  ... e mais {len(self.arquivos_faltando) - 30}")
        if self.nao_referenciados:
            linhas.append("\nArquivos da pasta de dados que o banco não referencia (copiados no mesmo caminho):")
            linhas += [f"  {pasta:28} {n:6}" for pasta, n in sorted(self.nao_referenciados.items())]
        for titulo, itens in (("Avisos", self.avisos), ("Pendências (a carga segue)", self.pendencias),
                              ("BLOQUEIOS (corrija antes de gravar)", self.bloqueios)):  # fmt: skip
            if itens:
                linhas.append(f"\n{titulo}:")
                linhas += [f"  - {i}" for i in itens]
        return "\n".join(linhas)


# ---------------------------------------------------------------- conversões


def _texto(valor: Any) -> str:
    return "" if valor is None else str(valor).strip()


def _inteiro(valor: Any) -> int:
    try:
        return int(float(str(valor).replace(",", "."))) if _texto(valor) else 0
    except ValueError:
        return 0


def _inteiro_ou_nada(valor: Any) -> int | None:
    return _inteiro(valor) if _texto(valor) else None


def _peso(valor: Any) -> Decimal:
    try:
        return Decimal(str(valor).replace(",", ".")).quantize(Decimal("0.001")) if _texto(valor) else Decimal(0)
    except InvalidOperation:
        return Decimal(0)


_FORMATOS_DATA_HORA = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%d/%m/%Y %H:%M")
_FORMATOS_DATA = ("%Y-%m-%d", "%d/%m/%Y")


def data_hora(valor: Any, onde: str, rel: Relatorio) -> datetime | None:
    if isinstance(valor, datetime):
        return valor.replace(microsecond=0)
    if isinstance(valor, date):
        return datetime(valor.year, valor.month, valor.day)
    s = _texto(valor)
    if not s:
        return None
    for formato in _FORMATOS_DATA_HORA + _FORMATOS_DATA:
        try:
            return datetime.strptime(s, formato)
        except ValueError:
            pass
    rel.pendencias.append(f"{onde}: data não reconhecida {s!r} (ficou vazia)")
    return None


def so_data(valor: Any, onde: str, rel: Relatorio) -> date | None:
    dh = data_hora(valor, onde, rel)
    return dh.date() if dh else None


def local_para_utc(valor: datetime | None) -> datetime | None:
    """O sistema antigo gravava a hora local da fábrica sem fuso; datas de sistema no novo têm fuso."""
    return valor.replace(tzinfo=FUSO).astimezone(UTC) if valor else None


def _json(valor: Any, onde: str, rel: Relatorio) -> Any:
    s = _texto(valor)
    if not s:
        return None
    try:
        return json.loads(s)
    except ValueError:
        rel.pendencias.append(f"{onde}: conteúdo JSON inválido (guardado como texto em 'texto_original')")
        return {"texto_original": s}


def numero_spec(valor: Any, onde: str, rel: Relatorio) -> Decimal | None:
    s = _texto(valor).replace(",", ".")
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        rel.bloqueios.append(f"{onde} = {valor!r} não é número. Corrija no sistema antigo (nunca inventar o valor).")
        return None


def relativo_legado(caminho: Any, pasta: str) -> str | None:
    """'C:\\Sistema\\Projeto\\data\\lotes\\2\\anexos\\x.pdf' -> 'lotes/2/anexos/x.pdf' (a partir de `pasta`)."""
    partes = [p for p in re.split(r"[\\/]+", _texto(caminho)) if p]
    minusculas = [p.lower() for p in partes]
    if pasta.lower() not in minusculas:
        return None
    resto = partes[minusculas.index(pasta.lower()) + 1 :]
    if not resto or any(p in (".", "..") for p in resto):
        return None
    return "/".join(resto)


def _achar(raiz: Path, nome: str) -> Path | None:
    """Arquivo ou pasta pelo nome, sem diferenciar maiúsculas (no Windows o sistema antigo misturava)."""
    if not raiz.is_dir():
        return None
    return next((p for p in raiz.iterdir() if p.name.lower() == nome.lower()), None)


# ---------------------------------------------------------------- leitura do sistema antigo


def _ler_tabelas(banco: Path) -> dict[str, list[dict]]:
    conexao = sqlite3.connect(f"file:{banco.as_posix()}?mode=ro", uri=True)
    conexao.row_factory = sqlite3.Row
    try:
        nomes = [r[0] for r in conexao.execute("select name from sqlite_master where type='table'")]
        return {n: [dict(r) for r in conexao.execute(f'select * from "{n}" order by rowid')] for n in nomes}
    finally:
        conexao.close()


def planilha_de_ops(raiz: Path, rel: Relatorio) -> Path | None:
    """A planilha mestre de OPs (Cadastro_Lote_<cliente>.xlsx), sem as cópias de segurança "_antes_"."""
    candidatas = sorted(
        p for p in raiz.iterdir()
        if p.is_file() and p.name.lower().startswith("cadastro_lote_") and p.suffix.lower() == ".xlsx"
        and "_antes" not in p.name.lower()
    ) if raiz.is_dir() else []  # fmt: skip
    if len(candidatas) > 1:
        rel.bloqueios.append(f"mais de uma planilha de OPs: {', '.join(p.name for p in candidatas)} — deixe só a atual")
        return None
    if not candidatas:
        rel.avisos.append("planilha de OPs (Cadastro_Lote_*.xlsx) não encontrada: nenhuma OP migrada")
        return None
    return candidatas[0]


def _planilha(raiz: Path, nome: str | Path | None, aba: str | None = None) -> list[tuple]:
    import openpyxl

    arquivo = nome if isinstance(nome, Path) else (_achar(raiz, nome) if nome else None)
    if not arquivo:
        return []
    livro = openpyxl.load_workbook(arquivo, data_only=True, read_only=True)
    try:
        folha = livro[aba] if aba else livro.worksheets[0]
        return [tuple(linha) for linha in folha.iter_rows(min_row=2, values_only=True)]
    finally:
        livro.close()


def _col(linha: tuple, i: int) -> Any:
    return linha[i] if i < len(linha) else None


# ---------------------------------------------------------------- montagem


@dataclass
class Plano:
    grupos: list[list[Any]] = field(default_factory=list)  # objetos a gravar, em ordem de dependência
    usuarios: list[Usuario] = field(default_factory=list)
    auditoria: list[tuple[dict, str]] = field(default_factory=list)  # (campos, login) — usuario_id resolvido depois
    copias: list[tuple[Path, str]] = field(default_factory=list)  # (origem, destino relativo)


def montar(
    db: Session,
    raiz: Path,
    pasta_dados: str,
    rel: Relatorio,
    renomear: dict[str, str] | None = None,
    admins: set[str] | None = None,
) -> Plano:
    """renomear: {login antigo: login novo}. admins: logins (já os novos) que entram como administrador."""
    banco = raiz / pasta_dados / "sistema.db"
    if not banco.is_file():
        raise ErroCarga(f"Banco do sistema antigo não encontrado: {banco}")
    t = _ler_tabelas(banco)
    pasta_databook = "DATABOOK_TESTE" if pasta_dados.lower() != "data" else "DATABOOK"
    plano = Plano()
    referenciados: set[str] = set()

    def arquivo(caminho: Any, onde: str, pasta: str = pasta_dados, prefixo: str = "") -> str:
        """Agenda a cópia e devolve o caminho relativo novo ('' se não deu para entender o caminho)."""
        rel_antigo = relativo_legado(caminho, pasta)
        if not rel_antigo:
            if _texto(caminho):
                rel.pendencias.append(f"{onde}: caminho fora da pasta {pasta}: {_texto(caminho)!r}")
            return ""
        origem = raiz / pasta / rel_antigo
        destino = prefixo + rel_antigo
        if pasta == pasta_dados:
            referenciados.add(rel_antigo.lower())
        if origem.is_file():
            plano.copias.append((origem, destino))
            rel.bytes_copiados += origem.stat().st_size
        else:
            rel.arquivos_faltando.append(f"{onde}: {destino}")
        return destino

    # --- cadastros (planilhas)
    fornecedores = {}
    for linha in _planilha(raiz, "Fornecedores_MP.xlsx"):
        codigo = _texto(_col(linha, 0))
        if codigo:
            fornecedores[codigo] = FornecedorMP(
                codigo=codigo, razao_social=_texto(_col(linha, 1)), materiais=_texto(_col(linha, 2)),
                contato=_texto(_col(linha, 3)), observacoes=_texto(_col(linha, 4)),
            )  # fmt: skip
    prestadores = {}
    for linha in _planilha(raiz, "Prestadores_Servico.xlsx"):
        codigo = _texto(_col(linha, 0))
        if codigo:
            prestadores[codigo] = Prestador(
                codigo=codigo, razao_social=_texto(_col(linha, 1)), tipo_servico=_texto(_col(linha, 2)),
                contato=_texto(_col(linha, 3)), observacoes=_texto(_col(linha, 4)),
            )  # fmt: skip
    equipamentos = {}
    for linha in _planilha(raiz, "Cadastro_de_Equipamento.xlsx"):
        codigo = _texto(_col(linha, 0))
        if codigo:
            onde = f"equipamento {codigo}"
            equipamentos[codigo] = Equipamento(
                codigo=codigo, descricao=_texto(_col(linha, 1)), setor=_texto(_col(linha, 2)), marca=_texto(_col(linha, 3)),
                data_calibracao=so_data(_col(linha, 4), onde, rel), validade_calibracao=so_data(_col(linha, 5), onde, rel),
                certificado=_texto(_col(linha, 6)), empresa_calibracao=_texto(_col(linha, 7)),
            )  # fmt: skip
    ops: dict[str, OrdemProducao] = {}
    arquivo_ops = planilha_de_ops(raiz, rel)
    for linha in _planilha(raiz, arquivo_ops, "Dados"):
        op = _texto(_col(linha, 1))
        if not op:
            continue
        if op in ops:
            rel.avisos.append(f"OP {op} aparece mais de uma vez em {arquivo_ops.name}: ficou a última linha")
        tipo = _texto(_col(linha, 4)).upper()
        ops[op] = OrdemProducao(
            op=op, cliente=_texto(_col(linha, 0)), coditem=_texto(_col(linha, 2)), descricao=_texto(_col(linha, 3)),
            tipo=tipo if tipo in TIPOS_LOTE else None, data_faturamento=so_data(_col(linha, 5), f"OP {op}", rel),
            nf=_texto(_col(linha, 6)), piv=_texto(_col(linha, 7)), qt_lote=_inteiro_ou_nada(_col(linha, 8)),
            qt_faturada=_inteiro_ou_nada(_col(linha, 9)), projeto=_texto(_col(linha, 10)), po=_texto(_col(linha, 11)),
            origem="planilha",
        )  # fmt: skip
    plano.grupos.append([*fornecedores.values(), *prestadores.values(), *equipamentos.values(), *ops.values()])
    rel.contar("fornecedores_mp", len(fornecedores))
    rel.contar("prestadores", len(prestadores))
    rel.contar("equipamentos", len(equipamentos))
    rel.contar("ordens_producao", len(ops))

    # --- especificações
    specs = []
    for r in t.get("spec_tipo", []):
        tipo = _texto(r.get("tipo")).upper()
        if tipo not in TIPOS_LOTE:
            rel.bloqueios.append(f"spec_tipo: tipo desconhecido {tipo!r}")
            continue
        valores = {c: numero_spec(r.get(c), f"especificação {tipo}.{c}", rel) for c in CAMPOS_SPEC_NUMERICOS}
        specs.append(EspecificacaoTipo(tipo=tipo, ch_temp=_texto(r.get("ch_temp")), ch_dim_cp=_texto(r.get("ch_dim_cp")), **valores))
    cotas = [
        EspecificacaoCota(id=r["id"], coditem=_texto(r.get("coditem")), descricao=_texto(r.get("desc_")),
                          nominal=_texto(r.get("nominal")), tol_min=_texto(r.get("tmin")), tol_max=_texto(r.get("tmax")))
        for r in t.get("spec_cotas", [])
    ]  # fmt: skip
    plano.grupos.append([*specs, *cotas])
    rel.contar("especificacoes_tipo", len(specs))
    rel.contar("especificacoes_cotas", len(cotas))

    # --- matéria-prima
    mps = []
    for r in t.get("materia_prima", []):
        onde = f"matéria-prima {r['id']}"
        status = _texto(r.get("status")) or "pendente"
        if status not in STATUS_MP:
            rel.bloqueios.append(f"{onde}: status desconhecido {status!r}")
        mps.append(MateriaPrima(
            id=r["id"], nf_entrada=_texto(r.get("nf_entrada")), corrida=_texto(r.get("corrida")),
            fornecedor=_texto(r.get("fornecedor")), tipo_destino=_texto(r.get("tipo_destino")).upper(),
            data_recebimento=so_data(r.get("data_recebimento"), onde, rel),
            qt_fund=_inteiro(r.get("qt_fund")), qt_real=_inteiro(r.get("qt_real")), qt_ok=_inteiro(r.get("qt_ok")),
            qt_rej=_inteiro(r.get("qt_rej")), qt_retrab=_inteiro(r.get("qt_retrab")), qt_cp_tt=_inteiro(r.get("qt_cp_tt")),
            observacoes=_texto(r.get("observacoes")), criado_em=data_hora(r.get("criado"), onde, rel),
            responsavel=_texto(r.get("resp")), status=status, aprovado_por=_texto(r.get("aprovado_por")),
            aprovado_em=data_hora(r.get("aprovado_em"), onde, rel), obs_aprovacao=_texto(r.get("obs_aprovacao")),
        ))  # fmt: skip
    ids_mp = {m.id for m in mps}
    mp_anexos = []
    for r in t.get("mp_anexos", []):
        if r.get("mp_id") not in ids_mp:
            rel.pendencias.append(f"anexo de matéria-prima {r['id']}: corrida {r.get('mp_id')} não existe (não migrado)")
            continue
        onde = f"anexo de matéria-prima {r['id']}"
        mp_anexos.append(MateriaPrimaAnexo(
            id=r["id"], materia_prima_id=r["mp_id"], nome=_texto(r.get("nome")) or "arquivo",
            arquivo=arquivo(r.get("arquivo"), onde), quando=data_hora(r.get("quando"), onde, rel),
        ))  # fmt: skip
    plano.grupos.append(mps)
    plano.grupos.append(mp_anexos)
    rel.contar("materias_primas", len(mps))
    rel.contar("materias_primas_anexos", len(mp_anexos))

    # --- lotes
    mp_por_corrida: dict[str, list[int]] = {}
    for m in mps:
        if m.corrida:
            mp_por_corrida.setdefault(m.corrida.upper(), []).append(m.id)
    lotes = []
    for r in t.get("lotes", []):
        onde = f"lote {r['id']}"
        tipo, numero = _texto(r.get("tipo")).upper(), _texto(r.get("lote"))
        if tipo not in TIPOS_LOTE:
            rel.bloqueios.append(f"{onde}: tipo desconhecido {tipo!r}")
        if not numero:
            rel.bloqueios.append(f"{onde}: sem número de lote")
        corrida = _texto(r.get("corrida"))
        candidatos = mp_por_corrida.get(corrida.upper(), []) if corrida else []
        if corrida and len(candidatos) != 1:
            rel.avisos.append(f"{onde} ({numero}): corrida {corrida!r} com {len(candidatos)} cadastro(s) de matéria-prima — "
                              "ficou sem vínculo")  # fmt: skip
        lotes.append(Lote(
            id=r["id"], numero=numero, op=_texto(r.get("op")), tipo=tipo, qtd=_inteiro(r.get("qtd")), corrida=corrida,
            coditem=_texto(r.get("coditem")), materia_prima_id=candidatos[0] if len(candidatos) == 1 else None,
            etapa=_inteiro(r.get("etapa")), etapa_desde=data_hora(r.get("etapa_desde"), onde, rel),
            criado_em=data_hora(r.get("criado"), onde, rel),
        ))  # fmt: skip
    ids_lote = {lote.id for lote in lotes}
    plano.grupos.append(lotes)
    rel.contar("lotes", len(lotes))

    def do_lote(r: dict, tabela: str) -> bool:
        if r.get("lote_id") in ids_lote:
            return True
        rel.pendencias.append(f"{tabela} {r.get('id')}: lote {r.get('lote_id')} não existe (não migrado)")
        return False

    registros = []
    for r in t.get("registros", []):
        if not do_lote(r, "registro"):
            continue
        onde = f"registro {r['id']}"
        status = _texto(r.get("status"))
        if status not in STATUS_REGISTRO:
            rel.bloqueios.append(f"{onde}: status desconhecido {status!r}")
        registros.append(Registro(
            id=r["id"], lote_id=r["lote_id"], etapa=_texto(r.get("etapa")), sub=_texto(r.get("sub")), status=status,
            dados=_json(r.get("dados"), onde, rel), quando=data_hora(r.get("quando"), onde, rel),
            responsavel=_texto(r.get("resp")), anulado=bool(_inteiro(r.get("anulado"))),
            anulado_motivo=_texto(r.get("anulado_motivo")), anulado_em=data_hora(r.get("anulado_em"), onde, rel),
            anulado_por=_texto(r.get("anulado_por")),
        ))  # fmt: skip
    ids_registro = {x.id for x in registros}
    anexos = []
    for r in t.get("anexos", []):
        if not do_lote(r, "anexo"):
            continue
        onde = f"anexo {r['id']} (lote {r['lote_id']})"
        anexos.append(Anexo(
            id=r["id"], lote_id=r["lote_id"], etapa=_texto(r.get("etapa")), sub=_texto(r.get("sub")),
            nome=_texto(r.get("nome")) or "arquivo", arquivo=arquivo(r.get("arquivo"), onde),
            quando=data_hora(r.get("quando"), onde, rel), apenas_registro=bool(_inteiro(r.get("apenas_registro"))),
        ))  # fmt: skip
    ids_anexo = {a.id for a in anexos}
    eventos, eventos_login = [], 0
    for r in t.get("eventos", []):
        if not r.get("lote_id"):
            eventos_login += 1  # o sistema antigo registrava logins como evento de "lote 0"
            continue
        if do_lote(r, "evento"):
            eventos.append(Evento(id=r["id"], lote_id=r["lote_id"], quando=data_hora(r.get("quando"), f"evento {r['id']}", rel),
                                  texto=_texto(r.get("texto"))))  # fmt: skip
    if eventos_login:
        rel.avisos.append(f"{eventos_login} eventos de login do sistema antigo não foram migrados para a linha do tempo "
                          "(logins ficam na auditoria)")  # fmt: skip
    plano.grupos.append(registros)
    plano.grupos.append([*anexos, *eventos])
    rel.contar("registros", len(registros))
    rel.contar("anexos", len(anexos))
    rel.contar("eventos", len(eventos))

    ncs = []
    for r in t.get("nao_conformidades", []):
        if not do_lote(r, "não conformidade"):
            continue
        onde = f"NC {r.get('numero') or r['id']}"
        status, disposicao = _texto(r.get("status")) or "aberta", _texto(r.get("disposicao"))
        if status not in STATUS_NC:
            rel.bloqueios.append(f"{onde}: status desconhecido {status!r}")
        registro_id = r.get("registro_id") or None
        if registro_id and registro_id not in ids_registro:
            rel.pendencias.append(f"{onde}: registro {registro_id} não existe (vínculo removido)")
            registro_id = None
        ncs.append(NaoConformidade(
            id=r["id"], numero=_texto(r.get("numero")), lote_id=r["lote_id"], etapa=_texto(r.get("etapa")),
            sub=_texto(r.get("sub")), registro_id=registro_id, descricao=_texto(r.get("descricao")),
            qtd_lote_na_abertura=_inteiro(r.get("qtd_lote_na_abertura")), qtd_afetada=_inteiro(r.get("qtd_afetada")),
            disposicao=disposicao, justificativa=_texto(r.get("justificativa")), status=status,
            aberta_em=data_hora(r.get("aberta_em"), onde, rel), aberta_por=_texto(r.get("aberta_por")),
            decidida_em=data_hora(r.get("decidida_em"), onde, rel), decidida_por=_texto(r.get("decidida_por")),
            encerrada_em=data_hora(r.get("encerrada_em"), onde, rel), encerrada_por=_texto(r.get("encerrada_por")),
            observacoes=_texto(r.get("observacoes")),
        ))  # fmt: skip
    plano.grupos.append(ncs)
    rel.contar("nao_conformidades", len(ncs))

    # --- cargas de TT, envios a prestador, ordens de faturamento, databooks
    cargas = []
    for r in t.get("cargas_tt", []):
        onde = f"carga TT {r.get('numero') or r['id']}"
        status = _texto(r.get("status")) or "planejada"
        if status not in STATUS_CARGA_TT:
            rel.bloqueios.append(f"{onde}: status desconhecido {status!r}")
        anexo_rel = r.get("relatorio_anexo_id") or None
        cargas.append(CargaTT(
            id=r["id"], numero=_texto(r.get("numero")), forno_tempera_codigo=_texto(r.get("forno_tempera_codigo")),
            forno_revenimento_codigo=_texto(r.get("forno_revenimento_codigo")),
            data_planejada=so_data(r.get("data_planejada"), onde, rel), data_inicio=data_hora(r.get("data_inicio"), onde, rel),
            data_fim=data_hora(r.get("data_fim"), onde, rel), status=status, observacoes=_texto(r.get("observacoes")),
            criado_em=data_hora(r.get("criado_em"), onde, rel), criado_por=_texto(r.get("criado_por")),
            relatorio_anexo_id=anexo_rel if anexo_rel in ids_anexo else None,
        ))  # fmt: skip
    ids_carga = {c.id for c in cargas}
    cargas_lotes = [
        CargaTTLote(id=r["id"], carga_id=r["carga_id"], lote_id=r["lote_id"], ordem=_inteiro(r.get("ordem")))
        for r in t.get("cargas_tt_lotes", []) if r.get("carga_id") in ids_carga and do_lote(r, "lote de carga TT")
    ]  # fmt: skip

    envios = []
    for r in t.get("envios_prestador", []):
        onde = f"envio {r.get('numero') or r['id']}"
        status = _texto(r.get("status")) or "enviado"
        if status not in STATUS_ENVIO:
            rel.bloqueios.append(f"{onde}: status desconhecido {status!r}")
        envios.append(EnvioPrestador(
            id=r["id"], numero=_texto(r.get("numero")), prestador=_texto(r.get("prestador")),
            tipo_servico=_texto(r.get("tipo_servico")), data_emissao=so_data(r.get("data_emissao"), onde, rel),
            data_envio=so_data(r.get("data_envio"), onde, rel), data_retorno=so_data(r.get("data_retorno"), onde, rel),
            responsavel=_texto(r.get("responsavel")), status=status, observacoes=_texto(r.get("observacoes")),
            spec_snapshot=_json(r.get("spec_snapshot"), onde, rel), qtd_cps=_texto(r.get("qtd_cps")),
            qtd_cp_tracao=_inteiro(r.get("qtd_cp_tracao")), qtd_cp_impacto=_inteiro(r.get("qtd_cp_impacto")),
            criado_em=data_hora(r.get("criado_em"), onde, rel), criado_por=_texto(r.get("criado_por")),
        ))  # fmt: skip
    ids_envio = {e.id for e in envios}
    envios_lotes = [
        EnvioPrestadorLote(
            id=r["id"], envio_id=r["envio_id"], lote_id=r["lote_id"], ordem=_inteiro(r.get("ordem")),
            qt_cp_tracao=_inteiro(r.get("qt_cp_tracao")), qt_cp_impacto=_inteiro(r.get("qt_cp_impacto")),
            qt_liberar=_inteiro(r.get("qt_liberar")), volumes=_inteiro(r.get("volumes")),
            peso_liq=_peso(r.get("peso_liq")), peso_bruto=_peso(r.get("peso_bruto")),
        )
        for r in t.get("envios_prestador_lotes", []) if r.get("envio_id") in ids_envio and do_lote(r, "lote de envio")
    ]  # fmt: skip
    envios_fotos = [
        EnvioPrestadorFoto(
            id=r["id"], envio_id=r["envio_id"], nome=_texto(r.get("nome")) or "foto",
            arquivo=arquivo(r.get("arquivo"), f"foto {r['id']} do envio {r['envio_id']}"),
            quando=data_hora(r.get("quando"), f"foto {r['id']}", rel), legenda=_texto(r.get("legenda")),
        )
        for r in t.get("envios_prestador_fotos", []) if r.get("envio_id") in ids_envio
    ]  # fmt: skip

    ofs = []
    for r in t.get("ordens_faturamento", []):
        onde = f"OF {r.get('numero') or r['id']}"
        status = _texto(r.get("status")) or "rascunho"
        if status not in STATUS_OF:
            rel.bloqueios.append(f"{onde}: status desconhecido {status!r}")
        ofs.append(OrdemFaturamento(
            id=r["id"], numero=_texto(r.get("numero")), data_emissao=so_data(r.get("data_emissao"), onde, rel),
            cliente=_texto(r.get("cliente")), pedido_cliente=_texto(r.get("pedido_cliente")), piv=_texto(r.get("piv")),
            nf_saida=_texto(r.get("nf_saida")), destinatario=_texto(r.get("destinatario")),
            observacoes=_texto(r.get("observacoes")), status=status, criado_em=data_hora(r.get("criado_em"), onde, rel),
            criado_por=_texto(r.get("criado_por")),
        ))  # fmt: skip
    ids_of = {o.id for o in ofs}
    ofs_lotes = [
        OrdemFaturamentoLote(
            id=r["id"], ordem_faturamento_id=r["of_id"], lote_id=r["lote_id"], qtd_faturada=_inteiro(r.get("qtd_faturada")),
            volumes=_inteiro(r.get("volumes")), ordem=_inteiro(r.get("ordem")),
            peso_liq=_peso(r.get("peso_liq")), peso_bruto=_peso(r.get("peso_bruto")),
        )
        for r in t.get("ordens_faturamento_lotes", []) if r.get("of_id") in ids_of and do_lote(r, "lote de OF")
    ]  # fmt: skip

    databooks = []
    for r in t.get("databooks_enviados", []):
        onde = f"databook enviado {r['id']}"
        databooks.append(DatabookEnviado(
            id=r["id"], op=_texto(r.get("op")), tipo=_texto(r.get("tipo")).upper(), lote=_texto(r.get("lote")),
            revisao=_inteiro(r.get("rev")), arquivo=_texto(r.get("arquivo")),
            caminho=arquivo(r.get("caminho_atual"), onde, pasta=pasta_databook, prefixo="databooks/"),
            data_envio=so_data(r.get("data_envio"), onde, rel), destinatario=_texto(r.get("destinatario")),
            nf_saida=_texto(r.get("nf_saida")), observacoes=_texto(r.get("observacoes")),
            enviado_em=data_hora(r.get("enviado_em"), onde, rel), enviado_por=_texto(r.get("enviado_por")),
        ))  # fmt: skip
    plano.grupos.append([*cargas, *envios, *ofs, *databooks])
    plano.grupos.append([*cargas_lotes, *envios_lotes, *envios_fotos, *ofs_lotes])
    for nome, lista in (("cargas_tt", cargas), ("cargas_tt_lotes", cargas_lotes), ("envios_prestador", envios),
                        ("envios_prestador_lotes", envios_lotes), ("envios_prestador_fotos", envios_fotos),
                        ("ordens_faturamento", ofs), ("ordens_faturamento_lotes", ofs_lotes),
                        ("databooks_enviados", databooks)):  # fmt: skip
        rel.contar(nome, len(lista))

    # --- usuários (sem senha) e auditoria
    renomear = {k.strip().lower(): v.strip().lower() for k, v in (renomear or {}).items()}
    admins = {a.strip().lower() for a in (admins or set())}
    existentes = {u.lower() for u in db.scalars(select(Usuario.login))}
    vistos_tutorial = {_texto(r.get("usuario")).lower(): r.get("visto_em") for r in t.get("tutorial_visto", [])}
    pasta_assinaturas = _achar(raiz, "assinaturas")
    linhas_usuarios = _planilha(raiz, "Usuarios.xlsx")
    logins_antigos = {_texto(_col(linha, 0)).lower() for linha in linhas_usuarios} - {""}
    for antigo, novo in renomear.items():
        if antigo not in logins_antigos:
            rel.bloqueios.append(f"--renomear {antigo}={novo}: não há usuário {antigo!r} no sistema antigo")
        if not _LOGIN_VALIDO.match(novo):
            rel.bloqueios.append(f"--renomear {antigo}={novo}: use só letras minúsculas, números, ponto, hífen e sublinhado")
        if novo in existentes or (novo in logins_antigos and novo not in renomear):
            rel.bloqueios.append(f"--renomear {antigo}={novo}: já existe um usuário {novo!r}")
    for linha in linhas_usuarios:
        antigo = _texto(_col(linha, 0)).lower()
        if not antigo:
            continue
        login = renomear.get(antigo, antigo)
        if login in existentes:
            rel.avisos.append(f"usuário {login!r} já existe no sistema novo: mantido como está (não migrado)")
            continue
        existentes.add(login)
        if login != antigo:
            rel.avisos.append(f"usuário {antigo!r} entra com o login {login!r}")
        if not _LOGIN_VALIDO.match(login):
            rel.pendencias.append(f"usuário {login!r}: login com caracteres que o sistema novo não aceita na tela")
        cargo = _texto(_col(linha, 2))
        # Igual ao sistema antigo: planilha sem as colunas de perfil = acesso a tudo; aprovador = cargo de gerente
        sem_perfis = _col(linha, 5) is None

        def marcado(i: int, sem_perfis: bool = sem_perfis, linha: tuple = linha) -> bool:
            return sem_perfis or _texto(_col(linha, i)).upper() == "SIM"

        usuario = Usuario(
            login=login, nome=_texto(_col(linha, 3)) or login, cargo=cargo,
            senha_hash=hash_senha(secrets.token_urlsafe(32)),  # ninguém conhece: o administrador define a provisória
            trocar_senha=True, ativo=True, admin=login in admins,
            pode_aprovar=("gerente" in cargo.lower()) if sem_perfis else _texto(_col(linha, 10)).upper() == "SIM",
            tutorial_visto_em=local_para_utc(data_hora(vistos_tutorial.get(antigo), f"tutorial de {login}", rel)),
            **{f"mod_{m}": marcado(5 + i) for i, m in enumerate(MODULOS)},
        )  # fmt: skip
        nome_assinatura = Path(_texto(_col(linha, 4))).name
        if nome_assinatura and pasta_assinaturas:
            origem = _achar(pasta_assinaturas, nome_assinatura)
            if origem and origem.is_file():
                usuario.assinatura_arquivo = f"assinaturas/{login}{origem.suffix.lower()}"
                plano.copias.append((origem, usuario.assinatura_arquivo))
                rel.bytes_copiados += origem.stat().st_size
            else:
                rel.arquivos_faltando.append(f"assinatura de {login}: {nome_assinatura}")
        if usuario.admin:
            rel.avisos.append(f"usuário {login!r} entra como administrador")
        elif usuario.mod_cadastros:
            rel.avisos.append(f"usuário {login!r} tinha o módulo Cadastros no sistema antigo (lá ele também cadastrava "
                              "usuários). No novo, só administrador cadastra usuários: use --admin se ele deve ser")  # fmt: skip
        plano.usuarios.append(usuario)
    rel.contar("usuarios", len(plano.usuarios))
    migrados = {u.login for u in plano.usuarios}
    for a in sorted(admins - migrados):
        if a in existentes:
            rel.avisos.append(f"--admin {a}: o usuário já existia no sistema novo e não foi alterado pela carga")
        else:
            rel.bloqueios.append(f"--admin {a}: não há esse usuário no sistema antigo (confira o login, ou o --renomear)")
    if plano.usuarios and not any(u.pode_aprovar for u in plano.usuarios):
        rel.avisos.append("nenhum usuário migrado pode aprovar: os relatórios ficarão sem 'Aprovado por'")

    for r in t.get("auditoria", []):
        onde = f"auditoria {r['id']}"
        detalhes = {"origem": "sistema antigo"}
        for chave in ("antes", "depois"):
            valor = _json(r.get(chave), onde, rel)
            if valor:
                detalhes[chave] = valor
        if _texto(r.get("motivo")):
            detalhes["motivo"] = _texto(r.get("motivo"))
        lote_id = r.get("lote_id") or None
        plano.auditoria.append((
            dict(
                quando=local_para_utc(data_hora(r.get("quando"), onde, rel)), login=_texto(r.get("usuario")) or None,
                acao=_texto(r.get("acao")).upper()[:30] or "?", entidade=_texto(r.get("entidade")) or None,
                entidade_id=_texto(r.get("entidade_id"))[:80] or None, lote_id=lote_id if lote_id in ids_lote else None,
                detalhes=detalhes, ip=_texto(r.get("ip"))[:45] or None,
            ),
            # O texto do login fica como foi gravado; o vínculo vai para o usuário novo (já renomeado)
            renomear.get(_texto(r.get("usuario")).lower(), _texto(r.get("usuario")).lower()),
        ))  # fmt: skip
    rel.contar("auditoria", len(plano.auditoria))

    # --- arquivos da pasta de dados que nenhum registro usa: copiados no mesmo caminho relativo, porque o
    # sistema antigo os usa por convenção de pasta (databooks gerados, fotos do visual, gráficos do forno)
    ignorar = re.compile(r"(^sistema.*\.db$|\.cfg$|\.log$|-journal$|-wal$|-shm$|^_cadastro_.*_upload)", re.IGNORECASE)
    for p in sorted((raiz / pasta_dados).rglob("*")):
        relativo = p.relative_to(raiz / pasta_dados).as_posix() if p.is_file() else ""
        if not relativo or ignorar.search(p.name) or relativo.lower().startswith("_mockup"):
            continue
        if relativo.lower() not in referenciados:
            pasta = "/".join(relativo.split("/")[:1]) + ("/<id>/" + relativo.split("/")[2] if relativo.count("/") >= 3 else "")
            rel.nao_referenciados[pasta] = rel.nao_referenciados.get(pasta, 0) + 1
            plano.copias.append((p, relativo))
            rel.bytes_copiados += p.stat().st_size

    # --- recursos: desenhos, instruções, imagens dos relatórios, modelos de documento e todos os databooks
    def copiar_pasta(origem: Path | None, destino: str, padrao: str = "*") -> int:
        if not origem or not origem.is_dir():
            return 0
        n = 0
        for p in sorted(origem.rglob(padrao)):
            if p.is_file():
                plano.copias.append((p, f"{destino}/{p.relative_to(origem).as_posix()}"))
                rel.bytes_copiados += p.stat().st_size
                n += 1
        return n

    rel.contar("recursos: desenhos", copiar_pasta(_achar(raiz, "Desenhos_Chavetas"), "recursos/desenhos", "*.pdf"))
    rel.contar("recursos: instruções", copiar_pasta(_achar(raiz, "Instruções_Qualidade"), "recursos/instrucoes", "*.pdf"))
    rel.contar("recursos: imagens", copiar_pasta(_achar(raiz, "relatorios_assets"), "recursos/relatorios"))
    modelos = [p for p in raiz.glob("*.docx") if not p.name.startswith("~$")] if raiz.is_dir() else []
    for p in modelos:
        plano.copias.append((p, f"recursos/modelos/{p.name}"))
        rel.bytes_copiados += p.stat().st_size
    rel.contar("recursos: modelos", len(modelos))
    ja_copiados = {destino for _, destino in plano.copias}
    pasta_db = _achar(raiz, pasta_databook)
    n_db = 0
    for p in sorted(pasta_db.rglob("*")) if pasta_db and pasta_db.is_dir() else []:
        destino = f"databooks/{p.relative_to(pasta_db).as_posix()}"
        if p.is_file() and destino not in ja_copiados:
            plano.copias.append((p, destino))
            rel.bytes_copiados += p.stat().st_size
            n_db += 1
    rel.contar("recursos: databooks", n_db)

    # --- parâmetros (nome da empresa, endereço, cliente...) de um arquivo LOCAL, fora do Git
    arquivo_parametros = _achar(raiz, "parametros_acokey.json")
    if arquivo_parametros:
        try:
            valores = json.loads(arquivo_parametros.read_text(encoding="utf-8"))
        except ValueError:
            rel.bloqueios.append(f"{arquivo_parametros.name}: JSON inválido")
            valores = {}
        plano.grupos.append([Parametro(chave=str(k)[:60], valor=str(v), alterado_por="(carga)") for k, v in valores.items()])
        rel.contar("parametros", len(valores))
    else:
        rel.avisos.append("parametros_acokey.json não encontrado: preencha os Parâmetros (empresa, cliente...) pela tela")
    rel.arquivos_copiados = len(plano.copias)
    return plano


def _banco_vazio(db: Session) -> bool:
    """Sem lotes, matéria-prima nem OPs digitadas. OPs trazidas pelo Mega não contam: a busca pode rodar antes da
    carga, e a planilha completa essas OPs (ver `_juntar_ops_do_mega`)."""
    if any(db.scalar(select(func.count()).select_from(m)) for m in (Lote, MateriaPrima)):
        return False
    return not db.scalar(select(func.count()).select_from(OrdemProducao).where(OrdemProducao.origem != "mega"))


_CAMPOS_PLANILHA_OP = ("cliente", "coditem", "descricao", "tipo", "data_faturamento", "nf", "piv", "qt_lote",
                       "qt_faturada", "projeto", "po")  # fmt: skip


def _juntar_ops_do_mega(db: Session, plano: Plano, rel: Relatorio) -> None:
    """OP da planilha que o Mega já trouxe: o que a Qualidade digitou na planilha vai para a OP existente
    (campo preenchido na planilha prevalece) e ela deixa de ser inserida de novo."""
    do_mega = {o.op: o for o in db.scalars(select(OrdemProducao).where(OrdemProducao.origem == "mega"))}
    if not do_mega:
        return
    juntadas = 0
    for grupo in plano.grupos:
        for objeto in [o for o in grupo if isinstance(o, OrdemProducao) and o.op in do_mega]:
            existente = do_mega[objeto.op]
            for campo in _CAMPOS_PLANILHA_OP:
                valor = getattr(objeto, campo)
                if valor not in (None, ""):
                    setattr(existente, campo, valor)
            existente.origem = "planilha"
            grupo.remove(objeto)
            juntadas += 1
    if juntadas:
        rel.avisos.append(f"{juntadas} OP(s) da planilha já tinham vindo do Mega: os dados da planilha foram juntados a elas")


def _acertar_sequencias(db: Session) -> None:
    """No PostgreSQL, depois de gravar com os ids do sistema antigo, a numeração automática continua do maior id."""
    if db.get_bind().dialect.name != "postgresql":
        return
    for tabela in ("especificacoes_cotas", "materias_primas", "materias_primas_anexos", "lotes", "registros", "anexos",
                   "eventos", "nao_conformidades", "cargas_tt", "cargas_tt_lotes", "envios_prestador",
                   "envios_prestador_lotes", "envios_prestador_fotos", "ordens_faturamento", "ordens_faturamento_lotes",
                   "databooks_enviados"):  # fmt: skip
        db.execute(text(f"SELECT setval(pg_get_serial_sequence('{tabela}', 'id'), COALESCE((SELECT MAX(id) FROM {tabela}), 1))"))


def executar(
    db: Session,
    raiz: Path,
    pasta_dados: str = "data",
    aplicar: bool = False,
    copiar_arquivos: bool = True,
    renomear: dict[str, str] | None = None,
    admins: set[str] | None = None,
) -> Relatorio:
    rel = Relatorio()
    if not _banco_vazio(db):
        raise ErroCarga("O banco novo já tem lotes, matéria-prima ou OPs digitadas: a carga inicial só roda com ele vazio.")
    plano = montar(db, raiz, pasta_dados, rel, renomear, admins)
    if not aplicar:
        return rel
    if rel.bloqueios:
        raise ErroCarga("Há bloqueios no relatório: nada foi gravado.\n" + rel.texto(aplicado=False))

    _juntar_ops_do_mega(db, plano, rel)
    for grupo in plano.grupos:
        db.add_all(grupo)
        db.flush()
    db.add_all(plano.usuarios)
    db.flush()
    ids_usuario = {u.login: u.id for u in db.scalars(select(Usuario))}
    for campos, login in plano.auditoria:
        if campos["quando"] is None:  # sem data no sistema antigo: fica a hora da carga
            campos = {k: v for k, v in campos.items() if k != "quando"}
        db.add(Auditoria(usuario_id=ids_usuario.get(login), **campos))
    db.add(Auditoria(acao="CARGA_INICIAL", entidade="sistema", login="(linha de comando)",
                     detalhes={"pasta_dados": pasta_dados, "contagens": rel.contagens}))  # fmt: skip
    db.flush()
    _acertar_sequencias(db)

    if copiar_arquivos:  # antes do commit: se faltar espaço ou permissão, o banco não fica pela metade
        base = config().pasta_arquivos
        for origem, destino in plano.copias:
            alvo = base / destino
            alvo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origem, alvo)
    db.commit()
    return rel


def main() -> None:
    argumentos = argparse.ArgumentParser(description="Carga inicial a partir do sistema antigo (pasta legado/)")
    argumentos.add_argument("raiz", type=Path, help="pasta do sistema antigo (a que tem data/, Usuarios.xlsx...)")
    argumentos.add_argument("--dados", default="data", help="pasta de dados dentro dela: data (produção) ou data_teste")
    argumentos.add_argument("--aplicar", action="store_true", help="grava (sem isto, só confere e mostra o relatório)")
    argumentos.add_argument("--sem-arquivos", action="store_true", help="não copia os arquivos (só para conferência)")
    argumentos.add_argument("--renomear", action="append", default=[], metavar="ANTIGO=NOVO",
                            help="troca o login de um usuário na carga (pode repetir)")  # fmt: skip
    argumentos.add_argument("--admin", action="append", default=[], metavar="LOGIN",
                            help="usuário que entra como administrador; use o login NOVO (pode repetir)")  # fmt: skip
    opcoes = argumentos.parse_args()
    renomear = {}
    for par in opcoes.renomear:
        antigo, igual, novo = par.partition("=")
        if not igual or not antigo.strip() or not novo.strip():
            sys.exit(f"--renomear {par!r}: use o formato ANTIGO=NOVO")
        renomear[antigo] = novo

    from app.db import SessionLocal

    with SessionLocal() as db:
        try:
            rel = executar(db, opcoes.raiz, opcoes.dados, opcoes.aplicar, not opcoes.sem_arquivos, renomear, set(opcoes.admin))
        except ErroCarga as erro:
            sys.exit(str(erro))
    print(rel.texto(aplicado=opcoes.aplicar))
    if not opcoes.aplicar:
        print("\nPara gravar, rode de novo com --aplicar." + (" Antes, resolva os BLOQUEIOS." if rel.bloqueios else ""))


if __name__ == "__main__":
    main()
