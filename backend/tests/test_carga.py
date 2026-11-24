"""Carga do sistema antigo, com uma cópia em miniatura dele montada no teste (nada de dado real)."""
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import func, select

from app import carga
from app.models import Anexo, Auditoria, DatabookEnviado, EspecificacaoTipo, Evento, Lote, OrdemProducao, Registro, Usuario
from app.seguranca import verificar_senha

ESQUEMA_ANTIGO = """
create table lotes(id integer primary key, op text, lote text unique, tipo text, qtd integer, corrida text default '',
  criado text, etapa integer default 0, etapa_desde text, coditem text default '');
create table registros(id integer primary key, lote_id integer, etapa text, sub text default '', status text, dados text,
  quando text, resp text, anulado integer default 0, anulado_motivo text default '', anulado_em text default '',
  anulado_por text default '');
create table anexos(id integer primary key, lote_id integer, etapa text, sub text default '', nome text, arquivo text,
  quando text, apenas_registro integer default 0);
create table eventos(id integer primary key, lote_id integer, quando text, texto text);
create table spec_tipo(tipo text primary key, dureza_min text default '', dureza_max text default '', tr_le_min text default '',
  tr_le_max text default '', tr_lr_min text default '', tr_lr_max text default '', tr_al_min text default '',
  tr_ra_min text default '', ch_temp text default '', ch_med_min text default '', ch_ind_min text default '',
  ch_dim_cp text default '');
create table materia_prima(id integer primary key, nf_entrada text default '', corrida text default '',
  fornecedor text default '', tipo_destino text default '', data_recebimento text default '', qt_fund integer default 0,
  qt_real integer default 0, qt_ok integer default 0, qt_rej integer default 0, qt_retrab integer default 0,
  qt_cp_tt integer default 0, observacoes text default '', criado text default '', resp text default '',
  status text default 'pendente', aprovado_por text default '', aprovado_em text default '', obs_aprovacao text default '');
create table databooks_enviados(id integer primary key, op text default '', tipo text default '', lote text default '',
  rev integer default 0, arquivo text, caminho_atual text, data_envio text default '', destinatario text default '',
  nf_saida text default '', observacoes text default '', enviado_em text, enviado_por text default '');
create table auditoria(id integer primary key, quando text, usuario text default '', acao text default '',
  entidade text default '', entidade_id text default '', lote_id integer default 0, antes text default '',
  depois text default '', motivo text default '', ip text default '');
create table tutorial_visto(usuario text primary key, visto_em text default '');
"""
RAIZ_WIN = r"C:\Sistema\ProjetoChavetas"


def _planilha(caminho: Path, linhas: list[list], aba: str | None = None) -> None:
    livro = openpyxl.Workbook()
    folha = livro.active
    if aba:
        folha.title = aba
    folha.append(["cabeçalho"])
    for linha in linhas:
        folha.append(linha)
    livro.save(caminho)


