"""Não conformidades: lista, detalhe, as 4 disposições, reabertura e correção de dureza. Dados fictícios."""
from datetime import datetime
from decimal import Decimal

from conftest import lote_exemplo
from sqlalchemy import select

from app.estado import estado_lotes, ultimos_registros
from app.models import Auditoria, EspecificacaoTipo, Evento, Lote, NaoConformidade, Registro
from app.nc import abrir_nc_automatica


def _nc(db, lote=None, etapa="dureza", sub="", dados=None, descricao="Dureza fora da especificação"):
    lote = lote or lote_exemplo(db)
    registro = Registro(lote_id=lote.id, etapa=etapa, sub=sub, status="reprovado", dados=dados or {},
                        quando=datetime(2026, 11, 20, 9, 0), responsavel="Fulano")  # fmt: skip
    db.add(registro)
    db.flush()
    nc = abrir_nc_automatica(db, None, lote, registro, descricao)
    db.commit()
    return lote, registro, nc


def _decidir(cliente, csrf, nc_id, **corpo):
    return cliente.post(f"/api/nao-conformidades/{nc_id}/decidir", json=corpo, headers={"X-CSRF-Token": csrf})


def _eventos(db, lote_id):
    db.expire_all()
    return [e.texto for e in db.scalars(select(Evento).where(Evento.lote_id == lote_id).order_by(Evento.id))]


def _auditoria(db, acao, entidade):
    db.expire_all()
    return list(db.scalars(select(Auditoria).where(Auditoria.acao == acao, Auditoria.entidade == entidade)))


# ---------------------------------------------------------------- lista e detalhe


def test_lista_com_abas_e_contagens(cliente, admin, db):
    lote, _, nc1 = _nc(db)
    _, _, nc2 = _nc(db, lote=lote, etapa="visual", descricao="Risco na face")
    nc2.status, nc2.disposicao = "encerrada", "sucata"
    cancelado = lote_exemplo(db, numero="26-4-900002", op="900002", cancelado_em=datetime(2026, 11, 21, 8, 0))
    _nc(db, lote=cancelado)  # lote cancelado: some das listas
    db.commit()

    r = cliente.get("/api/nao-conformidades")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["aba"] == "abertas" and corpo["contagens"] == {"abertas": 1, "encerradas": 1}
    [item] = corpo["itens"]
    assert item["numero"] == nc1.numero and item["etapa_nome"] == "Dureza HRC" and item["lote"]["numero"] == "26-4-900001"
    assert item["aberta_em"] and item["descricao"] == "Dureza fora da especificação"

    encerradas = cliente.get("/api/nao-conformidades?aba=encerradas").json()["itens"]
    assert [n["id"] for n in encerradas] == [nc2.id] and encerradas[0]["disposicao_nome"] == "Sucata"
    assert cliente.get(f"/api/nao-conformidades?lote_id={lote.id}").json()["contagens"] == {"abertas": 1, "encerradas": 1}


