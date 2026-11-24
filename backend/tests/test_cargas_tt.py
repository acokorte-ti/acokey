"""Cargas de tratamento térmico: montar, editar, iniciar, concluir e cancelar. Dados fictícios."""
from datetime import date

from conftest import lote_exemplo
from sqlalchemy import select

from app.models import Auditoria, CargaTT, CargaTTLote, Equipamento, Evento, Registro


def _equipamentos(db) -> None:
    db.add_all([
        Equipamento(codigo="FO-01", descricao="Forno de Têmpera", marca="Marca Exemplo",
                    validade_calibracao=date(2027, 1, 1), certificado="C-1"),
        Equipamento(codigo="FO-02", descricao="Forno de Revenimento", marca="Marca Exemplo"),
        Equipamento(codigo="FO-03", descricao="Forno de têmpera antigo", ativo=False),
    ])  # fmt: skip
    db.commit()


def _aguardando_tt(db, **dados):
    """Lote com a matéria-prima aprovada: a etapa verdadeira dele é o tratamento térmico."""
    lote = lote_exemplo(db, **dados)
    db.add(Registro(lote_id=lote.id, etapa="receb_mp", status="aprovado"))
    db.commit()
    return lote


def _corpo(*lotes, **extra) -> dict:
    return {"forno_tempera_codigo": "FO-01", "forno_revenimento_codigo": "FO-02", "data_planejada": "2026-11-25",
            "observacoes": "Carga noturna", "lote_ids": [lo.id for lo in lotes]} | extra  # fmt: skip


