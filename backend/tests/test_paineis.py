"""Início, painel (alertas e exportação), dashboard, Gantt, KPIs, indicadores, busca e exportação da auditoria.

Tudo com dados fictícios (OP 900001..., lote "26-4-900001", corrida "M999/26").
"""
import io
from datetime import date, datetime, timedelta

import pytest
from conftest import lote_exemplo
from openpyxl import load_workbook

from app import fluxo
from app.config import agora_local
from app.models import (
    Auditoria,
    CargaTT,
    DatabookEnviado,
    EnvioPrestador,
    Equipamento,
    Lote,
    MateriaPrima,
    NaoConformidade,
    OrdemProducao,
    Registro,
)


def _lote(db, numero: str, op: str, tipo: str = "PIN", qtd: int = 72, dias: int = 0, criado: datetime | None = None) -> Lote:
    lote = lote_exemplo(db, numero=numero, tipo=tipo, op=op, qtd=qtd)
    agora = agora_local()
    lote.etapa_desde = agora - timedelta(days=dias)
    lote.criado_em = criado or agora
    db.commit()
    return lote


def _aprovar(db, lote: Lote, ate: str | None = None, quando: datetime | None = None) -> None:
    """Grava registro aprovado em cada etapa aplicável, na ordem, até a etapa `ate` (inclusive) ou todas."""
    for etapa in fluxo.ETAPAS:
        if etapa.aplicavel(lote.tipo):
            for sub in etapa.subs_de(lote.tipo):
                db.add(Registro(lote_id=lote.id, etapa=etapa.chave, sub=sub, status="aprovado", quando=quando or agora_local()))
        if etapa.chave == ate:
            break
    db.commit()


def _concluir(db, lote: Lote, quando: datetime | None = None) -> None:
    _aprovar(db, lote, quando=quando)
    lote.etapa = fluxo.CONCLUIDO
    lote.etapa_desde = quando or agora_local()
    db.commit()


def _reprovar(db, lote: Lote, etapa: str = "receb_mp", status_nc: str = "aberta") -> None:
    registro = Registro(lote_id=lote.id, etapa=etapa, status="reprovado", quando=agora_local())
    db.add(registro)
    db.flush()
    db.add(NaoConformidade(numero=f"NC-2026-9{lote.id:02d}", lote_id=lote.id, etapa=etapa, registro_id=registro.id, status=status_nc))
    db.commit()


def _alertas(resposta) -> dict:
    return {p["chave"]: p for p in resposta.json()["pendencias"]}


# ---------------------------------------------------------------- início


def test_inicio_mostra_so_os_cartoes_do_usuario_com_numeros_reais(cliente, admin, como, db):
    em_tt = _lote(db, "26-4-900001", "900001")
    _aprovar(db, em_tt, ate="receb_mp")  # está no tratamento térmico
    na_dureza = _lote(db, "26-4-900002", "900002")
    _aprovar(db, na_dureza, ate="trat_termico")  # aguardando inspeção (dureza)
    concluido = _lote(db, "26-4-900003", "900003")
    _concluir(db, concluido)
    cancelado = _lote(db, "26-4-900004", "900004")
    cancelado.cancelado_em = agora_local()
    hoje = agora_local().date()
    db.add(Equipamento(codigo="DUR-01", descricao="Durômetro", validade_calibracao=hoje - timedelta(days=1)))
    db.commit()

    r = cliente.get("/api/inicio")
    assert r.status_code == 200, r.text
    cartoes = {c["chave"]: c for c in r.json()["cartoes"]}
    assert list(cartoes) == ["producao", "qualidade", "tt", "equipamentos", "cadastros"]
    assert cartoes["producao"]["texto"] == "2 lotes em andamento"  # o cancelado e o concluído não contam
    assert cartoes["tt"]["texto"] == "1 lote em TT"
    assert cartoes["qualidade"]["texto"] == "1 aguardando inspeção"
    assert cartoes["equipamentos"]["texto"] == "1 calibração vencida" and cartoes["equipamentos"]["alerta"] is True

    # Sem módulo nenhum: só o cartão da Produção (o painel é de todos)
    outro, _ = como(modulos=[])
    assert [c["chave"] for c in outro.get("/api/inicio").json()["cartoes"]] == ["producao"]
    tt, _ = como(modulos=["producao_tt"])
    assert [c["chave"] for c in tt.get("/api/inicio").json()["cartoes"]] == ["producao", "tt"]
    cad, _ = como(modulos=["cadastros"])
    assert [c["chave"] for c in cad.get("/api/inicio").json()["cartoes"]] == ["producao", "equipamentos", "cadastros"]


