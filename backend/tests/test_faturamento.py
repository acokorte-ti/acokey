"""Ordem de faturamento: lotes prontos, correção do nº do lote, situações, cliente pelo PIV e PDF."""
from datetime import date, datetime

import pymupdf
from conftest import lote_exemplo
from sqlalchemy import select

from app import fluxo, parametros
from app.config import agora_local
from app.expedicao import lote_com_qtd, lote_completo
from app.models import Auditoria, Evento, Lote, NaoConformidade, OrdemFaturamento, OrdemProducao, Registro

ANO = agora_local().year


def _h(csrf: str) -> dict:
    return {"X-CSRF-Token": csrf}


def _pronto(db, lote: Lote) -> Lote:
    """Aprova todas as etapas aplicáveis ao tipo do lote."""
    for etapa in fluxo.ETAPAS:
        if etapa.aplicavel(lote.tipo):
            for sub in etapa.subs_de(lote.tipo):
                db.add(Registro(lote_id=lote.id, etapa=etapa.chave, sub=sub, status="aprovado", quando=datetime(2026, 11, 21, 9)))
    db.commit()
    return lote


def _corpo(*lote_ids, **extra):
    return {"data_emissao": "2026-11-24", "cliente": "CLIENTE EXEMPLO", "pedido_cliente": "PO-1", "piv": "80001",
            "destinatario": "Fulano <fulano@exemplo.com>", "observacoes": "Embalagem especial",
            "itens": [{"lote_id": i, "volumes": 2, "peso_liq": "12,5", "peso_bruto": 13.75} for i in lote_ids], **extra}  # fmt: skip


def test_formato_do_lote_da_of():
    assert lote_completo("900001", date(2026, 11, 20)) == "26-4-900001"
    assert lote_completo("26-4-900001", date(2025, 2, 1)) == "26-4-900001"
    assert lote_com_qtd("900001", 72, date(2026, 5, 2)) == "26-2-900001 (72 Peças)"


def test_lotes_disponiveis_mostram_prontos_e_bloqueados_com_motivo(cliente, admin, db):
    pronto = _pronto(db, lote_exemplo(db))
    pendente = lote_exemplo(db, numero="26-4-900002", op="900002")
    com_nc = _pronto(db, lote_exemplo(db, numero="26-4-900003", op="900003"))
    db.add(NaoConformidade(numero="NC-2026-901", lote_id=com_nc.id, status="em_tratamento"))
    db.add(OrdemProducao(op="900001", cliente="CLIENTE EXEMPLO LTDA", piv="80001", po="PO-9", coditem="123456"))
    db.commit()
    lotes = {x["id"]: x for x in cliente.get("/api/faturamento/lotes-disponiveis").json()["lotes"]}
    assert lotes[pronto.id]["pronto"] is True and lotes[pronto.id]["motivos"] == []
    assert lotes[pronto.id]["piv"] == "80001" and lotes[pronto.id]["pedido_cliente"] == "PO-9" and lotes[pronto.id]["cliente"] == "CLIENTE"
    assert lotes[pronto.id]["lote_com_qtd"] == "26-4-900001 (72 Peças)"
    assert lotes[pendente.id]["pronto"] is False and lotes[pendente.id]["motivos"] == ["etapa pendente: Receb. MP"]
    assert lotes[com_nc.id]["motivos"] == ["1 NC aberta(s)"]


def test_criar_of_com_lote_pronto(cliente, admin, db):
    lote = _pronto(db, lote_exemplo(db))
    r = cliente.post("/api/faturamento", json=_corpo(lote.id), headers=_h(admin))
    assert r.status_code == 201, r.text
    assert r.json()["numero"] == f"OF-{ANO}-001"
    d = cliente.get(f"/api/faturamento/{r.json()['id']}").json()
    assert d["status"] == "rascunho" and d["pode_editar"] is True and d["proximos"] == ["emitida", "cancelada"]
    item = d["itens"][0]
    assert item["qtd_faturada"] == 72 and item["qtd"] == 72  # sem qtd liberada, vai o lote inteiro
    assert item["lote_com_qtd"] == "26-4-900001 (72 Peças)" and item["peso_liq"] == 12.5 and item["peso_bruto"] == 13.75
    assert d["totais"] == {"qtd": 72, "qtd_faturada": 72, "volumes": 2, "peso_liq": 12.5, "peso_bruto": 13.75}
    assert d["criado_por"] == "Administrador"
    assert any(f"OF-{ANO}-001" in t for t in db.scalars(select(Evento.texto).where(Evento.lote_id == lote.id)))
    assert db.scalar(select(Auditoria).where(Auditoria.acao == "CRIAR", Auditoria.entidade == "ordem_faturamento")) is not None

    lista = cliente.get("/api/faturamento").json()
    assert lista["contagens"] == {"ativas": 1, "faturadas": 0, "canceladas": 0}
    assert lista["itens"][0]["total_pecas"] == 72 and lista["itens"][0]["total_volumes"] == 2