def test_detalhe_mostra_registro_e_atalho_de_dureza(cliente, admin, db):
    _, registro, nc = _nc(db)
    r = cliente.get(f"/api/nao-conformidades/{nc.id}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["registro"]["id"] == registro.id and d["registro"]["responsavel"] == "Fulano"
    assert d["corrigir_dureza_disponivel"] is True
    assert d["pode_decidir_desvio"] is False  # administrador NÃO tem "pode aprovar"
    assert d["lote"]["qtd"] == 72
    assert cliente.get("/api/nao-conformidades/999").status_code == 404


def test_sem_modulo_qualidade_nao_ve_nem_decide(como, db):
    _, _, nc = _nc(db)
    outro, csrf = como(modulos=["pcp"])
    assert outro.get("/api/nao-conformidades").status_code == 403
    assert outro.get(f"/api/nao-conformidades/{nc.id}").status_code == 403
    assert _decidir(outro, csrf, nc.id, disposicao="retrabalho").status_code == 403
    assert outro.post(f"/api/nao-conformidades/{nc.id}/reabrir", headers={"X-CSRF-Token": csrf}).status_code == 403


def test_decisao_sem_csrf_e_recusada(cliente, admin, db):
    _, _, nc = _nc(db)
    assert cliente.post(f"/api/nao-conformidades/{nc.id}/decidir", json={"disposicao": "retrabalho"}).status_code == 403


# ---------------------------------------------------------------- disposições


def test_retrabalho_mantem_bloqueado_e_reabrir_exige_aprovador(como, db):
    lote, registro, nc = _nc(db)
    qualidade, csrf = como(modulos=["qualidade"])
    assert _decidir(qualidade, csrf, nc.id, disposicao="qualquer").status_code == 422
    r = _decidir(qualidade, csrf, nc.id, disposicao="retrabalho", observacoes="Retemperar o lote")
    assert r.status_code == 200, r.text
    assert r.json()["nc"]["status"] == "em_tratamento" and r.json()["nc"]["decidida_por"] == "Fulano de Tal"
    db.expire_all()
    estado = estado_lotes(db, [lote.id])[0][lote.id][("dureza", "")]
    assert not estado.resolvida  # retrabalho não libera o avanço
    assert any("RETRABALHO" in t for t in _eventos(db, lote.id))
    assert _auditoria(db, "DECIDIR", "nc")[0].detalhes["depois"]["disposicao"] == "retrabalho"
    # Em tratamento: não se decide de novo sem reabrir
    assert _decidir(qualidade, csrf, nc.id, disposicao="sucata", qtd_afetada=1).status_code == 409

    assert qualidade.post(f"/api/nao-conformidades/{nc.id}/reabrir", headers={"X-CSRF-Token": csrf}).status_code == 403
    aprovador, csrf_ap = como(modulos=["qualidade"], pode_aprovar=True)
    r = aprovador.post(f"/api/nao-conformidades/{nc.id}/reabrir", json={"motivo": "Decidido por engano"},
                       headers={"X-CSRF-Token": csrf_ap})  # fmt: skip
    assert r.status_code == 200, r.text
    assert r.json()["nc"]["status"] == "aberta" and r.json()["nc"]["disposicao"] == ""
    assert aprovador.post(f"/api/nao-conformidades/{nc.id}/reabrir", headers={"X-CSRF-Token": csrf_ap}).status_code == 409
    assert _auditoria(db, "REABRIR", "nc")[0].detalhes["motivo"] == "Decidido por engano"


def test_sucata_abate_a_quantidade_e_libera(como, db):
    lote, _, nc = _nc(db)
    qualidade, csrf = como(modulos=["qualidade"])
    for qtd in (None, 0, 73):
        r = _decidir(qualidade, csrf, nc.id, disposicao="sucata", qtd_afetada=qtd)
        assert r.status_code == 422 and "entre 1 e 72" in r.json()["detail"]
    r = _decidir(qualidade, csrf, nc.id, disposicao="sucata", qtd_afetada=5)
    assert r.status_code == 200, r.text
    assert "ajustada para 67" in r.json()["mensagem"]
    db.expire_all()
    assert db.get(Lote, lote.id).qtd == 67
    nc_db = db.get(NaoConformidade, nc.id)
    assert nc_db.status == "encerrada" and nc_db.disposicao == "sucata" and nc_db.qtd_afetada == 5 and nc_db.encerrada_em
    assert estado_lotes(db, [lote.id])[0][lote.id][("dureza", "")].resolvida
    assert any("de 72 para 67" in t for t in _eventos(db, lote.id))
    detalhes = _auditoria(db, "DECIDIR", "nc")[0].detalhes
    assert detalhes["antes"]["qtd_lote"] == 72 and detalhes["depois"]["qtd_lote"] == 67
    assert _decidir(qualidade, csrf, nc.id, disposicao="retrabalho").status_code == 409  # já encerrada


def test_uso_como_esta_exige_aprovador_e_justificativa(cliente, admin, como, db):
    lote, _, nc = _nc(db)
    qualidade, csrf = como(modulos=["qualidade"])
    assert _decidir(qualidade, csrf, nc.id, disposicao="uso_como_esta", justificativa="ok").status_code == 403
    assert _decidir(cliente, admin, nc.id, disposicao="uso_como_esta", justificativa="ok").status_code == 403  # admin sem "pode aprovar"
    aprovador, csrf_ap = como(modulos=["qualidade"], pode_aprovar=True, nome="Beltrano")
    assert _decidir(aprovador, csrf_ap, nc.id, disposicao="uso_como_esta", justificativa="   ").status_code == 422
    r = _decidir(aprovador, csrf_ap, nc.id, disposicao="uso_como_esta", justificativa="Desvio aceito pelo cliente exemplo")
    assert r.status_code == 200, r.text
    d = r.json()["nc"]
    assert d["status"] == "encerrada" and d["disposicao"] == "uso_como_esta" and d["justificativa"].startswith("Desvio")
    assert d["encerrada_por"] == "Beltrano"
    db.expire_all()
    assert estado_lotes(db, [lote.id])[0][lote.id][("dureza", "")].resolvida


def test_anulada_marca_o_registro_e_o_fluxo_o_ignora(como, db):
    lote = lote_exemplo(db)
    anterior = Registro(lote_id=lote.id, etapa="visual", status="aprovado", quando=datetime(2026, 11, 20, 8, 0))
    db.add(anterior)
    db.commit()
    _, registro, nc = _nc(db, lote=lote, etapa="visual", descricao="Lançado como reprovado por engano")
    qualidade, csrf = como(modulos=["qualidade"])
    assert _decidir(qualidade, csrf, nc.id, disposicao="anulada", motivo_anulacao="x").status_code == 403
    aprovador, csrf_ap = como(modulos=["qualidade"], pode_aprovar=True)
    assert _decidir(aprovador, csrf_ap, nc.id, disposicao="anulada").status_code == 422
    r = _decidir(aprovador, csrf_ap, nc.id, disposicao="anulada", motivo_anulacao="Marcado reprovado em vez de aprovado")
    assert r.status_code == 200, r.text
    assert r.json()["nc"]["registro"]["anulado"] is True
    db.expire_all()
    reg = db.get(Registro, registro.id)
    assert reg.anulado and reg.anulado_motivo.startswith("Marcado") and reg.anulado_por == "Fulano de Tal" and reg.anulado_em
    assert ultimos_registros(db, [lote.id])[(lote.id, "visual", "")].id == anterior.id  # o anulado some do fluxo
    assert _auditoria(db, "ANULAR", "registro")[0].entidade_id == str(registro.id)
    assert any("ANULADA" in t for t in _eventos(db, lote.id))


def test_lote_cancelado_nao_recebe_decisao(cliente, admin, db):
    lote, _, nc = _nc(db)
    lote.cancelado_em = datetime(2026, 11, 22, 8, 0)
    db.commit()
    assert cliente.get(f"/api/nao-conformidades/{nc.id}").json()["lote"]["cancelado"] is True
    assert _decidir(cliente, admin, nc.id, disposicao="retrabalho").status_code == 409


# ---------------------------------------------------------------- correção de dureza


def _spec_pin(db, minimo="30", maximo="39"):
    db.add(EspecificacaoTipo(tipo="PIN", dureza_min=Decimal(minimo), dureza_max=Decimal(maximo)))
    db.commit()


def _corrigir(cliente, csrf, registro_id, leituras, nc_id=None):
    return cliente.post(f"/api/registros/{registro_id}/corrigir-dureza", json={"leituras": leituras, "nc_id": nc_id},
                        headers={"X-CSRF-Token": csrf})  # fmt: skip


def test_corrigir_dureza_que_fica_aprovada_encerra_a_nc(como, db):
    _spec_pin(db)
    dados = {"leituras": [{"cp": "OP900001-DUR1", "peca": "17", "valores": [2.5, 36, 35], "status": "REPROVADO"},
                          {"cp": "OP900001-DUR2", "valores": [34, 35], "status": "APROVADO"}]}  # fmt: skip
    lote, registro, nc = _nc(db, dados=dados)
    qualidade, csrf = como(modulos=["qualidade"])
    assert qualidade.get(f"/api/registros/{registro.id}/corrigir-dureza").status_code == 403
    assert _corrigir(qualidade, csrf, registro.id, [{"cp": "A", "valores": ["36"]}, {"cp": "B", "valores": ["35"]}]).status_code == 403
    aprovador, csrf_ap = como(modulos=["qualidade"], pode_aprovar=True)
    r = aprovador.get(f"/api/registros/{registro.id}/corrigir-dureza")
    assert r.status_code == 200, r.text
    tela = r.json()
    assert tela["esp_min"] == 30 and tela["esp_max"] == 39 and tela["nc"]["id"] == nc.id
    assert [lt["valores"] for lt in tela["leituras"]] == [[2.5, 36, 35], [34, 35]]

    assert _corrigir(aprovador, csrf_ap, registro.id, [{"cp": "A", "valores": ["36"]}]).status_code == 409  # lista mudou
    assert _corrigir(aprovador, csrf_ap, registro.id, [{"cp": "A", "valores": ["abc"]}, {"cp": "B", "valores": []}]).status_code == 422
    assert _corrigir(aprovador, csrf_ap, registro.id, [{"cp": "A", "valores": [""]}, {"cp": "B", "valores": []}]).status_code == 422

    r = _corrigir(aprovador, csrf_ap, registro.id,
                  [{"cp": "OP900001-DUR1", "valores": ["25,5", "36", "35"]}, {"cp": "OP900001-DUR2", "valores": ["34", "35", ""]}],
                  nc_id=nc.id)  # fmt: skip
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "reprovado"  # 25,5 continua fora: NC segue aberta
    db.expire_all()
    assert db.get(NaoConformidade, nc.id).status == "aberta"

    r = _corrigir(aprovador, csrf_ap, registro.id,
                  [{"cp": "OP900001-DUR1", "valores": ["35,5", "36", "35"]}, {"cp": "OP900001-DUR2", "valores": [34, 35]}],
                  nc_id=nc.id)  # fmt: skip
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "aprovado" and r.json()["nc_encerrada"]["id"] == nc.id
    db.expire_all()
    reg = db.get(Registro, registro.id)
    assert reg.status == "aprovado" and reg.dados["leituras"][0]["valores"] == [35.5, 36, 35] and reg.dados["corrigido_por"]
    assert [lt["peca"] for lt in reg.dados["leituras"]] == ["17", ""]  # o nº da peça não se perde na correção
    nc_db = db.get(NaoConformidade, nc.id)
    assert nc_db.status == "encerrada" and nc_db.disposicao == "anulada" and "Antes: OP900001-DUR1 (peça 17): 25,5" in nc_db.observacoes
    assert estado_lotes(db, [lote.id])[0][lote.id][("dureza", "")].resolvida
    correcoes = _auditoria(db, "CORRIGIR", "registro")
    assert correcoes[0].detalhes["antes"]["leituras"][0]["valores"] == [2.5, 36, 35]  # o valor de antes fica guardado
    # Já aprovado: não se corrige mais por aqui
    assert aprovador.get(f"/api/registros/{registro.id}/corrigir-dureza").status_code == 409


def test_corrigir_dureza_no_formato_antigo_do_relatorio(como, db):
    _spec_pin(db)
    dados = {"report": {"titulo": "Relatório de Ensaio de Dureza (HRC)",
                        "kv": [["Leituras", "3"], ["Resultado", "REPROVADO"]],
                        "tabelas": [{"titulo": "Leituras", "cab": ["Peça / ponto", "HRC", "Resultado"],
                                     "linhas": [["P1", "3,6", "FORA"], ["P1", "36", "OK"], ["P2", "35", "OK"]]}]}}  # fmt: skip
    _, registro, nc = _nc(db, dados=dados)
    aprovador, csrf = como(modulos=["qualidade"], pode_aprovar=True)
    tela = aprovador.get(f"/api/registros/{registro.id}/corrigir-dureza").json()
    assert tela["leituras"] == [{"cp": "P1", "peca": "", "valores": [3.6, 36.0], "status": ""},
                                {"cp": "P2", "peca": "", "valores": [35.0], "status": ""}]  # fmt: skip
    r = _corrigir(aprovador, csrf, registro.id, [{"cp": "P1", "valores": ["36", "36"]}, {"cp": "P2", "valores": ["35"]}])
    assert r.status_code == 200 and r.json()["status"] == "aprovado"
    db.expire_all()
    relatorio = db.get(Registro, registro.id).dados["report"]
    assert relatorio["tabelas"][0]["linhas"] == [["P1", "36", "OK"], ["P1", "36", "OK"], ["P2", "35", "OK"]]
    assert ["Resultado", "APROVADO"] in relatorio["kv"] and ["Leituras", "3"] in relatorio["kv"]


def test_corrigir_dureza_recusa_sem_especificacao_e_fora_da_dureza(como, db):
    lote, registro, _ = _nc(db, dados={"leituras": [{"cp": "CP1", "valores": [2.5]}]})
    aprovador, csrf = como(modulos=["qualidade"], pode_aprovar=True)
    r = _corrigir(aprovador, csrf, registro.id, [{"cp": "CP1", "valores": ["35"]}])
    assert r.status_code == 422 and "não está cadastrada" in r.json()["detail"]
    _, outro, _ = _nc(db, lote=lote, etapa="visual")
    assert aprovador.get(f"/api/registros/{outro.id}/corrigir-dureza").status_code == 422
    assert aprovador.get("/api/registros/9999/corrigir-dureza").status_code == 404
