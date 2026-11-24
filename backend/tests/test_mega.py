"""Integração com o Mega: desligada por padrão, sem nenhum segredo no código, e a busca das OPs com a consulta
simulada (nenhum teste conecta no Oracle). Dados fictícios."""
from datetime import datetime

import pytest
from sqlalchemy import select

from app import mega
from app.config import config
from app.models import Auditoria, OrdemProducao, Parametro
from app.ordens_producao import classificar


def test_mega_comeca_desligado():
    pronto, motivo = mega.situacao()
    assert not pronto and "desligada" in motivo


def test_testar_sem_configuracao_avisa_e_nao_conecta(monkeypatch):
    monkeypatch.setattr(config(), "mega_dsn", "")
    with pytest.raises(SystemExit, match="ainda não estão no .env"):
        mega.testar()


def test_mensagem_de_erro_nao_mostra_dados_da_conexao():
    erro = Exception("DPY-6005: cannot connect to database (CONNECTION_ID=abc). usuario/senha@host:1521/servico")
    assert mega._mensagem_publica(erro).startswith("DPY-6005")
    assert mega._mensagem_publica(Exception("senha errada em host")) == "Exception"


# ---------------------------------------------------------------- busca das OPs


def test_classificar_segue_a_ordem_do_sistema_antigo():
    assert classificar("CHAVETA PIN SPARK 4.1/2") == "PIN"  # tem ARK no meio, mas PIN vem antes
    assert classificar("chaveta box mark") == "BOX"
    assert classificar("CHAVETA ARK 7") == "ARK"
    assert classificar("PARAFUSO") is None and classificar(None) is None


def _op(op, item="90001", desc="CHAVETA DE TRAVAMENTO PIN", situacao="AB", qtde=72.0, pedido=9001, cliente="CLIENTE MEGA"):
    """Uma linha como a consulta de OPs devolve."""
    return {"OP": op, "ITEM": item, "DESCRICAO": desc, "SITUACAO": situacao, "QTDE": qtde, "CLIENTE": cliente, "PEDIDO": pedido}


def _nota(pedido=9001, item="90001", nf=None, data=None, qtd=None, po="PO-EXEMPLO", seq_item=1, nota_id=None, seq_nota=1):
    """Uma linha como a consulta de itens de pedido e notas devolve."""
    return {"PEDIDO": pedido, "ITEM": item, "SERIE": "1", "SEQ_ITEM": seq_item, "PO": po, "NOTA_ID": nota_id or nf,
            "SEQ_ITEM_NOTA": seq_nota, "QTD_NOTA": qtd, "NF": nf, "DATA_NF": data}  # fmt: skip


def test_itens_do_pedido_somam_por_nota_e_ignoram_vinculo_repetido_e_nota_cancelada():
    itens = mega.montar_itens_pedido([
        _nota(nf=800001, data=datetime(2026, 9, 1), qtd=30.0),
        _nota(nf=800001, data=datetime(2026, 9, 1), qtd=12.0, seq_nota=2),  # 2º item da mesma nota
        _nota(nf=800001, data=datetime(2026, 9, 1), qtd=12.0, seq_nota=2),  # mesma linha repetida
        _nota(nf=800002, data=datetime(2026, 9, 20), qtd=30, po="PO-OUTRO", seq_item=2),
        _nota(nf=None, qtd=5),  # vínculo com nota cancelada: não conta
    ])  # fmt: skip
    item = itens[("9001", "90001")]
    assert item.po == "PO-EXEMPLO; PO-OUTRO"
    assert item.lista_notas() == [{"nf": "800001", "data": "2026-09-01", "qtd": 42}, {"nf": "800002", "data": "2026-09-20", "qtd": 30}]
    op = mega.montar_ops([_op(900001), _op(900001, item="outro")])["900001"]  # OP repetida: fica a primeira linha
    assert (op.coditem, op.qtde, op.pedido_origem, op.cliente) == ("90001", 72, "9001", "CLIENTE MEGA")


def _aplicar(db, ops, notas=()):
    resumo = mega.aplicar(db, mega.montar_ops(ops), mega.montar_itens_pedido(list(notas)))
    db.commit()
    return resumo


def _cadastro(db, op):
    return db.scalar(select(OrdemProducao).where(OrdemProducao.op == op))


