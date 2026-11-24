"""Ciclo do lote: novo/editar/cancelar, registro das etapas, aprovação por documento, anexos, avanço, importação,
PDF do registro, arquivo do laser e mapa. Valores fictícios (OP 900001, corrida M999/26, CLIENTE EXEMPLO)."""
from datetime import date, datetime
from decimal import Decimal

import pymupdf
import pytest
from conftest import lote_exemplo
from sqlalchemy import select

from app import fluxo, parametros
from app.models import (
    Anexo,
    Auditoria,
    DatabookEnviado,
    EnvioPrestador,
    EnvioPrestadorLote,
    Equipamento,
    EspecificacaoCota,
    EspecificacaoTipo,
    Lote,
    MateriaPrima,
    MateriaPrimaAnexo,
    NaoConformidade,
    OrdemProducao,
    Prestador,
    Registro,
)

PDF = b"%PDF-1.4 documento de teste"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


def _h(csrf: str) -> dict:
    return {"X-CSRF-Token": csrf}


def _lote(db, etapa: str = "receb_mp", tipo: str = "PIN", **extra) -> Lote:
    """Lote fictício com o cursor na etapa pedida."""
    return lote_exemplo(db, tipo=tipo, etapa=fluxo.INDICE[etapa], **extra)


def _espec_pin(db) -> None:
    db.add(EspecificacaoTipo(tipo="PIN", dureza_min=Decimal("30"), dureza_max=Decimal("39"), tr_le_min=Decimal("550"),
                             tr_lr_min=Decimal("655"), tr_al_min=Decimal("18"), ch_temp="-20", ch_med_min=Decimal("27"),
                             ch_ind_min=Decimal("20"), ch_dim_cp="10x10 mm"))  # fmt: skip
    db.commit()


def _anexar(cliente, csrf, lote_id, etapa, nome="relatorio.pdf", conteudo=PDF, sub=""):
    return cliente.post(f"/api/lotes/{lote_id}/etapas/{etapa}/anexos", files=[("arquivos", (nome, conteudo, "application/pdf"))],
                        data={"sub": sub}, headers=_h(csrf))  # fmt: skip


def _registrar(cliente, csrf, lote_id, etapa, campos, sub=""):
    return cliente.post(f"/api/lotes/{lote_id}/etapas/{etapa}/registros", json={"sub": sub, "campos": campos}, headers=_h(csrf))


def _texto_pdf(conteudo: bytes) -> str:
    with pymupdf.open(stream=conteudo, filetype="pdf") as documento:
        return "\n".join(pagina.get_text() for pagina in documento)


# ---------------------------------------------------------------- novo lote, editar, cancelar


def test_novo_lote_com_sugestao_de_op(cliente, como, db):
    db.add(OrdemProducao(op="900001", cliente="CLIENTE EXEMPLO", coditem="12345", tipo="BOX", qt_lote=48,
                         descricao="INSTR. CONTROLE TRAVAMENTO BOX 7 5/8 EXEMPLO"))  # fmt: skip
    db.commit()
    pcp, csrf = como(modulos=["pcp"])
    sugestoes = pcp.get("/api/lotes/sugestoes-op", params={"q": "9000"}).json()
    assert sugestoes[0]["op"] == "900001" and sugestoes[0]["tipo"] == "BOX" and sugestoes[0]["qtd"] == 48
    assert sugestoes[0]["descricao_curta"] == "BOX 7 5/8 EXEMPLO" and sugestoes[0]["lotes"] == 0

    r = pcp.post("/api/lotes", json={"op": "900001", "numero": "26-4-900001", "tipo": "box", "qtd": 48}, headers=_h(csrf))
    assert r.status_code == 201, r.text
    lote = db.get(Lote, r.json()["id"])
    assert lote.tipo == "BOX" and lote.coditem == "12345" and lote.etapa == 0  # item veio do cadastro da OP
    assert pcp.post("/api/lotes", json={"op": "900001", "numero": "26-4-900001", "tipo": "BOX", "qtd": 1},
                    headers=_h(csrf)).status_code == 409  # fmt: skip
    assert pcp.post("/api/lotes", json={"op": "900001", "numero": "x", "tipo": "XYZ", "qtd": 1}, headers=_h(csrf)).status_code == 422
    assert pcp.post("/api/lotes", json={"op": "900001", "numero": "y", "tipo": "PIN", "qtd": 0}, headers=_h(csrf)).status_code == 422
    assert pcp.get("/api/lotes/sugestoes-op", params={"q": "9000"}).json()[0]["lotes"] == 1

    tt, csrf_tt = como(modulos=["producao_tt"])
    assert tt.post("/api/lotes", json={"op": "900002", "numero": "z", "tipo": "PIN", "qtd": 5}, headers=_h(csrf_tt)).status_code == 403
    assert tt.get("/api/lotes/sugestoes-op").status_code == 403