def test_lote_com_pendencia_nao_entra(cliente, admin, db):
    pendente = lote_exemplo(db)
    r = cliente.post("/api/faturamento", json=_corpo(pendente.id), headers=_h(admin))
    assert r.status_code == 422 and "ainda não está pronto" in r.json()["detail"] and "Receb. MP" in r.json()["detail"]
    assert cliente.post("/api/faturamento", json=_corpo(), headers=_h(admin)).status_code == 422
    lote = _pronto(db, lote_exemplo(db, numero="26-4-900002", op="900002"))
    corpo = _corpo(lote.id)
    corpo["itens"][0]["qtd_faturada"] = -1
    assert cliente.post("/api/faturamento", json=corpo, headers=_h(admin)).status_code == 422
    corpo["itens"][0].update(qtd_faturada=60, peso_liq="dez")
    r = cliente.post("/api/faturamento", json=corpo, headers=_h(admin))
    assert r.status_code == 422 and "Peso inválido" in r.json()["detail"]
    assert db.scalar(select(OrdemFaturamento)) is None


def test_correcao_do_numero_do_lote_na_of(cliente, admin, db, como):
    lote = _pronto(db, lote_exemplo(db, numero="900001"))
    outro = lote_exemplo(db, numero="26-4-900009", op="900009")
    # Número que já é de outro lote: recusa e não grava nada (nem a OF, nem a correção)
    corpo = _corpo(lote.id)
    corpo["itens"][0]["numero_corrigido"] = outro.numero
    r = cliente.post("/api/faturamento", json=corpo, headers=_h(admin))
    assert r.status_code == 409 and "Já existe outro lote" in r.json()["detail"]
    assert db.scalar(select(OrdemFaturamento)) is None
    # Sem senha administrativa: quem tem o módulo corrige
    usinagem, csrf = como(modulos=["producao_usinagem"])
    corpo["itens"][0]["numero_corrigido"] = "26-4-900001"
    r = usinagem.post("/api/faturamento", json=corpo, headers=_h(csrf))
    assert r.status_code == 201, r.text
    db.expire_all()
    assert db.get(Lote, lote.id).numero == "26-4-900001"
    registro = db.scalar(select(Auditoria).where(Auditoria.entidade == "lote", Auditoria.acao == "ALTERAR"))
    assert registro.detalhes["numero"] == ["900001", "26-4-900001"] and "OF" in registro.detalhes["motivo"]
    assert registro.lote_id == lote.id and registro.login == "usuario1"
    # Sem mexer no número, nada muda (o antigo completava sozinho o número curto ao salvar)
    lote2 = _pronto(db, lote_exemplo(db, numero="900002", op="900002"))
    assert cliente.post("/api/faturamento", json=_corpo(lote2.id), headers=_h(admin)).status_code == 201
    db.expire_all()
    assert db.get(Lote, lote2.id).numero == "900002"