@pytest.fixture
def legado(tmp_path: Path) -> Path:
    raiz = tmp_path / "legado"
    (raiz / "data" / "lotes" / "1" / "anexos").mkdir(parents=True)
    (raiz / "data" / "lotes" / "1" / "anexos" / "cert.pdf").write_bytes(b"%PDF certificado")
    (raiz / "data" / "lotes" / "1" / "databook" / "saida").mkdir(parents=True)
    (raiz / "data" / "lotes" / "1" / "databook" / "saida" / "Databook_x.pdf").write_bytes(b"%PDF gerado")
    (raiz / "data" / "seguranca.cfg").write_text("SENHA_EDICAO=nao-pode-ser-lida")
    (raiz / "DATABOOK" / "Enviados").mkdir(parents=True)
    (raiz / "DATABOOK" / "Enviados" / "Databook_DB-1.pdf").write_bytes(b"%PDF enviado")
    (raiz / "assinaturas").mkdir()
    (raiz / "assinaturas" / "fulano.png").write_bytes(b"\x89PNG assinatura")

    con = sqlite3.connect(raiz / "data" / "sistema.db")
    con.executescript(ESQUEMA_ANTIGO)
    con.execute("insert into materia_prima(id,corrida,status,data_recebimento,criado) values(4,'M999/26','aprovada','2026-11-11','2026-11-16 14:17')")
    con.execute("insert into lotes values(1,'900001','26-4-900001','PIN',72,'M999/26','2026-11-16 18:18',2,'2026-11-17 11:29','4330-01')")
    con.execute("insert into lotes values(2,'900002','26-4-900002','ARK',30,'','2026-11-16 18:19',0,'2026-11-16 18:19','')")
    con.execute("insert into registros(id,lote_id,etapa,sub,status,dados,quando,resp) values(1,1,'receb_mp','','aprovado',?,'2026-11-17 08:40','Fulano')",
                (json.dumps({"report": "pdf"}),))  # fmt: skip
    con.execute("insert into registros(id,lote_id,etapa,sub,status,dados,quando,resp,anulado) values(2,1,'trat_termico','','aprovado','{}','2026-11-17 09:00','Fulano',1)")
    con.execute("insert into anexos values(1,1,'receb_mp','','cert.pdf',?, '2026-11-17 08:50',0)",
                (RAIZ_WIN + r"\data\lotes\1\anexos\cert.pdf",))  # fmt: skip
    con.execute("insert into anexos values(2,1,'receb_mp','','sumiu.pdf',?, '2026-11-17 08:51',0)",
                (RAIZ_WIN + r"\data\lotes\1\anexos\sumiu.pdf",))  # fmt: skip
    con.execute("insert into eventos values(1,0,'2026-11-15 22:39','Login: fulano')")
    con.execute("insert into eventos values(2,1,'2026-11-16 18:18','Lote criado')")
    con.execute("insert into spec_tipo(tipo,dureza_min,dureza_max,tr_al_min,ch_temp,ch_dim_cp) values('PIN','30','39','5','Ambiente','10x7,5x55mm')")
    con.execute("insert into databooks_enviados(id,op,tipo,rev,arquivo,caminho_atual,data_envio,enviado_em) values(1,'900001','PIN',3,'Databook_DB-1.pdf',?,'19/11/2026','2026-11-20 21:14')",
                (RAIZ_WIN + r"\DATABOOK\Enviados\Databook_DB-1.pdf",))  # fmt: skip
    con.execute("insert into auditoria(id,quando,usuario,acao,entidade,entidade_id,lote_id,depois) values(1,'2026-11-21 15:15','fulano','criar','lote','1',1,?)",
                (json.dumps({"lote": "26-4-900001"}),))  # fmt: skip
    con.execute("insert into tutorial_visto values('fulano','2026-11-21 10:00')")
    con.commit()
    con.close()

    _planilha(raiz / "Usuarios.xlsx", [
        ["Fulano", "pbkdf2:sha256:600000$abc$def", "Gerente da Qualidade", "Fulano de Tal", "fulano.png", "SIM", "SIM", "", "", "SIM", "SIM"],
        ["Joao", "texto-puro", "Gerente de Produção", "João", None],  # planilha antiga, sem as colunas de perfil
    ])  # fmt: skip
    _planilha(raiz / "Cadastro_Lote_Cliente.xlsx",
              [["CLIENTE EXEMPLO", 900001, "4330-01", "INSTR. CONTROLE TRAVAMENTO PIN", "pin", None, "", "PIV-9", 72, None, "P1", "PO-1"]],
              aba="Dados")  # fmt: skip
    (raiz / "parametros_acokey.json").write_text('{"cliente_nome": "CLIENTE EXEMPLO"}', encoding="utf-8")
    # Cópia de segurança que o sistema antigo deixava ao lado: não pode ser lida no lugar da atual
    _planilha(raiz / "Cadastro_Lote_Cliente_antes_20261119.xlsx", [["X", 1, "", "", "BOX"]], aba="Dados")
    return raiz