def test_monta_lista_e_detalha_a_carga(db, como):
    _equipamentos(db)
    pin = _aguardando_tt(db)
    box = _aguardando_tt(db, numero="26-4-900002", op="900002", tipo="BOX", qtd=50)
    tt, csrf = como(modulos=["producao_tt"])

    r = tt.get("/api/cargas-tt/formulario")
    assert r.status_code == 200, r.text
    form = r.json()
    assert form["numero_previsto"].startswith("TT-") and form["numero_previsto"].endswith("-001")
    assert [f["codigo"] for f in form["fornos_tempera"]] == ["FO-01"]  # inativo e revenimento ficam de fora
    assert [f["codigo"] for f in form["fornos_revenimento"]] == ["FO-02"]
    assert {d["id"] for d in form["disponiveis"]} == {pin.id, box.id}

    r = tt.post("/api/cargas-tt", json=_corpo(pin, box), headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201, r.text
    criada = r.json()
    assert criada["numero"] == form["numero_previsto"] and criada["aviso"] == ""

    lista = tt.get("/api/cargas-tt").json()
    assert lista["contagens"] == {"ativas": 1, "concluidas": 0, "canceladas": 0}
    item = lista["itens"][0]
    assert item["n_lotes"] == 2 and item["total_pecas"] == 122 and item["forno_tempera_desc"] == "Forno de Têmpera"

    detalhe = tt.get(f"/api/cargas-tt/{criada['id']}").json()
    assert detalhe["status"] == "planejada" and detalhe["criado_por"] == "Fulano de Tal"
    assert [lo["numero"] for lo in detalhe["lotes"]] == ["26-4-900001", "26-4-900002"]
    assert detalhe["lotes"][0]["etapa_atual"] == "Trat. térmico" and detalhe["relatorio"] is None

    # o lote pode entrar em outra carga (têmpera numa, revenimento noutra); a tela mostra em quantas já está
    disponiveis = {d["id"]: d for d in tt.get("/api/cargas-tt/formulario").json()["disponiveis"]}
    assert disponiveis[pin.id]["em_cargas"] == 1
    assert tt.get(f"/api/cargas-tt/do-lote/{pin.id}").json()[0]["numero"] == criada["numero"]

    eventos = db.scalars(select(Evento.texto).where(Evento.lote_id == pin.id)).all()
    assert f"Lote incluído na carga de TT {criada['numero']}" in eventos
    assert db.scalar(select(Auditoria).where(Auditoria.acao == "CRIAR", Auditoria.entidade == "carga_tt")) is not None


def test_valida_lotes_fornos_e_avisa_mistura_com_ark(db, como):
    _equipamentos(db)
    pin = _aguardando_tt(db)
    ark = _aguardando_tt(db, numero="26-4-900003", op="900003", tipo="ARK")
    sem_mp = lote_exemplo(db, numero="26-4-900004", op="900004")  # ainda no recebimento de MP
    qualidade, csrf = como(modulos=["qualidade"])
    cabecalho = {"X-CSRF-Token": csrf}

    r = qualidade.post("/api/cargas-tt", json=_corpo(), headers=cabecalho)
    assert r.status_code == 422 and "ao menos um lote" in r.json()["detail"]
    r = qualidade.post("/api/cargas-tt", json=_corpo(sem_mp), headers=cabecalho)
    assert r.status_code == 422 and "não está aguardando" in r.json()["detail"]
    r = qualidade.post("/api/cargas-tt", json=_corpo(pin, forno_tempera_codigo="FO-99"), headers=cabecalho)
    assert r.status_code == 422 and "FO-99" in r.json()["detail"]
    r = qualidade.post("/api/cargas-tt", json=_corpo(pin, forno_tempera_codigo="FO-03"), headers=cabecalho)
    assert r.status_code == 422  # forno inativo
    r = qualidade.post("/api/cargas-tt", json=_corpo(pin, ark), headers=cabecalho)
    assert r.status_code == 201 and "ARK" in r.json()["aviso"]  # recomendação, não bloqueio
    assert qualidade.get("/api/cargas-tt").status_code == 200


def test_situacao_iniciar_concluir_e_cancelar_com_motivo(db, como):
    _equipamentos(db)
    pin = _aguardando_tt(db)
    tt, csrf = como(modulos=["producao_tt"])
    cab = {"X-CSRF-Token": csrf}
    carga = tt.post("/api/cargas-tt", json=_corpo(pin), headers=cab).json()
    url = f"/api/cargas-tt/{carga['id']}/status"

    assert tt.post(url, json={"status": "concluida"}, headers=cab).status_code == 409  # precisa iniciar antes
    assert tt.post(url, json={"status": "em_andamento"}, headers=cab).status_code == 200
    db.expire_all()
    assert db.get(CargaTT, carga["id"]).data_inicio is not None
    assert tt.post(url, json={"status": "concluida"}, headers=cab).status_code == 200
    r = tt.post(url, json={"status": "cancelada", "motivo": "engano"}, headers=cab)
    assert r.status_code == 409  # concluída não se cancela
    db.expire_all()
    concluida = db.get(CargaTT, carga["id"])
    assert concluida.status == "concluida" and concluida.data_fim is not None

    outra = tt.post("/api/cargas-tt", json=_corpo(pin), headers=cab).json()
    url = f"/api/cargas-tt/{outra['id']}/status"
    assert tt.post(url, json={"status": "cancelada"}, headers=cab).status_code == 422  # sem motivo
    assert tt.post(url, json={"status": "cancelada", "motivo": "Montada por engano"}, headers=cab).status_code == 200
    db.expire_all()
    cancelada = db.get(CargaTT, outra["id"])
    assert cancelada.status == "cancelada" and cancelada.cancelado_motivo == "Montada por engano"
    assert cancelada.cancelado_por == "Fulano de Tal"
    assert db.scalar(select(CargaTTLote).where(CargaTTLote.carga_id == outra["id"])) is not None  # nada é apagado
    assert tt.put(f"/api/cargas-tt/{outra['id']}", json=_corpo(pin), headers=cab).status_code == 409
    assert tt.get("/api/cargas-tt?aba=canceladas").json()["itens"][0]["numero"] == outra["numero"]
    texto = f"Carga TT {outra['numero']} → cancelada (motivo: Montada por engano)"
    assert texto in db.scalars(select(Evento.texto).where(Evento.lote_id == pin.id)).all()


def test_editar_troca_fornos_e_lotes(db, como):
    _equipamentos(db)
    a = _aguardando_tt(db)
    b = _aguardando_tt(db, numero="26-4-900002", op="900002")
    c = _aguardando_tt(db, numero="26-4-900003", op="900003", tipo="BOX")
    tt, csrf = como(modulos=["producao_tt"])
    cab = {"X-CSRF-Token": csrf}
    carga = tt.post("/api/cargas-tt", json=_corpo(a, b), headers=cab).json()

    form = tt.get(f"/api/cargas-tt/formulario?carga_id={carga['id']}").json()
    assert form["numero_previsto"] == carga["numero"] and form["lote_ids"] == [a.id, b.id]

    r = tt.put(f"/api/cargas-tt/{carga['id']}", json=_corpo(a, c, forno_revenimento_codigo="", observacoes="ok"), headers=cab)
    assert r.status_code == 200, r.text
    assert "+1/-1" in r.json()["mensagem"]
    detalhe = tt.get(f"/api/cargas-tt/{carga['id']}").json()
    assert [lo["id"] for lo in detalhe["lotes"]] == [a.id, c.id]
    assert detalhe["forno_revenimento_codigo"] == "" and detalhe["observacoes"] == "ok"
    assert f"Lote removido da carga de TT {carga['numero']}" in db.scalars(select(Evento.texto).where(Evento.lote_id == b.id)).all()
    auditoria = db.scalar(select(Auditoria).where(Auditoria.acao == "ALTERAR", Auditoria.entidade == "carga_tt"))
    assert auditoria.detalhes["lotes_removidos"] == ["26-4-900002"] and auditoria.detalhes["lotes_adicionados"] == ["26-4-900003"]


def test_acesso_negado_sem_producao_tt_nem_qualidade(db, como):
    _equipamentos(db)
    pin = _aguardando_tt(db)
    tt, csrf_tt = como(modulos=["producao_tt"])
    carga = tt.post("/api/cargas-tt", json=_corpo(pin), headers={"X-CSRF-Token": csrf_tt}).json()
    pcp, csrf = como(modulos=["pcp", "producao_usinagem"], login="pcp1")
    cab = {"X-CSRF-Token": csrf}
    assert pcp.get("/api/cargas-tt").status_code == 403
    assert pcp.get("/api/cargas-tt/formulario").status_code == 403
    assert pcp.get(f"/api/cargas-tt/{carga['id']}").status_code == 403
    assert pcp.post("/api/cargas-tt", json=_corpo(pin), headers=cab).status_code == 403
    assert pcp.put(f"/api/cargas-tt/{carga['id']}", json=_corpo(pin), headers=cab).status_code == 403
    assert pcp.post(f"/api/cargas-tt/{carga['id']}/status", json={"status": "em_andamento"}, headers=cab).status_code == 403
    assert pcp.get(f"/api/cargas-tt/do-lote/{pin.id}").status_code == 200  # consulta da página do lote
    assert tt.post("/api/cargas-tt", json=_corpo(pin)).status_code == 403  # sem o token CSRF