def test_situacoes_emitir_faturar_trava_e_cancelar(cliente, admin, db):
    lote = _pronto(db, lote_exemplo(db))
    of_id = cliente.post("/api/faturamento", json=_corpo(lote.id), headers=_h(admin)).json()["id"]
    assert cliente.post(f"/api/faturamento/{of_id}/status", json={"status": "faturada"}, headers=_h(admin)).status_code == 409
    assert cliente.post(f"/api/faturamento/{of_id}/status", json={"status": "emitida"}, headers=_h(admin)).status_code == 200
    assert cliente.post(f"/api/faturamento/{of_id}/status", json={"status": "rascunho"}, headers=_h(admin)).status_code == 200
    assert cliente.post(f"/api/faturamento/{of_id}/status", json={"status": "emitida"}, headers=_h(admin)).status_code == 200
    corpo = _corpo(lote.id, observacoes="Entregar na portaria 2")
    assert cliente.put(f"/api/faturamento/{of_id}", json=corpo, headers=_h(admin)).status_code == 200  # emitida ainda edita
    r = cliente.post(f"/api/faturamento/{of_id}/status", json={"status": "faturada", "nf_saida": "NF 12345"}, headers=_h(admin))
    assert r.status_code == 200
    d = cliente.get(f"/api/faturamento/{of_id}").json()
    assert d["status"] == "faturada" and d["nf_saida"] == "NF 12345" and d["pode_editar"] is False and d["proximos"] == []
    # Faturada fica travada
    assert cliente.put(f"/api/faturamento/{of_id}", json=_corpo(lote.id), headers=_h(admin)).status_code == 409
    r = cliente.post(f"/api/faturamento/{of_id}/status", json={"status": "cancelada", "motivo": "Engano no pedido"}, headers=_h(admin))
    assert r.status_code == 409 and "travada" in r.json()["detail"]
    assert any("faturada (NF NF 12345)" in t for t in db.scalars(select(Evento.texto).where(Evento.lote_id == lote.id)))

    outra = cliente.post("/api/faturamento", json=_corpo(lote.id), headers=_h(admin)).json()["id"]
    r = cliente.post(f"/api/faturamento/{outra}/status", json={"status": "cancelada"}, headers=_h(admin))
    assert r.status_code == 422 and "motivo" in r.json()["detail"]
    cancelar = {"status": "cancelada", "motivo": "Lançada em duplicidade"}
    r = cliente.post(f"/api/faturamento/{outra}/status", json=cancelar, headers=_h(admin))
    assert r.status_code == 200
    d = cliente.get(f"/api/faturamento/{outra}").json()
    assert d["status"] == "cancelada" and d["cancelado_motivo"] == "Lançada em duplicidade" and d["cancelado_por"] == "Administrador"
    assert cliente.post(f"/api/faturamento/{outra}/status", json={"status": "rascunho"}, headers=_h(admin)).status_code == 409
    assert cliente.get("/api/faturamento?aba=canceladas").json()["contagens"] == {"ativas": 0, "faturadas": 1, "canceladas": 1}
    acoes = db.scalars(select(Auditoria.acao).where(Auditoria.entidade == "ordem_faturamento")).all()
    assert {"CRIAR", "STATUS", "ALTERAR", "CANCELAR"} <= set(acoes)


def test_emitir_confere_de_novo_as_pendencias(cliente, admin, db):
    lote = _pronto(db, lote_exemplo(db))
    of_id = cliente.post("/api/faturamento", json=_corpo(lote.id), headers=_h(admin)).json()["id"]
    db.add(NaoConformidade(numero="NC-2026-950", lote_id=lote.id, status="aberta"))
    db.commit()
    r = cliente.post(f"/api/faturamento/{of_id}/status", json={"status": "emitida"}, headers=_h(admin))
    assert r.status_code == 409 and "26-4-900001" in r.json()["detail"] and "NC aberta" in r.json()["detail"]
    # Na edição, o lote que ficou bloqueado vem na lista (para poder tirar) e não deixa salvar
    lotes = cliente.get(f"/api/faturamento/lotes-disponiveis?of_id={of_id}").json()["lotes"]
    assert next(x for x in lotes if x["id"] == lote.id)["pronto"] is False
    assert cliente.put(f"/api/faturamento/{of_id}", json=_corpo(lote.id), headers=_h(admin)).status_code == 422


def test_editar_troca_lotes_e_marca_em_outra_of(cliente, admin, db):
    a = _pronto(db, lote_exemplo(db))
    b = _pronto(db, lote_exemplo(db, numero="26-4-900002", op="900002", qtd=10))
    of_id = cliente.post("/api/faturamento", json=_corpo(a.id), headers=_h(admin)).json()["id"]
    corpo = _corpo(b.id, a.id, cliente="CLIENTE NOVO")
    corpo["itens"][0]["qtd_faturada"] = 8
    assert cliente.put(f"/api/faturamento/{of_id}", json=corpo, headers=_h(admin)).status_code == 200
    d = cliente.get(f"/api/faturamento/{of_id}").json()
    assert [i["lote_id"] for i in d["itens"]] == [b.id, a.id] and d["itens"][0]["qtd_faturada"] == 8 and d["cliente"] == "CLIENTE NOVO"
    alteracao = db.scalars(select(Auditoria).where(Auditoria.acao == "ALTERAR", Auditoria.entidade == "ordem_faturamento")).all()[-1]
    assert alteracao.detalhes["cliente"] == ["CLIENTE EXEMPLO", "CLIENTE NOVO"]
    assert alteracao.detalhes["lotes"] == [["26-4-900001"], ["26-4-900001", "26-4-900002"]]
    assert cliente.put(f"/api/faturamento/{of_id}", json=_corpo(b.id), headers=_h(admin)).status_code == 200
    assert any("retirado da ordem" in t for t in db.scalars(select(Evento.texto).where(Evento.lote_id == a.id)))

    cliente.post(f"/api/faturamento/{of_id}/status", json={"status": "emitida"}, headers=_h(admin))
    lotes = {x["id"]: x for x in cliente.get("/api/faturamento/lotes-disponiveis").json()["lotes"]}
    assert lotes[b.id]["ja_faturado"] is True and lotes[a.id]["ja_faturado"] is False
    # Na própria OF, o lote não aparece como "já em outra OF"
    lotes = {x["id"]: x for x in cliente.get(f"/api/faturamento/lotes-disponiveis?of_id={of_id}").json()["lotes"]}
    assert lotes[b.id]["ja_faturado"] is False