def test_editar_lote_limpo_e_com_registros(cliente, como, db):
    lote = _lote(db)
    pcp, csrf = como(modulos=["pcp"])
    corpo = {"op": "900001", "numero": "26-4-900009", "tipo": "PIN", "qtd": 70, "coditem": "12345"}
    r = pcp.patch(f"/api/lotes/{lote.id}", json=corpo, headers=_h(csrf))
    assert r.status_code == 200 and r.json()["mudou"] is True
    db.refresh(lote)
    assert lote.numero == "26-4-900009" and lote.qtd == 70

    db.add(Registro(lote_id=lote.id, etapa="receb_mp", status="aprovado", responsavel="Fulano"))
    db.commit()
    corpo["qtd"] = 71
    assert pcp.patch(f"/api/lotes/{lote.id}", json=corpo, headers=_h(csrf)).status_code == 403  # sem "pode aprovar"
    aprovador, csrf_ap = como(modulos=["qualidade"], pode_aprovar=True)
    assert aprovador.patch(f"/api/lotes/{lote.id}", json=corpo, headers=_h(csrf_ap)).status_code == 422  # falta o motivo
    r = aprovador.patch(f"/api/lotes/{lote.id}", json=corpo | {"motivo": "quantidade conferida na expedição"}, headers=_h(csrf_ap))
    assert r.status_code == 200, r.text
    auditoria = db.scalars(select(Auditoria).where(Auditoria.acao == "ALTERAR", Auditoria.entidade == "lote")).all()[-1]
    assert auditoria.detalhes["qtd"] == [70, 71] and auditoria.detalhes["motivo"] == "quantidade conferida na expedição"

    outro = lote_exemplo(db, numero="26-4-900010")
    assert aprovador.patch(f"/api/lotes/{outro.id}", json=corpo | {"motivo": "teste de número"}, headers=_h(csrf_ap)).status_code == 409


def test_cancelar_lote_libera_o_numero_e_respeita_o_databook(cliente, como, db, admin):
    lote = _lote(db, corrida="M999/26")
    db.add(Anexo(lote_id=lote.id, etapa="receb_mp", nome="cert.pdf", arquivo="lotes/1/anexos/cert.pdf"))
    db.add(DatabookEnviado(op="900001", tipo="PIN", lote="26-4-900001"))
    db.commit()
    qualidade, csrf = como(modulos=["qualidade"])
    assert qualidade.post(f"/api/lotes/{lote.id}/cancelar", json={"motivo": "lote em dobro"}, headers=_h(csrf)).status_code == 403
    # O administrador pode, mas o databook já foi enviado: bloqueia e deixa rastro
    r = cliente.post(f"/api/lotes/{lote.id}/cancelar", json={"motivo": "lote em dobro"}, headers=_h(admin))
    assert r.status_code == 409 and "databook" in r.json()["detail"]
    assert db.scalar(select(Auditoria).where(Auditoria.acao == "TENTATIVA_BLOQUEADA")) is not None

    db.query(DatabookEnviado).delete()
    db.commit()
    assert cliente.post(f"/api/lotes/{lote.id}/cancelar", json={"motivo": ""}, headers=_h(admin)).status_code == 422
    r = cliente.post(f"/api/lotes/{lote.id}/cancelar", json={"motivo": "lote criado em dobro"}, headers=_h(admin))
    assert r.status_code == 200, r.text
    db.expire_all()
    cancelado = db.get(Lote, lote.id)
    assert cancelado.cancelado_em and cancelado.cancelado_motivo == "lote criado em dobro" and cancelado.numero.endswith(f"-CANC{lote.id}")
    assert cliente.get(f"/api/lotes/{lote.id}").status_code == 404
    assert all(i["id"] != lote.id for i in cliente.get("/api/lotes").json()["itens"])
    # o número volta a ficar livre para o lote certo
    r = cliente.post("/api/lotes", json={"op": "900001", "numero": "26-4-900001", "tipo": "PIN", "qtd": 72}, headers=_h(admin))
    assert r.status_code == 201, r.text

    limpo = lote_exemplo(db, numero="26-4-900020")
    pcp, csrf_pcp = como(modulos=["pcp"])
    assert pcp.post(f"/api/lotes/{limpo.id}/cancelar", json={}, headers=_h(csrf_pcp)).status_code == 200  # lote limpo: sem motivo


# ---------------------------------------------------------------- registro pelo formulário