def test_caminho_do_windows_vira_relativo():
    assert carga.relativo_legado(RAIZ_WIN + r"\data\lotes\2\anexos\x.pdf", "data") == "lotes/2/anexos/x.pdf"
    assert carga.relativo_legado(RAIZ_WIN + r"\DATABOOK\Enviados\a.pdf", "DATABOOK") == "Enviados/a.pdf"
    assert carga.relativo_legado(r"D:\outro\lugar\x.pdf", "data") is None
    assert carga.relativo_legado(RAIZ_WIN + r"\data\..\..\segredo.txt", "data") is None


def test_simulacao_nao_grava_nada(db, legado, pasta_arquivos):
    rel = carga.executar(db, legado, aplicar=False)
    assert rel.contagens["lotes"] == 2 and rel.contagens["usuarios"] == 2
    assert not rel.bloqueios
    assert db.scalar(select(func.count(Lote.id))) == 0
    assert not any(pasta_arquivos.iterdir())


def test_carga_grava_mantendo_ids_e_arquivos(db, legado, pasta_arquivos):
    rel = carga.executar(db, legado, aplicar=True)

    lote = db.get(Lote, 1)
    assert lote.numero == "26-4-900001" and lote.materia_prima_id == 4 and lote.etapa_desde.hour == 11
    assert db.get(Registro, 2).anulado is True
    anexo = db.get(Anexo, 1)
    assert anexo.arquivo == "lotes/1/anexos/cert.pdf"
    assert (pasta_arquivos / anexo.arquivo).read_bytes() == b"%PDF certificado"
    assert any("sumiu.pdf" in f for f in rel.arquivos_faltando)
    assert db.get(Anexo, 2) is not None  # o registro fica, para alguém reanexar
    assert rel.nao_referenciados == {"lotes/<id>/databook": 1}  # seguranca.cfg nem entra na conta
    assert (pasta_arquivos / "lotes/1/databook/saida/Databook_x.pdf").exists()  # copiado no mesmo caminho
    assert not (pasta_arquivos / "seguranca.cfg").exists()
    assert rel.contagens["recursos: databooks"] == 0  # o enviado já foi copiado pelo registro de envio
    assert (pasta_arquivos / "databooks/Enviados/Databook_DB-1.pdf").exists()
    assert rel.contagens["recursos: imagens"] == 0 and rel.contagens["parametros"] == 1
    from app import parametros

    assert parametros.ler(db, "cliente_nome") == "CLIENTE EXEMPLO"

    databook = db.get(DatabookEnviado, 1)
    assert databook.caminho == "databooks/Enviados/Databook_DB-1.pdf" and databook.data_envio.isoformat() == "2026-11-19"
    assert (pasta_arquivos / databook.caminho).exists()

    assert [e.texto for e in db.scalars(select(Evento))] == ["Lote criado"]  # o "login" do lote 0 não vira evento
    spec = db.get(EspecificacaoTipo, "PIN")
    assert spec.dureza_min == Decimal("30") and spec.tr_le_min is None and spec.ch_temp == "Ambiente"
    op = db.scalar(select(OrdemProducao))
    assert op.op == "900001" and op.tipo == "PIN" and op.piv == "PIV-9" and op.po == "PO-1"

    fulano = db.scalar(select(Usuario).where(Usuario.login == "fulano"))
    joao = db.scalar(select(Usuario).where(Usuario.login == "joao"))
    assert fulano.modulos == ["qualidade", "pcp", "cadastros"] and fulano.pode_aprovar and not fulano.admin
    assert joao.modulos == ["qualidade", "pcp", "producao_tt", "producao_usinagem", "cadastros"] and joao.pode_aprovar
    for u in (fulano, joao):
        assert u.trocar_senha and u.senha_hash.startswith("$argon2id$")
        assert not verificar_senha(u.senha_hash, "texto-puro")  # nenhuma senha antiga continua valendo
    assert fulano.assinatura_arquivo == "assinaturas/fulano.png" and (pasta_arquivos / "assinaturas/fulano.png").exists()
    assert fulano.tutorial_visto_em is not None

    antiga = db.scalar(select(Auditoria).where(Auditoria.acao == "CRIAR"))
    assert antiga.usuario_id == fulano.id and antiga.lote_id == 1 and antiga.detalhes["origem"] == "sistema antigo"
    assert db.scalar(select(Auditoria).where(Auditoria.acao == "CARGA_INICIAL")) is not None