def test_op_existente_so_recebe_o_que_esta_vazio_e_a_diferenca_fica_registrada(db):
    db.add(Parametro(chave="especificacao_codigo", valor="ESPEC-EXEMPLO/1", alterado_por="teste"))
    db.add(OrdemProducao(op="900001", origem="planilha", cliente="Cliente Exemplo", coditem="90009", descricao="",
                         tipo="BOX", qt_lote=50, projeto="ESPEC-EXEMPLO/0", nf="800777", piv=""))  # fmt: skip
    db.add(OrdemProducao(op="900002", origem="planilha", cliente="", coditem="90001", descricao="CHAVETA DE TRAVAMENTO PIN"))
    db.commit()
    resumo = _aplicar(db, [_op(900001), _op(900002, qtde=10)], [_nota(nf=800001, data=datetime(2026, 9, 1), qtd=50)])
    assert resumo.novas == [] and set(resumo.atualizadas) == {"900001", "900002"}
    assert resumo.divergentes == {"900001": ["coditem", "tipo"]}
    digitada = _cadastro(db, "900001")
    assert (digitada.coditem, digitada.tipo, digitada.qt_lote, digitada.projeto) == ("90009", "BOX", 50, "ESPEC-EXEMPLO/0")
    assert digitada.descricao == "CHAVETA DE TRAVAMENTO PIN"  # estava vazia
    assert digitada.piv == "" and digitada.nf == "800777" and digitada.po == ""  # PIV, NF e PO nunca vêm do pedido de origem
    assert digitada.situacao_op == "AB" and digitada.origem == "planilha" and digitada.sincronizado_em is not None
    dados = digitada.dados_mega
    assert dados["coditem"] == "90001" and dados["pedido_origem"] == "9001" and dados["pedido_notas"] == "9001"
    assert dados["notas_do_piv"] is False and dados["ops_mesmo_pedido"] == 2 and dados["notas"][0]["nf"] == "800001"
    outra = _cadastro(db, "900002")
    assert outra.cliente == "Cliente Exemplo" and outra.qt_lote == 10  # o nome do Mega vira o que a Qualidade usa


def test_com_piv_digitado_as_notas_e_o_po_vem_dele_e_nao_do_pedido_de_origem(db):
    db.add(OrdemProducao(op="900001", origem="planilha", coditem="90001", piv="9555", po=""))
    db.commit()
    notas = [_nota(pedido=9001, nf=800001, data=datetime(2026, 9, 1), qtd=72, po="PO-ORIGEM"),
             _nota(pedido=9555, nf=800555, data=datetime(2026, 10, 5), qtd=72, po="PO-FATURADO")]  # fmt: skip
    _aplicar(db, [_op(900001, pedido=9001)], notas)
    op = _cadastro(db, "900001")
    assert op.piv == "9555" and op.po == "PO-FATURADO" and op.nf == ""
    assert op.dados_mega["pedido_notas"] == "9555" and op.dados_mega["notas_do_piv"] is True
    assert [n["nf"] for n in op.dados_mega["notas"]] == ["800555"] and op.dados_mega["pedido_origem"] == "9001"


def test_op_nova_so_entra_aberta_e_com_tipo(db):
    db.add(Parametro(chave="especificacao_codigo", valor="ESPEC-EXEMPLO/1", alterado_por="teste"))
    db.add(OrdemProducao(op="900001", origem="planilha", descricao="digitada", nf=""))
    db.commit()
    resumo = _aplicar(db, [
        _op(900001, situacao="CA"),
        _op(900003, situacao="EN"),  # encerrada e nunca cadastrada: histórico, não entra
        _op(900004, situacao="CA"),
        _op(900005, item="90002", desc="CHAVETA ANTI-ROTACIONAL BOX", pedido=None),
        _op(900006, desc="ANEL DE TRAVAMENTO"),  # não dá PIN, BOX nem ARK
    ])  # fmt: skip
    assert resumo.novas == ["900005"] and resumo.fechadas_ignoradas == 2 and resumo.sem_tipo_ignoradas == 1
    cancelada = _cadastro(db, "900001")
    assert cancelada.situacao_op == "CA" and cancelada.descricao == "digitada" and cancelada.dados_mega["notas"] == []
    nova = _cadastro(db, "900005")
    assert nova.origem == "mega" and nova.tipo == "BOX" and nova.qt_lote == 72 and nova.cliente == "CLIENTE MEGA"
    assert nova.projeto == "ESPEC-EXEMPLO/1" and nova.piv == "" and nova.po == "" and nova.dados_mega["pedido_notas"] is None