def test_dureza_usa_a_especificacao_abre_e_fecha_nc(cliente, como, db):
    _espec_pin(db)
    lote = _lote(db, etapa="dureza")
    inspetor, csrf = como(modulos=["qualidade"], nome="Fulano Inspetor")
    # O limite digitado (10 a 99) é ignorado: vale o cadastro (30 a 39)
    r = _registrar(inspetor, csrf, lote.id, "dureza", {"min": "10", "max": "99", "leituras": "P1 35 36\nP2-37-38", "equip": "DU-01"})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "aprovado"
    registro = db.get(Registro, r.json()["registro"]["id"])
    assert registro.responsavel == "Fulano Inspetor" and registro.usuario_id is not None  # o usuário logado, não um nome digitado
    linhas = registro.dados["report"]["tabelas"][0]["linhas"]
    assert linhas[0] == ["P1 pt1", "35", "OK"] and len(linhas) == 4
    assert ["Especificação", "30 a 39 HRC"] in registro.dados["report"]["kv"]

    r = _registrar(inspetor, csrf, lote.id, "dureza", {"leituras": "P1 41,5", "obs": "peça dura"})
    assert r.json()["status"] == "reprovado" and r.json()["nc"]["numero"].startswith("NC-")
    nc = db.scalar(select(NaoConformidade))
    assert nc.status == "aberta" and nc.registro_id == r.json()["registro"]["id"] and "peça dura" in nc.descricao
    assert inspetor.get(f"/api/lotes/{lote.id}").json()["lote"]["nc_aberta"] is True

    r = _registrar(inspetor, csrf, lote.id, "dureza", {"leituras": "P1 35"})
    assert r.json()["status"] == "aprovado" and r.json()["nc_encerrada"] == nc.numero
    db.refresh(nc)
    assert nc.status == "encerrada" and nc.disposicao == "retrabalho"

    erro = _registrar(inspetor, csrf, lote.id, "dureza", {"leituras": "P1 35 abc"})
    assert erro.status_code == 422 and "não é um número" in erro.json()["detail"]
    manual = _registrar(inspetor, csrf, lote.id, "dureza", {"leituras": "P1 35", "decisao": "reprovado"})
    assert manual.json()["status"] == "reprovado"


def test_formulario_so_vale_para_etapa_liberada(cliente, como, db):
    lote = _lote(db, etapa="receb_mp")
    inspetor, csrf = como(modulos=["qualidade"])
    r = _registrar(inspetor, csrf, lote.id, "dureza", {"min": "30", "leituras": "P1 35"})
    assert r.status_code == 409
    ark = lote_exemplo(db, numero="26-4-900002", tipo="ARK", etapa=5)
    assert _registrar(inspetor, csrf, ark.id, "dureza", {"min": "30", "leituras": "P1 35"}).status_code == 422  # ARK não faz dureza


def test_quimica_grava_corrida_e_fica_pendente_sem_certificado(cliente, como, db):
    lote = _lote(db)
    inspetor, csrf = como(modulos=["qualidade"])
    elementos = [{"elemento": "C", "valor": "0,30", "min": "0,28", "max": "0,33"}, {"elemento": "Mn", "valor": "0,9"}]
    campos = {"corrida": "M999/26", "fornecedor": "Fornecedor Exemplo", "elementos": elementos}
    r = _registrar(inspetor, csrf, lote.id, "receb_mp", campos)
    assert r.status_code == 201 and r.json()["status"] == "pendente" and r.json()["aviso"]  # exige documento anexado
    db.refresh(lote)
    assert lote.corrida == "M999/26"
    assert _anexar(inspetor, csrf, lote.id, "receb_mp").status_code == 201
    campos["elementos"][0]["valor"] = "0,40"
    r = _registrar(inspetor, csrf, lote.id, "receb_mp", campos)
    assert r.json()["status"] == "reprovado"
    report = db.get(Registro, r.json()["registro"]["id"]).dados["report"]
    assert report["tabelas"][0]["linhas"][0] == ["C", "0.4", "0.28", "0.33", "FORA"]
    assert _registrar(inspetor, csrf, lote.id, "receb_mp", {"elementos": []}).status_code == 422


def test_tracao_pendente_sem_validacao_e_charpy(cliente, como, db):
    _espec_pin(db)
    lote = _lote(db, etapa="lab_ext")
    inspetor, csrf = como(modulos=["qualidade"])
    _anexar(inspetor, csrf, lote.id, "lab_ext", sub="tracao")
    cps = [{"cp": "CP1", "le": "600", "lr": "700", "al": "20", "ra": "50"}]
    r = _registrar(inspetor, csrf, lote.id, "lab_ext", {"cps": cps}, sub="tracao")
    assert r.json()["status"] == "pendente"  # resultados dentro, mas ninguém validou
    r = _registrar(inspetor, csrf, lote.id, "lab_ext", {"cps": cps, "validado": True, "validador": "Fulano"}, sub="tracao")
    assert r.json()["status"] == "aprovado"
    fora = [{"cp": "CP1", "le": "500", "lr": "700", "al": "20"}]
    assert _registrar(inspetor, csrf, lote.id, "lab_ext", {"cps": fora, "validado": True}, sub="tracao").json()["status"] == "reprovado"
    conjuntos = [{"cp": "Conjunto 1", "j1": "30", "j2": "28", "j3": "26"}]
    r = _registrar(inspetor, csrf, lote.id, "lab_ext", {"conjuntos": conjuntos, "validado": True}, sub="charpy")
    assert r.json()["status"] == "aprovado"
    report = db.get(Registro, r.json()["registro"]["id"]).dados["report"]
    assert any("temperatura de ensaio -20 °C" in v for _, v in report["kv"])
    assert _registrar(inspetor, csrf, lote.id, "lab_ext", {"cps": cps}, sub="").status_code == 422  # precisa escolher o ensaio