def test_cliente_pelo_piv(cliente, admin, db):
    db.add(OrdemProducao(op="900001", cliente="", piv="80001"))
    db.add(OrdemProducao(op="900002", cliente="CLIENTE EXEMPLO LTDA", piv="80001"))
    db.commit()
    assert cliente.get("/api/faturamento/cliente-por-piv?piv=80001").json() == {"cliente": "CLIENTE EXEMPLO LTDA"}
    assert cliente.get("/api/faturamento/cliente-por-piv?piv=99999").json() == {"cliente": ""}
    assert cliente.get("/api/faturamento/cliente-por-piv").json() == {"cliente": ""}


def test_pdf_da_of_e_documento_interno(cliente, admin, db):
    lote = _pronto(db, lote_exemplo(db, numero="900001"))
    curto = _pronto(db, lote_exemplo(db, numero="900002", op="900002", qtd=10))
    parametros.gravar(db, "cliente_nome", "CLIENTE PADRAO EXEMPLO", "admin")
    db.commit()
    corpo = _corpo(lote.id, curto.id, cliente="")
    corpo["itens"][0]["qtd_faturada"] = 70
    of_id = cliente.post("/api/faturamento", json=corpo, headers=_h(admin)).json()["id"]
    r = cliente.get(f"/api/faturamento/{of_id}/pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and r.headers["content-type"] == "application/pdf"
    with pymupdf.open(stream=r.content, filetype="pdf") as documento:
        texto = "\n".join(p.get_text() for p in documento)
    for esperado in ("ORDEM DE FATURAMENTO", f"OF-{ANO}-001", "CLIENTE PADRAO EXEMPLO", "26-4-900001 (72 Peças)",
                     "26-4-900002 (10 Peças)", "Qtd lote", "Qtd lib.", "Totais", "12,50 kg", "PO-1", "80001", "Qualidade",
                     "PCP / Expedição", "Faturamento"):  # fmt: skip
        assert esperado in texto, esperado
    assert db.scalar(select(Auditoria).where(Auditoria.acao == "GERAR_PDF", Auditoria.entidade == "ordem_faturamento")) is not None


def test_quem_nao_tem_o_modulo_nao_acessa(cliente, admin, db, como):
    lote = _pronto(db, lote_exemplo(db))
    of_id = cliente.post("/api/faturamento", json=_corpo(lote.id), headers=_h(admin)).json()["id"]
    pcp, csrf = como(modulos=["pcp", "cadastros"])
    for caminho in ("/api/faturamento", "/api/faturamento/opcoes", "/api/faturamento/lotes-disponiveis", f"/api/faturamento/{of_id}",
                    f"/api/faturamento/{of_id}/pdf", "/api/faturamento/cliente-por-piv?piv=1"):  # fmt: skip
        assert pcp.get(caminho).status_code == 403, caminho
    assert pcp.post("/api/faturamento", json=_corpo(lote.id), headers=_h(csrf)).status_code == 403
    assert pcp.put(f"/api/faturamento/{of_id}", json=_corpo(lote.id), headers=_h(csrf)).status_code == 403
    assert pcp.post(f"/api/faturamento/{of_id}/status", json={"status": "emitida"}, headers=_h(csrf)).status_code == 403
    tt, csrf_tt = como(modulos=["producao_tt"])
    assert tt.post(f"/api/faturamento/{of_id}/status", json={"status": "emitida"}, headers=_h(csrf_tt)).status_code == 200