def test_sincronizar_audita_simulacao_nao_grava_e_consulta_vazia_nao_apaga(db, monkeypatch):
    chamadas = []
    monkeypatch.setattr(mega, "ler", lambda itens, pivs: chamadas.append((itens, pivs)) or ([_op(900001)], []))
    resumo = mega.sincronizar(db, simular=True)
    assert resumo.novas == ["900001"] and db.scalar(select(OrdemProducao)) is None
    assert db.scalar(select(Auditoria).where(Auditoria.acao == mega.ACAO_AUDITORIA)) is None
    mega.sincronizar(db)
    auditoria = db.scalar(select(Auditoria).where(Auditoria.acao == mega.ACAO_AUDITORIA))
    assert auditoria.detalhes["novas"] == 1 and auditoria.detalhes["ops_novas"] == ["900001"]
    assert auditoria.login == "(agendador)" and mega.ultima_busca(db)["novas"] == 1
    _cadastro(db, "900001").piv = "9555"
    db.commit()
    mega.sincronizar(db)
    assert chamadas[-1] == (["90001"], ["9555"])  # itens e PIVs já cadastrados também entram na consulta
    monkeypatch.setattr(mega, "ler", lambda itens, pivs: ([], []))
    with pytest.raises(mega.MegaIndisponivel, match="não devolveu nenhuma OP"):
        mega.sincronizar(db)


def test_consultas_so_levam_inteiros_conferidos_e_termos_como_parametro(monkeypatch):
    sql, parametros_sql = mega.consulta_ops(["90001", "90002", "X' OR 1=1 --", ""])
    assert "o.PRO_IN_CODIGO IN (90001, 90002)" in sql and "1=1" not in sql
    assert parametros_sql["termo0"] == "%TRAVAMENTO%" and parametros_sql["filial"] == 3
    assert "UPPER(p.PRO_ST_DESCRICAO) LIKE :termo0" in sql and "ACOKORTE.PRO_ORDENS" in sql
    notas = mega.consulta_notas(mega._inteiros(["9001", "9001", "x'--", 9002.0]), list(range(1, 1902)))
    assert "ip.PED_IN_CODIGO IN (9001, 9002)" in notas and "--" not in notas
    assert notas.count("ip.PRO_IN_CODIGO IN (") == 3  # 1901 itens: blocos de 900 (o Oracle aceita até 1000)
    assert "l.PE_ORG_TAB_IN_CODIGO = ip.ORG_TAB_IN_CODIGO" in notas and "n.ORG_IN_CODIGO = l.NF_ORG_IN_CODIGO" in notas
    monkeypatch.setattr(config(), "mega_esquema", "ACOKORTE; DROP")
    with pytest.raises(mega.MegaIndisponivel, match="MEGA_ESQUEMA"):
        mega.consulta_ops([])


# ---------------------------------------------------------------- rotas


def test_rotas_da_busca_no_mega(como, monkeypatch):
    cadastros, csrf = como(modulos=["cadastros"])
    qualidade, csrf_q = como(modulos=["qualidade"])
    h = {"X-CSRF-Token": csrf}
    assert qualidade.get("/api/ordens-producao/mega").status_code == 403
    assert qualidade.post("/api/ordens-producao/buscar-mega", headers={"X-CSRF-Token": csrf_q}).status_code == 403
    estado = cadastros.get("/api/ordens-producao/mega").json()
    assert estado["pronto"] is False and "desligada" in estado["motivo"] and estado["ultima"] is None
    r = cadastros.post("/api/ordens-producao/buscar-mega", headers=h)
    assert r.status_code == 409 and "desligada" in r.json()["detail"]

    monkeypatch.setattr(mega, "situacao", lambda: (True, ""))
    monkeypatch.setattr(mega, "ler", lambda itens, pivs: ([_op(900001)], [_nota(nf=800001, data=datetime(2026, 9, 1), qtd=72)]))
    r = cadastros.post("/api/ordens-producao/buscar-mega", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["novas"] == ["900001"] and "1 OP(s) nova(s)" in r.json()["mensagem"]
    op = cadastros.get("/api/ordens-producao").json()[0]
    assert op["origem"] == "mega" and op["dados_mega"]["notas"] == [{"nf": "800001", "data": "2026-09-01", "qtd": 72}]
    ultima = cadastros.get("/api/ordens-producao/mega").json()["ultima"]
    assert ultima["novas"] == 1 and ultima["por"] == "usuario1" and ultima["erro"] is None

    def quebra(itens, pivs):
        raise RuntimeError("ORA-01017: invalid username/password; logon denied")

    monkeypatch.setattr(mega, "ler", quebra)
    r = cadastros.post("/api/ordens-producao/buscar-mega", headers=h)
    assert r.status_code == 502 and "ORA-01017" in r.json()["detail"]
    assert cadastros.get("/api/ordens-producao/mega").json()["ultima"]["erro"].startswith("ORA-01017")

    monkeypatch.setattr(mega, "ler", lambda itens, pivs: ([_op(900001)], []))
    monkeypatch.setattr(mega, "aplicar", lambda db, ops, itens: (_ for _ in ()).throw(ValueError("detalhe interno")))
    r = cadastros.post("/api/ordens-producao/buscar-mega", headers=h)
    assert r.status_code == 502 and "detalhe interno" not in r.json()["detail"] and "log do servidor" in r.json()["detail"]