def test_dimensional_usa_as_cotas_cadastradas(cliente, como, db):
    lote = _lote(db, etapa="usinagem", coditem="12345")
    db.add(EspecificacaoCota(coditem="12345", descricao="Largura", nominal="20", tol_min="-0,1", tol_max="+0,1"))
    db.commit()
    cota = db.scalar(select(EspecificacaoCota))
    inspetor, csrf = como(modulos=["producao_usinagem"])
    pagina = inspetor.get(f"/api/lotes/{lote.id}/etapas/usinagem").json()
    assert pagina["cotas"][0]["descricao"] == "Largura" and pagina["etapa"]["formulario"] == "dim"
    # a tela mandou outro nominal, mas a cota cadastrada vale
    linhas = [{"cota_id": cota.id, "descricao": "X", "nominal": "50", "tol_min": "-1", "tol_max": "1", "medidas": "20,05; 19,95"},
              {"descricao": "Comprimento", "nominal": "100", "tol_min": "-0,5", "tol_max": "0,5", "medidas": ""}]  # fmt: skip
    r = _registrar(inspetor, csrf, lote.id, "usinagem", {"cotas": linhas, "instrumento": "Paquímetro"})
    assert r.json()["status"] == "aprovado"
    linhas[0]["medidas"] = "20,2"
    assert _registrar(inspetor, csrf, lote.id, "usinagem", {"cotas": linhas}).json()["status"] == "reprovado"
    linhas[1]["medidas"] = "100"
    linhas[1]["nominal"] = "cem"
    assert _registrar(inspetor, csrf, lote.id, "usinagem", {"cotas": linhas}).status_code == 422


def test_tt_lp_visual_embalagem_e_simples(cliente, como, db):
    lote = _lote(db, etapa="embalagem", corrida="M999/26")
    inspetor, csrf = como(modulos=["qualidade"])
    curva = "0;25\n30;850\n90;850\n100;60"
    r = _registrar(inspetor, csrf, lote.id, "trat_termico", {"ciclo": "Têmpera", "alvo": "850", "patamar": "60", "curva": curva})
    assert r.json()["status"] == "aprovado"
    curto = _registrar(inspetor, csrf, lote.id, "trat_termico", {"alvo": "850", "patamar": "80", "curva": curva})
    assert curto.json()["status"] == "reprovado"
    assert _registrar(inspetor, csrf, lote.id, "lp", {"qtd_insp": "72", "indicacoes": "1"}).json()["status"] == "reprovado"
    assert _registrar(inspetor, csrf, lote.id, "tambor", {"ok": True}).json()["status"] == "aprovado"
    assert _registrar(inspetor, csrf, lote.id, "tambor", {}).json()["status"] == "reprovado"
    assert _registrar(inspetor, csrf, lote.id, "embalagem", {"qtd_emb": "72", "parafusos": "72"}).json()["status"] == "aprovado"
    r = _registrar(inspetor, csrf, lote.id, "visual", {"qtd_aprov": "3", "ano": "2026", "tri": "4"})
    assert r.json()["status"] == "aprovado"
    report = db.get(Registro, r.json()["registro"]["id"]).dados["report"]
    assert report["laser"] == ["2026T4-CM999/26-L26-4-900001-001", "2026T4-CM999/26-L26-4-900001-002", "2026T4-CM999/26-L26-4-900001-003"]
    assert _registrar(inspetor, csrf, lote.id, "visual", {"qtd_aprov": "3", "ano": "26", "tri": "5"}).status_code == 422

    csv = inspetor.get(f"/api/lotes/{lote.id}/laser.csv")
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    linhas = csv.content.decode("utf-8-sig").splitlines()
    assert linhas[0] == "sequencial;codigo_gravacao" and linhas[3] == "3;2026T4-CM999/26-L26-4-900001-003"


def test_laser_sem_formulario_calcula_pela_data_e_quantidade(cliente, db, admin):
    lote = _lote(db, etapa="visual", qtd=2)
    assert cliente.get(f"/api/lotes/{lote.id}/laser.csv").status_code == 404
    db.add(Registro(lote_id=lote.id, etapa="visual", status="aprovado", quando=datetime(2026, 5, 10, 9, 0),
                    dados={"report": "visual-sistema", "laser_qtd": 2}))  # fmt: skip
    db.commit()
    linhas = cliente.get(f"/api/lotes/{lote.id}/laser.csv").content.decode("utf-8-sig").splitlines()
    assert linhas[1:] == ["1;2026T2-CSC-L26-4-900001-001", "2;2026T2-CSC-L26-4-900001-002"]