def test_banner_da_visita_guiada_some_depois_de_responder(como, db):
    outro, csrf = como(modulos=[])
    assert outro.get("/api/inicio").json()["mostrar_tutorial"] is True
    assert outro.post("/api/inicio/tutorial-visto").status_code == 403  # sem o token CSRF
    r = outro.post("/api/inicio/tutorial-visto", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    assert outro.get("/api/inicio").json()["mostrar_tutorial"] is False
    # Responder de novo não grava outra vez
    assert outro.post("/api/inicio/tutorial-visto", headers={"X-CSRF-Token": csrf}).status_code == 200
    registros = db.query(Auditoria).filter(Auditoria.entidade == "usuario", Auditoria.acao == "ALTERAR").all()
    assert [a.detalhes for a in registros if a.detalhes and "tutorial_visto" in a.detalhes] == [{"tutorial_visto": [False, True]}]


def test_paineis_exigem_login(cliente):
    for caminho in ("/api/inicio", "/api/painel", "/api/dashboard", "/api/gantt", "/api/buscar?q=1", "/api/painel/exportar.xlsx"):
        assert cliente.get(caminho).status_code == 401, caminho


# ---------------------------------------------------------------- painel: resumo, Enviado-DB e alertas


def test_painel_resumo_coluna_enviado_e_alertas(cliente, admin, db):
    agora = agora_local()
    hoje = agora.date()
    enviado = _lote(db, "26-4-900001", "900001", tipo="BOX", qtd=40)
    _concluir(db, enviado)
    db.add(DatabookEnviado(op="900001", tipo="BOX", lote="26-4-900001", data_envio=hoje))
    concluido = _lote(db, "26-4-900002", "900002")
    _concluir(db, concluido)
    parado = _lote(db, "26-4-900003", "900003", dias=9)
    com_nc = _lote(db, "26-4-900004", "900004", dias=20)  # parado, mas entra no alerta de NC
    _reprovar(db, com_nc)
    pronto = _lote(db, "26-4-900005", "900005")
    _aprovar(db, pronto, ate="receb_mp")  # cursor ainda no recebimento, que já está aprovado
    db.add(MateriaPrima(corrida="M999/26", status="pendente"))
    db.add(MateriaPrima(corrida="M998/26", status="pendente", cancelado_em=agora))  # cancelada não conta
    db.add(Equipamento(codigo="FOR-01", validade_calibracao=hoje + timedelta(days=10)))
    db.add(Equipamento(codigo="FOR-02", validade_calibracao=hoje + timedelta(days=60)))  # longe de vencer
    db.add(Equipamento(codigo="FOR-03", validade_calibracao=hoje + timedelta(days=5), ativo=False))  # inativo
    carga = CargaTT(numero="TT-2026-901", status="em_andamento", data_inicio=agora - timedelta(hours=30))
    db.add(carga)
    db.add(CargaTT(numero="TT-2026-902", status="em_andamento", data_inicio=agora - timedelta(hours=2)))
    envio = EnvioPrestador(numero="EP-2026-901", status="enviado", data_envio=hoje - timedelta(days=12))
    db.add(envio)
    db.add(EnvioPrestador(numero="EP-2026-902", status="retornado", data_envio=hoje - timedelta(days=40)))
    db.commit()

    r = cliente.get("/api/painel")
    assert r.status_code == 200, r.text
    dados = r.json()
    assert dados["resumo"] == {"total": 5, "andamento": 3, "concluidos": 1, "enviados": 1, "nc": 1}
    assert dados["enviados"] == {"lote_ids": [enviado.id], "pecas": 40, "pin": 0, "box": 1, "ark": 0}
    assert pronto.id in dados["prontos"] and parado.id not in dados["prontos"]

    alertas = _alertas(r)
    assert alertas["materia_prima"]["quantidade"] == 1
    assert alertas["materia_prima"]["link"].startswith("/materia-prima/")
    assert alertas["parados"]["quantidade"] == 1 and alertas["parados"]["link"] == f"/lotes/{parado.id}"
    assert "OP 900003" in alertas["parados"]["texto"]
    assert alertas["nc"]["quantidade"] == 1 and alertas["nc"]["link"] == "/nao-conformidades"
    assert alertas["prontos"]["link"] == f"/lotes/{pronto.id}"
    assert alertas["sem_databook"]["quantidade"] == 1  # o enviado não conta
    assert alertas["calibracao"]["quantidade"] == 1 and "calibracao_vencida" not in alertas
    assert alertas["carga_tt"]["link"] == f"/cargas-tt/{carga.id}" and "TT-2026-901" in alertas["carga_tt"]["texto"]
    assert alertas["envio_prestador"]["link"] == f"/envios/{envio.id}" and alertas["envio_prestador"]["quantidade"] == 1


def test_alerta_de_databook_gerado_e_nao_enviado(cliente, admin, db, pasta_arquivos):
    import os

    lote = _lote(db, "26-4-900001", "900001")
    _concluir(db, lote)
    pasta = pasta_arquivos / "lotes" / str(lote.id) / "databook" / "saida"
    pasta.mkdir(parents=True)
    pdf = pasta / "Databook_900001.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    alertas = _alertas(cliente.get("/api/painel"))
    assert "sem_databook" not in alertas and "databook_sem_envio" not in alertas  # gerado hoje
    velho = (agora_local() - timedelta(days=4)).timestamp()
    os.utime(pdf, (velho, velho))
    alertas = _alertas(cliente.get("/api/painel"))
    assert alertas["databook_sem_envio"]["quantidade"] == 1 and alertas["databook_sem_envio"]["link"] == "/databooks"


def test_alertas_so_aparecem_para_quem_pode_abrir_a_tela(como, db):
    hoje = agora_local().date()
    _lote(db, "26-4-900001", "900001", dias=10)
    db.add(MateriaPrima(corrida="M999/26", status="pendente"))
    db.add(Equipamento(codigo="FOR-01", validade_calibracao=hoje - timedelta(days=2)))
    db.add(EnvioPrestador(numero="EP-2026-901", status="enviado", data_envio=hoje - timedelta(days=15)))
    db.commit()
    sem_modulo, _ = como(modulos=[])
    assert set(_alertas(sem_modulo.get("/api/painel"))) == {"parados"}
    usinagem, _ = como(modulos=["producao_usinagem"])
    assert set(_alertas(usinagem.get("/api/painel"))) == {"parados", "envio_prestador"}
    qualidade, _ = como(modulos=["qualidade"])
    assert {"parados", "materia_prima", "calibracao_vencida", "envio_prestador"} <= set(_alertas(qualidade.get("/api/painel")))


def test_exportar_painel_em_excel(cliente, admin, db):
    db.add(OrdemProducao(op="900001", cliente="CLIENTE EXEMPLO INDUSTRIAL SA", po="PO-123"))
    lote = _lote(db, "26-4-900001", "900001", dias=12)
    lote.coditem = "=1+1"  # texto que viraria fórmula no Excel
    lote.corrida = "M999/26"
    enviado = _lote(db, "26-4-900002", "900002", tipo="ARK")
    _concluir(db, enviado)
    db.add(DatabookEnviado(op="900002", tipo="ARK", data_envio=agora_local().date()))
    db.commit()

    r = cliente.get("/api/painel/exportar.xlsx")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert 'filename="Painel_Lotes_' in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Lotes", "Resumo"]
    ws = wb["Lotes"]
    cabecalho = [c.value for c in ws[1]]
    assert len(cabecalho) == 14 and cabecalho[0] == "OP" and cabecalho[12] == "Enviado-DB"
    linhas = {row[1]: row for row in ws.iter_rows(min_row=2, values_only=True)}
    assert linhas["26-4-900002"][11] == "Enviado-DB" and linhas["26-4-900002"][12] == "Sim"  # o mais novo vem primeiro
    primeira = linhas["26-4-900001"]
    assert primeira[5] == "'=1+1"
    assert primeira[6] == "Cliente" and primeira[7] == "PO-123"
    assert primeira[8] == fluxo.ETAPAS[0].nome and primeira[10] == 12 and primeira[11] == "Em andamento"
    assert ws.cell(row=3, column=11).fill.fgColor.rgb.endswith("FBE7E4")  # 12 dias na etapa: em vermelho
    resumo = {row[0]: row[1] for row in wb["Resumo"].iter_rows(values_only=True) if row and row[0]}
    assert resumo["Total de lotes"] == 2 and resumo["Enviado-DB"] == 1 and resumo["Total ARK"] == 1


# ---------------------------------------------------------------- dashboard


def test_dashboard_agrupa_por_setor_e_mostra_kpis_so_para_quem_pode(cliente, admin, como, db):
    db.add(OrdemProducao(op="900001", descricao="INSTR. CONTROLE TRAVAMENTO ARK 18-24 EXEMPLO", tipo="ARK", coditem="99001"))
    _lote(db, "26-4-900001", "900001", tipo="ARK", qtd=10, dias=3)
    tt = _lote(db, "26-4-900002", "900002", qtd=100)
    _aprovar(db, tt, ate="receb_mp")
    enviado = _lote(db, "26-4-900003", "900003", tipo="BOX")
    _concluir(db, enviado)
    db.add(DatabookEnviado(op="900003", tipo="BOX", data_envio=agora_local().date()))
    db.commit()

    r = cliente.get("/api/dashboard")
    assert r.status_code == 200, r.text
    dados = r.json()
    assert dados["setores"] == ["Inspeção de recebimento", "Tratamento térmico", "Enviado-DB"]
    lotes = {x["numero"]: x for x in dados["lotes"]}
    assert lotes["26-4-900001"]["descricao"] == "ARK 18-24 EXEMPLO" and lotes["26-4-900001"]["dias"] == 3
    assert lotes["26-4-900003"]["situacao"] == "enviado" and lotes["26-4-900003"]["setor"] == "Enviado-DB"
    assert dados["maior_qtd"] == 100
    assert dados["totais"]["enviados"] == 1 and dados["totais"]["box_enviados"] == 1 and dados["totais"]["pin_ativos"] == 1
    assert dados["tendencias"]["enviados"]["sentido"] == "novo"
    assert dados["kpis"]["funil"][1] == {"nome": "Finalizados", "lotes": 1, "pecas": 72}
    assert dados["ops"][0]["op"] == "900001"

    usinagem, _ = como(modulos=["producao_usinagem"])
    assert usinagem.get("/api/dashboard").json()["kpis"] is None
    tt_usuario, _ = como(modulos=["producao_tt"])
    assert tt_usuario.get("/api/dashboard").json()["kpis"] is not None


# ---------------------------------------------------------------- Gantt


def test_gantt_uma_linha_por_op_com_a_situacao_de_cada_etapa(cliente, admin, db):
    db.add(OrdemProducao(op="900001", tipo="ARK", coditem="99001", qt_lote=30))
    db.add(OrdemProducao(op="900002", tipo="PIN", coditem="99002", qt_lote=50))  # sem lote ainda
    ark = _lote(db, "26-4-900001", "900001", tipo="ARK", qtd=30)
    _aprovar(db, ark, ate="trat_termico", quando=datetime(2026, 11, 2, 9, 0))
    pulada = _lote(db, "26-4-900003", "900003")  # OP fora do cadastro: entra no fim
    _aprovar(db, pulada, ate="receb_mp")
    pulada.etapa = fluxo.INDICE["dureza"]  # passou do TT sem ele aprovado
    db.commit()

    r = cliente.get("/api/gantt")
    assert r.status_code == 200, r.text
    dados = r.json()
    assert len(dados["etapas"]) == len(fluxo.ETAPAS)
    linhas = {x["op"]: x for x in dados["linhas"]}
    assert [x["op"] for x in dados["linhas"]] == ["900001", "900003", "900002"]  # sem lote por último
    linha_ark = linhas["900001"]
    estados = [c["s"] for c in linha_ark["celulas"]]
    assert estados[fluxo.INDICE["receb_mp"]] == "aprovada" and linha_ark["celulas"][0]["rotulo"] == "02/11/2026"
    assert estados[fluxo.INDICE["dureza"]] == "na" and estados[fluxo.INDICE["usinagem"]] == "na"
    assert estados[fluxo.INDICE["lab_ext"]] == "atual" and estados[fluxo.INDICE["dim_final"]] == "futura"
    assert linha_ark["pct"] == int(2 / 8 * 100) and linha_ark["lote"]["numero"] == "26-4-900001"
    assert linhas["900002"]["situacao"] == "semlote" and set(c["s"] for c in linhas["900002"]["celulas"]) == {"nao_iniciado"}
    assert linhas["900002"]["qtd"] == 50
    assert [c["s"] for c in linhas["900003"]["celulas"]][fluxo.INDICE["trat_termico"]] == "atual"
    _reprovar(db, pulada, etapa="trat_termico")
    linha = {x["op"]: x for x in cliente.get("/api/gantt").json()["linhas"]}["900003"]
    assert linha["celulas"][fluxo.INDICE["trat_termico"]]["s"] == "reprovada"
    assert dados["totais"]["ops"] == 3 and dados["totais"]["sem_lote"] == 1 and dados["totais"]["lotes"] == 2


# ---------------------------------------------------------------- KPIs


def test_kpis_exigem_qualidade_ou_producao_tt(como):
    for modulos in ([], ["pcp"], ["producao_usinagem"], ["cadastros"]):
        outro, _ = como(modulos=modulos)
        assert outro.get("/api/kpis").status_code == 403, modulos
    tt, _ = como(modulos=["producao_tt"])
    assert tt.get("/api/kpis").status_code == 200


def test_kpis_com_filtros_de_periodo_e_tipo(cliente, admin, db):
    agora = agora_local()
    hoje = agora.date()
    antigo = _lote(db, "26-1-900001", "900001", qtd=10, criado=agora - timedelta(days=400))
    _concluir(db, antigo)
    db.add(DatabookEnviado(op="900001", tipo="PIN", data_envio=hoje - timedelta(days=380)))
    recente = _lote(db, "26-4-900002", "900002", tipo="BOX", qtd=20, criado=agora - timedelta(days=10), dias=5)
    _aprovar(db, recente, ate="receb_mp")
    _lote(db, "26-4-900003", "900003", tipo="ARK", qtd=30, criado=agora, dias=1)
    db.commit()

    tudo = cliente.get("/api/kpis").json()
    assert tudo["periodo"] == "tudo" and tudo["tipo"] == "todos"
    assert tudo["totais"]["lotes"] == 3 and tudo["totais"]["pecas"] == 60 and tudo["totais"]["enviados"] == 1
    assert tudo["funil"] == [{"nome": "Em andamento", "lotes": 2, "pecas": 50}, {"nome": "Finalizados", "lotes": 1, "pecas": 10}]
    assert tudo["funil_tipo"][0]["box"] == 1 and tudo["funil_tipo"][1]["pin"] == 1 and tudo["funil_tipo"][1]["pecas_pin"] == 10
    setores = {s["setor"]: s for s in tudo["setores"]}
    assert setores["Trat. Térmico"]["lotes"] == 1 and setores["Trat. Térmico"]["dias_medio"] == 5.0
    # Peças por mês: sem buracos entre o primeiro e o último mês
    meses = tudo["pecas_mes"]
    assert meses[0]["pin"] == 10 and meses[-1]["total"] >= 30 and len(meses) >= 13
    # A linha do tempo dos databooks começa no mês do envio mais antigo
    assert tudo["linha_do_tempo"][0]["enviados"] == 1 and len(tudo["linha_do_tempo"]) >= 13

    tres_meses = cliente.get("/api/kpis?periodo=3m").json()
    assert tres_meses["totais"]["lotes"] == 2 and tres_meses["rotulo_periodo"] == "Últimos 3 meses"
    so_box = cliente.get("/api/kpis?tipo=box").json()
    assert so_box["tipo"] == "BOX" and so_box["totais"]["lotes"] == 1 and so_box["totais"]["pecas"] == 20
    assert sum(m["enviados"] for m in so_box["linha_do_tempo"]) == 0  # o databook enviado é de PIN
    invalido = cliente.get("/api/kpis?periodo=xx&tipo=zz").json()
    assert invalido["periodo"] == "tudo" and invalido["tipo"] == "todos"
    ano = cliente.get("/api/kpis?periodo=ano").json()
    assert ano["soma_anual"]["ark"] == 30 and ano["ano"] == hoje.year


def test_tendencia_mes_a_mes():
    from app.paineis import variacao

    assert variacao(0, 0) is None
    assert variacao(3, 0)["sentido"] == "novo"
    assert variacao(6, 4) == {"atual": 6, "anterior": 4, "sentido": "subiu", "rotulo": "+50%", "pct": 50}
    assert variacao(1, 4)["rotulo"] == "-75%" and variacao(1, 4)["sentido"] == "caiu"
    assert variacao(2, 2)["sentido"] == "igual"


def test_linha_do_tempo_mostra_pelo_menos_seis_meses():
    from app.paineis import linha_do_tempo

    meses = linha_do_tempo([date(2026, 11, 3), date(2026, 11, 20), None], hoje=date(2026, 11, 24))
    assert [m["mes"] for m in meses] == ["06/2026", "07/2026", "08/2026", "09/2026", "10/2026", "11/2026"]
    assert meses[-1]["enviados"] == 2
    virada = linha_do_tempo([date(2025, 12, 1)], hoje=date(2026, 2, 10))
    assert virada[0]["mes"] == "09/2025" and virada[3] == {"mes": "12/2025", "chave": "2025-12", "enviados": 1}


# ---------------------------------------------------------------- indicadores


def test_indicadores_por_fornecedor_e_tipo(cliente, admin, como, db):
    quantidades = {"qt_fund": 110, "qt_real": 100, "qt_ok": 80, "qt_rej": 15, "qt_retrab": 5}
    db.add(MateriaPrima(corrida="M999/26", fornecedor="FORNECEDOR A", tipo_destino="PIN", **quantidades))
    db.add(MateriaPrima(corrida="M998/26", fornecedor="FORNECEDOR B", tipo_destino="ARK", qt_fund=50, qt_real=50, qt_ok=49, qt_rej=1))
    db.add(MateriaPrima(corrida="M997/26", fornecedor="FORNECEDOR A", tipo_destino="PIN", qt_real=999, cancelado_em=agora_local()))
    db.commit()

    r = cliente.get("/api/indicadores")
    assert r.status_code == 200, r.text
    dados = r.json()
    assert dados["total"] == 2
    geral = dados["geral"]
    assert geral["qt_real"] == 150 and geral["pct_refugo"] == round(16 / 150 * 100, 1) and geral["rendimento"] == round(129 / 160 * 100, 1)
    assert [f["fornecedor"] for f in dados["por_fornecedor"]] == ["FORNECEDOR A", "FORNECEDOR B"]
    assert dados["por_fornecedor"][0]["pct_refugo"] == 15.0 and dados["por_fornecedor"][0]["pct_retrab"] == 5.0
    assert {t["tipo"] for t in dados["por_tipo"]} == {"PIN", "ARK"}
    assert dados["top_refugo"][0]["corrida"] == "M999/26"

    for modulos in (["producao_tt"], ["pcp"], []):
        outro, _ = como(modulos=modulos)
        assert outro.get("/api/indicadores").status_code == 403, modulos


# ---------------------------------------------------------------- busca global


def test_busca_por_op_lote_item_e_descricao(cliente, admin, db):
    db.add(OrdemProducao(op="900001", descricao="INSTR. CONTROLE TRAVAMENTO CHAVETA TÊMPERA EXEMPLO", tipo="PIN", coditem="99001"))
    db.add(OrdemProducao(op="900777", descricao="PEÇA SEM LOTE", tipo="BOX", coditem="99777", qt_lote=12))
    lote = _lote(db, "26-4-900001", "900001")
    lote.coditem = "99001"
    concluido = _lote(db, "26-4-900002", "900002", tipo="ARK")
    _concluir(db, concluido)
    cancelado = _lote(db, "26-4-900003", "900003")
    cancelado.cancelado_em = agora_local()
    db.commit()

    r = cliente.get("/api/buscar?q=900001")
    assert r.status_code == 200, r.text
    itens = r.json()["itens"]
    assert [i["numero"] for i in itens] == ["26-4-900001"]
    assert itens[0]["etapa"] == fluxo.ETAPAS[0].curto and itens[0]["descricao"] == "CHAVETA TÊMPERA EXEMPLO"
    assert [i["numero"] for i in cliente.get("/api/buscar?q=tempera").json()["itens"]] == ["26-4-900001"]  # sem acento
    assert cliente.get("/api/buscar?q=900002 ark").json()["itens"][0]["etapa"] == "Concluído"
    assert cliente.get("/api/buscar?q=900003").json()["total"] == 0  # cancelado não aparece
    sem_lote = cliente.get("/api/buscar?q=99777").json()["itens"]
    assert sem_lote == [
        {"tipo": "op", "id": None, "op": "900777", "numero": "", "formato": "BOX", "qtd": 12, "coditem": "99777",
         "descricao": "PEÇA SEM LOTE", "etapa": "Sem lote iniciado", "enviado": False, "nc": False}
    ]  # fmt: skip
    recentes = cliente.get(f"/api/buscar?ids={concluido.id},{cancelado.id},{lote.id}").json()["itens"]
    assert [i["id"] for i in recentes] == [concluido.id, lote.id]
    assert cliente.get("/api/buscar?q=" + "x" * 101).status_code == 422


# ---------------------------------------------------------------- exportação da auditoria


def test_exportar_auditoria_com_os_filtros_da_lista(cliente, admin, como, db):
    lote = _lote(db, "26-4-900001", "900001")
    db.add(Auditoria(login="fulano", acao="APROVAR", entidade="registro", entidade_id="7", lote_id=lote.id,
                     detalhes={"motivo": "=CMD()", "etapa": "dureza"}))  # fmt: skip
    db.add(Auditoria(login="fulano", acao="CRIAR", entidade="lote", entidade_id=str(lote.id), lote_id=lote.id))
    db.commit()

    r = cliente.get("/api/auditoria/exportar.xlsx?acao=aprovar")
    assert r.status_code == 200, r.text
    assert 'filename="Auditoria_' in r.headers["content-disposition"]
    ws = load_workbook(io.BytesIO(r.content))["Auditoria"]
    assert [c.value for c in ws[1]] == ["Quando", "Usuário", "Ação", "Sobre", "ID", "Lote", "Motivo", "Detalhes (JSON)", "IP"]
    linhas = list(ws.iter_rows(min_row=2, values_only=True))
    assert len(linhas) == 1
    assert linhas[0][1:7] == ("fulano", "APROVAR", "registro", "7", "26-4-900001", "'=CMD()")
    assert isinstance(linhas[0][0], datetime) and '"etapa": "dureza"' in linhas[0][7]

    todos = load_workbook(io.BytesIO(cliente.get(f"/api/auditoria/exportar.xlsx?lote_id={lote.id}").content))["Auditoria"]
    assert todos.max_row == 3
    vazio = load_workbook(io.BytesIO(cliente.get("/api/auditoria/exportar.xlsx?login=ninguem").content))["Auditoria"]
    assert vazio.max_row == 1

    for modulos in (["producao_tt"], ["cadastros"], []):
        outro, _ = como(modulos=modulos)
        assert outro.get("/api/auditoria/exportar.xlsx").status_code == 403, modulos
    assert cliente.get("/api/auditoria/exportar.xlsx?de=2026-13-01").status_code == 422


@pytest.mark.parametrize("caminho", ["/api/inicio", "/api/painel", "/api/dashboard", "/api/gantt", "/api/buscar"])
def test_telas_abertas_a_qualquer_usuario_logado(como, caminho):
    outro, _ = como(modulos=[])
    assert outro.get(caminho).status_code == 200