def test_planilha_de_ops_ignora_copia_de_seguranca_e_bloqueia_se_houver_duas(db, legado):
    rel = carga.executar(db, legado, aplicar=False)
    assert rel.contagens["ordens_producao"] == 1 and not rel.bloqueios  # a "_antes_" foi ignorada
    _planilha(legado / "Cadastro_Lote_Outro.xlsx", [["Y", 2, "", "", "PIN"]], aba="Dados")
    rel = carga.executar(db, legado, aplicar=False)
    assert any("mais de uma planilha de OPs" in b for b in rel.bloqueios)


def test_renomear_login_e_definir_administrador(db, legado, pasta_arquivos):
    rel = carga.executar(db, legado, aplicar=True, renomear={"Fulano": "fulano.tal"}, admins={"fulano.tal"})
    assert not rel.bloqueios
    assert db.scalar(select(Usuario).where(Usuario.login == "fulano")) is None
    novo = db.scalar(select(Usuario).where(Usuario.login == "fulano.tal"))
    assert novo.admin and novo.pode_aprovar and novo.trocar_senha
    assert novo.tutorial_visto_em is not None  # o tutorial era do login antigo
    assert novo.assinatura_arquivo == "assinaturas/fulano.tal.png" and (pasta_arquivos / novo.assinatura_arquivo).exists()
    assert not db.scalar(select(Usuario).where(Usuario.login == "joao")).admin
    antiga = db.scalar(select(Auditoria).where(Auditoria.acao == "CRIAR"))
    assert antiga.usuario_id == novo.id and antiga.login == "fulano"  # o texto da auditoria antiga fica como foi gravado


@pytest.mark.parametrize(
    ("renomear", "admins", "esperado"),
    [
        ({"beltrano": "beltrano.x"}, set(), "não há usuário 'beltrano'"),
        ({"fulano": "Fulano Tal"}, set(), "use só letras minúsculas"),
        ({"fulano": "joao"}, set(), "já existe um usuário 'joao'"),
        ({}, {"ninguem"}, "--admin ninguem"),
        ({"fulano": "fulano.tal"}, {"fulano"}, "--admin fulano"),  # o --admin usa o login NOVO
    ],
)
def test_renomear_e_admin_errados_bloqueiam(db, legado, renomear, admins, esperado):
    rel = carga.executar(db, legado, aplicar=False, renomear=renomear, admins=admins)
    assert any(esperado in b for b in rel.bloqueios), rel.bloqueios


def test_carga_so_roda_com_banco_vazio(db, legado):
    carga.executar(db, legado, aplicar=True, copiar_arquivos=False)
    with pytest.raises(carga.ErroCarga, match="vazio"):
        carga.executar(db, legado, aplicar=True)


def test_especificacao_que_nao_e_numero_bloqueia(db, legado):
    con = sqlite3.connect(legado / "data" / "sistema.db")
    con.execute("update spec_tipo set dureza_max='39 a 40' where tipo='PIN'")
    con.commit()
    con.close()
    rel = carga.executar(db, legado, aplicar=False)
    assert any("dureza_max" in b for b in rel.bloqueios)
    with pytest.raises(carga.ErroCarga, match="bloqueios"):
        carga.executar(db, legado, aplicar=True)
    assert db.scalar(select(func.count(Lote.id))) == 0