# ---------------------------------------------------------------- aprovar por documento, anexos e avanço


def test_aprovar_por_anexo_exige_documento_e_avanca_o_lote(cliente, como, db):
    db.add(Prestador(codigo="LAB01", razao_social="Laboratório Exemplo", tipo_servico="Lab mecânico (tração/Charpy)"))
    db.add(Prestador(codigo="REV01", razao_social="Revestidor Exemplo", tipo_servico="Revestimento fosfato"))
    db.commit()
    lote = _lote(db, tipo="BOX")
    usuario, csrf = como(modulos=["producao_tt"])
    r = usuario.post(f"/api/lotes/{lote.id}/etapas/receb_mp/aprovar-por-anexo", json={"corrida": "M999/26"}, headers=_h(csrf))
    assert r.status_code == 422  # Receb. MP exige o certificado anexado
    assert _anexar(usuario, csrf, lote.id, "receb_mp", nome="Certificado MP.pdf").status_code == 201
    r = usuario.post(f"/api/lotes/{lote.id}/etapas/receb_mp/aprovar-por-anexo", json={"corrida": "M999/26"}, headers=_h(csrf))
    assert r.status_code == 200, r.text
    assert r.json()["avancou"] == 1
    db.refresh(lote)
    assert lote.corrida == "M999/26" and lote.etapa == fluxo.INDICE["trat_termico"]

    # Etapa futura também pode ser aprovada pelo documento; tração e Charpy de uma vez, com o laboratório
    _anexar(usuario, csrf, lote.id, "lab_ext", nome="laudo.pdf", sub="tracao")
    assert usuario.post(f"/api/lotes/{lote.id}/etapas/lab_ext/aprovar-por-anexo", json={"prestador": "REV01"},
                        headers=_h(csrf)).status_code == 422  # revestidor não faz ensaio  # fmt: skip
    r = usuario.post(f"/api/lotes/{lote.id}/etapas/lab_ext/aprovar-por-anexo", json={"prestador": "lab01"}, headers=_h(csrf))
    assert r.json()["aprovados"] == ["tracao", "charpy"] and r.json()["avancou"] == 0  # o TT ainda não foi aprovado
    report = db.scalars(select(Registro).where(Registro.etapa == "lab_ext")).first().dados["report"]
    assert ["Laboratório externo", "LAB01 - Laboratório Exemplo"] in report["kv"]
    again = usuario.post(f"/api/lotes/{lote.id}/etapas/lab_ext/aprovar-por-anexo", json={}, headers=_h(csrf))
    assert again.json()["aprovados"] == []

    # Etapa sem documento próprio: "marcar como concluída" sem anexo
    r = usuario.post(f"/api/lotes/{lote.id}/etapas/trat_termico/aprovar-por-anexo", json={}, headers=_h(csrf))
    assert r.status_code == 200
    db.refresh(lote)
    assert lote.etapa == fluxo.INDICE["dureza"]  # andou até a primeira etapa ainda não aprovada


def test_anexos_conferem_o_arquivo_e_sao_removidos_com_motivo(cliente, como, db, pasta_arquivos):
    lote = _lote(db)
    usuario, csrf = como(modulos=["qualidade"])
    dois = [("arquivos", ("bom.pdf", PDF, "application/pdf")), ("arquivos", ("ruim.exe", b"MZ", "application/x-msdownload"))]
    r = usuario.post(f"/api/lotes/{lote.id}/etapas/receb_mp/anexos", files=dois, headers=_h(csrf))
    assert r.status_code == 201 and len(r.json()["salvos"]) == 1 and "ruim.exe" in r.json()["ignorados"][0]
    anexo = db.get(Anexo, r.json()["salvos"][0]["id"])
    assert anexo.arquivo.startswith(f"lotes/{lote.id}/anexos/") and (pasta_arquivos / anexo.arquivo).read_bytes() == PDF
    assert _anexar(usuario, csrf, lote.id, "receb_mp", nome="falso.pdf", conteudo=b"MZ").status_code == 422

    fotos = usuario.post(f"/api/lotes/{lote.id}/etapas/visual/fotos-registro", files=[("fotos", ("peca.png", PNG, "image/png"))],
                         headers=_h(csrf))  # fmt: skip
    assert fotos.status_code == 201 and fotos.json()["salvos"][0]["apenas_registro"] is True

    assert usuario.post(f"/api/anexos/{anexo.id}/remover", json={"motivo": ""}, headers=_h(csrf)).status_code == 422
    assert usuario.post(f"/api/anexos/{anexo.id}/remover", json={"motivo": "arquivo da OP errada"}, headers=_h(csrf)).status_code == 200
    assert usuario.post(f"/api/anexos/{anexo.id}/remover", json={"motivo": "de novo"}, headers=_h(csrf)).status_code == 409
    db.refresh(anexo)
    assert anexo.removido_em and anexo.removido_motivo == "arquivo da OP errada" and (pasta_arquivos / anexo.arquivo).exists()
    pagina = usuario.get(f"/api/lotes/{lote.id}/etapas/receb_mp").json()
    assert pagina["anexos"] == []


def test_avancar_respeita_a_aprovacao_e_a_materia_prima(cliente, como, db):
    lote = _lote(db, corrida="M999/26")
    usuario, csrf = como(modulos=["qualidade"])
    assert usuario.post(f"/api/lotes/{lote.id}/avancar", headers=_h(csrf)).status_code == 409  # nada aprovado ainda
    db.add(Registro(lote_id=lote.id, etapa="receb_mp", status="aprovado"))
    db.add(MateriaPrima(corrida="M999/26", status="reprovada", obs_aprovacao="carbono alto"))
    db.commit()
    r = usuario.post(f"/api/lotes/{lote.id}/avancar", json={}, headers=_h(csrf))
    assert r.status_code == 409 and "REPROVADA" in r.json()["detail"]
    assert db.scalar(select(Auditoria).where(Auditoria.acao == "TENTATIVA_BLOQUEADA")) is not None
    assert usuario.post(f"/api/lotes/{lote.id}/avancar", json={"forcar": True, "motivo": "liberado"}, headers=_h(csrf)).status_code == 403
    aprovador, csrf_ap = como(modulos=["qualidade"], pode_aprovar=True)
    assert aprovador.post(f"/api/lotes/{lote.id}/avancar", json={"forcar": True}, headers=_h(csrf_ap)).status_code == 422
    r = aprovador.post(f"/api/lotes/{lote.id}/avancar", json={"forcar": True, "motivo": "concessão do cliente"}, headers=_h(csrf_ap))
    assert r.status_code == 200 and r.json()["etapa"] == 1

    ark = lote_exemplo(db, numero="26-4-900002", tipo="ARK", etapa=fluxo.INDICE["trat_termico"])
    db.add(Registro(lote_id=ark.id, etapa="trat_termico", status="aprovado"))
    db.commit()
    assert usuario.post(f"/api/lotes/{ark.id}/avancar", headers=_h(csrf)).json()["etapa"] == fluxo.INDICE["lab_ext"]  # pula a dureza


def test_importar_certificado_da_corrida(cliente, como, db, pasta_arquivos):
    lote = _lote(db, corrida="M999/26")
    (pasta_arquivos / "materia_prima/1").mkdir(parents=True)
    (pasta_arquivos / "materia_prima/1/cert.pdf").write_bytes(PDF)
    (pasta_arquivos / "materia_prima/1/cert_APROVADO.pdf").write_bytes(PDF + b" carimbado")
    mp = MateriaPrima(corrida="M999/26", status="aprovada")
    db.add(mp)
    db.flush()
    db.add(MateriaPrimaAnexo(materia_prima_id=mp.id, nome="cert.pdf", arquivo="materia_prima/1/cert.pdf"))
    db.add(MateriaPrimaAnexo(materia_prima_id=mp.id, nome="cert_APROVADO.pdf", arquivo="materia_prima/1/cert_APROVADO.pdf"))
    db.commit()
    usuario, csrf = como(modulos=["qualidade"])
    assert usuario.get(f"/api/lotes/{lote.id}/etapas/receb_mp").json()["certificados_corrida"] == 2
    r = usuario.post(f"/api/lotes/{lote.id}/importar-certificado-mp", headers=_h(csrf))
    assert r.status_code == 201, r.text
    assert [a["nome"] for a in r.json()["salvos"]] == ["cert_APROVADO.pdf"]  # só a cópia carimbada
    anexo = db.scalar(select(Anexo).where(Anexo.lote_id == lote.id))
    assert (pasta_arquivos / anexo.arquivo).read_bytes().endswith(b"carimbado")
    sem = lote_exemplo(db, numero="26-4-900002")
    assert usuario.post(f"/api/lotes/{sem.id}/importar-certificado-mp", headers=_h(csrf)).status_code == 422


def test_importacao_em_massa_por_prefixo(cliente, como, db):
    lote = _lote(db)
    usuario, csrf = como(modulos=["qualidade"])
    arquivos = [("arquivos", (nome, PDF, "application/pdf"))
                for nome in ("1-Certificado MP.pdf", "2-TT.pdf", "3b_Dureza.pdf", "6-Tracao.pdf", "anotacoes.pdf")]  # fmt: skip
    r = usuario.post(f"/api/lotes/{lote.id}/importar", files=arquivos, headers=_h(csrf))
    assert r.status_code == 201, r.text
    assert len(r.json()["importados"]) == 4 and r.json()["avulsos"] == ["anotacoes.pdf"]
    detalhe = usuario.get(f"/api/lotes/{lote.id}").json()
    situacao = {e["chave"]: e["situacao"] for e in detalhe["etapas"]}
    # tambor e usinagem não têm documento no checklist: aprovam sozinhos
    assert situacao["receb_mp"] == situacao["dureza"] == situacao["tambor"] == situacao["usinagem"] == "aprovada"
    assert situacao["lab_ext"] != "aprovada"  # falta o Charpy
    assert detalhe["cursor"] == fluxo.INDICE["lab_ext"] and detalhe["avulsos"][0]["nome"] == "anotacoes.pdf"
    assert detalhe["importacao"]["indice"] == "PIN/BOX" and detalhe["importacao"]["checklist"][0]["prefixo"] == "1"

    ark = lote_exemplo(db, numero="26-4-900002", tipo="ARK")
    r = usuario.post(f"/api/lotes/{ark.id}/importar", files=[("arquivos", ("0-Capa.pdf", PDF, "application/pdf"))], headers=_h(csrf))
    assert sorted(i.split("→ ")[1] for i in r.json()["importados"]) == ["Dimensional final", "Visual / Laser"]


def test_pagina_da_etapa_traz_cadastros_e_envios(cliente, como, db):
    _espec_pin(db)
    lote = _lote(db, etapa="dureza")
    db.add(Equipamento(codigo="DU-01", descricao="Durômetro", marca="Marca Exemplo", certificado="C-1",
                       data_calibracao=date(2026, 1, 10), validade_calibracao=date(2027, 1, 10)))  # fmt: skip
    db.add(Prestador(codigo="LP01", razao_social="NDT Exemplo", tipo_servico="NDT - líquido penetrante"))
    envio = EnvioPrestador(numero="EP-2026-001", prestador="NDT Exemplo", tipo_servico="NDT - líquido penetrante",
                           data_envio=date(2026, 11, 20), status="enviado")  # fmt: skip
    db.add(envio)
    db.flush()
    db.add(EnvioPrestadorLote(envio_id=envio.id, lote_id=lote.id))
    db.commit()
    usuario, _ = como(modulos=[])  # só consulta: vê a página
    pagina = usuario.get(f"/api/lotes/{lote.id}/etapas/dureza").json()
    assert pagina["espec"]["dureza_min"] == 30 and pagina["etapa"]["liberada"] is True
    assert pagina["equipamentos"][0]["texto"].startswith("Durômetro - Marca Marca Exemplo - COD.DU-01 - Calibração Certificado C-1")
    lp = usuario.get(f"/api/lotes/{lote.id}/etapas/lp").json()
    assert lp["prestadores"][0]["codigo"] == "LP01" and lp["envios"][0]["numero"] == "EP-2026-001"
    assert lp["envios"][0]["laudo_lancado"] is False and lp["etapa"]["liberada"] is False
    lab = usuario.get(f"/api/lotes/{lote.id}/etapas/lab_ext", params={"sub": "charpy"}).json()
    assert lab["sub"] == "charpy" and [s["sub"] for s in lab["etapa"]["subs"]] == ["tracao", "charpy"]
    assert usuario.get(f"/api/lotes/{lote.id}/etapas/nao_existe").status_code == 404


def test_pdf_do_registro(cliente, como, db):
    parametros.gravar(db, "cliente_nome", "CLIENTE EXEMPLO", "admin")
    db.commit()
    _espec_pin(db)
    lote = _lote(db, etapa="dureza", corrida="M999/26")
    inspetor, csrf = como(modulos=["qualidade"], nome="Fulano Inspetor")
    r = _registrar(inspetor, csrf, lote.id, "dureza", {"leituras": "P1 35\nP2 45", "obs": "segunda peça dura"})
    pdf = inspetor.get(f"/api/registros/{r.json()['registro']['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and pdf.headers["content-type"] == "application/pdf"
    texto = _texto_pdf(pdf.content)
    for esperado in ("Relatório de Ensaio de Dureza (HRC)", "CLIENTE EXEMPLO", "26-4-900001", "M999/26", "FORA", "segunda peça dura",
                     "Fulano Inspetor", "AçoKorte Indústria"):  # fmt: skip
        assert esperado in texto, esperado

    tt = _registrar(inspetor, csrf, lote.id, "trat_termico", {"alvo": "850", "patamar": "30", "curva": "0;20\n20;850\n80;850"})
    assert "Curva do ciclo de tratamento térmico" in _texto_pdf(inspetor.get(f"/api/registros/{tt.json()['registro']['id']}/pdf").content)

    # Registro de relatório gerado pelo sistema: abre o PDF anexado à etapa
    _anexar(inspetor, csrf, lote.id, "dureza", nome="RIP-35.pdf")
    sistema = Registro(lote_id=lote.id, etapa="dureza", status="aprovado", dados={"report": "dureza-sistema"})
    vazio = Registro(lote_id=lote.id, etapa="dureza", status="aprovado", dados=None)
    db.add_all([sistema, vazio])
    db.commit()
    resposta = inspetor.get(f"/api/registros/{sistema.id}/pdf")
    assert resposta.status_code == 200 and resposta.content == PDF
    assert inspetor.get(f"/api/registros/{vazio.id}/pdf").status_code == 404


def test_mapa_e_detalhe_do_lote(cliente, como, db):
    lote = _lote(db, etapa="trat_termico", coditem="12345")
    db.add(Registro(lote_id=lote.id, etapa="receb_mp", status="aprovado", responsavel="Fulano", quando=datetime(2026, 11, 20, 9, 0)))
    reprovado = Registro(lote_id=lote.id, etapa="trat_termico", status="reprovado", responsavel="Fulano")
    db.add(reprovado)
    db.flush()
    db.add(NaoConformidade(numero="NC-2026-001", lote_id=lote.id, etapa="trat_termico", registro_id=reprovado.id, status="aberta"))
    db.add(Anexo(lote_id=lote.id, etapa="receb_mp", nome="cert.pdf", arquivo="x.pdf"))
    db.add(Anexo(lote_id=lote.id, etapa="receb_mp", nome="foto.png", arquivo="y.png", apenas_registro=True))
    db.commit()
    usuario, _ = como(modulos=[])
    mapa = usuario.get(f"/api/lotes/{lote.id}/mapa").json()
    assert [linha["nome"] for linha in mapa["linhas"]][:3] == ["Receb. MP", "Trat. térmico", "Dureza HRC"]
    assert mapa["linhas"][0]["status"] == "aprovado" and [a["nome"] for a in mapa["linhas"][0]["anexos"]] == ["cert.pdf"]
    assert mapa["linhas"][3]["nome"] == "Tração / Charpy / Ensaio de tração" and mapa["total_etapas"] == 11 and len(mapa["linhas"]) == 12
    detalhe = usuario.get(f"/api/lotes/{lote.id}").json()
    tt = next(e for e in detalhe["etapas"] if e["chave"] == "trat_termico")
    assert tt["nc_pendente"]["numero"] == "NC-2026-001" and detalhe["tem_dados"] is True and detalhe["pode_avancar"] is False
    assert next(e for e in detalhe["etapas"] if e["chave"] == "receb_mp")["n_documentos"] == 1


@pytest.mark.parametrize(
    ("metodo", "caminho", "extra"),
    [
        ("post", "/api/lotes/{id}/etapas/receb_mp/registros", {"json": {"campos": {}}}),
        ("post", "/api/lotes/{id}/etapas/receb_mp/aprovar-por-anexo", {"json": {}}),
        ("post", "/api/lotes/{id}/etapas/receb_mp/anexos", {"files": [("arquivos", ("a.pdf", PDF, "application/pdf"))]}),
        ("post", "/api/lotes/{id}/etapas/visual/fotos-registro", {"files": [("fotos", ("a.png", PNG, "image/png"))]}),
        ("post", "/api/lotes/{id}/avancar", {"json": {}}),
        ("post", "/api/lotes/{id}/importar", {"files": [("arquivos", ("1-a.pdf", PDF, "application/pdf"))]}),
        ("post", "/api/lotes/{id}/importar-certificado-mp", {}),
        ("post", "/api/anexos/{anexo}/remover", {"json": {"motivo": "teste"}}),
        ("patch", "/api/lotes/{id}", {"json": {"op": "1", "numero": "2", "tipo": "PIN", "qtd": 1}}),
        ("post", "/api/lotes/{id}/cancelar", {"json": {}}),
        ("post", "/api/lotes", {"json": {"op": "1", "numero": "2", "tipo": "PIN", "qtd": 1}}),
    ],
)
def test_quem_nao_trabalha_no_lote_nao_grava(cliente, como, db, metodo, caminho, extra):
    lote = _lote(db)
    anexo = Anexo(lote_id=lote.id, etapa="receb_mp", nome="a.pdf", arquivo="a.pdf")
    db.add(anexo)
    db.commit()
    so_cadastros, csrf = como(modulos=["cadastros"])
    resposta = getattr(so_cadastros, metodo)(caminho.format(id=lote.id, anexo=anexo.id), headers=_h(csrf), **extra)
    assert resposta.status_code == 403, resposta.text
    assert so_cadastros.get(f"/api/lotes/{lote.id}/etapas/receb_mp").status_code == 200  # ver continua liberado


def test_sem_login_nao_ve_a_etapa(cliente, db):
    lote = _lote(db)
    assert cliente.get(f"/api/lotes/{lote.id}/etapas/receb_mp").status_code == 401
    assert cliente.get(f"/api/lotes/{lote.id}/mapa").status_code == 401
