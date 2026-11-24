"""Envios a prestador externo: lista, formulário, situação, fotos, PDF e modelo .docx do laboratório."""
import io
from datetime import date, datetime, timedelta
from decimal import Decimal

import docx
import pymupdf
from conftest import lote_exemplo
from PIL import Image
from sqlalchemy import select

from app import parametros
from app.api_envios import envios_sem_retorno
from app.config import agora_local
from app.models import Auditoria, EnvioPrestador, EnvioPrestadorFoto, EspecificacaoTipo, Evento, OrdemProducao, Prestador, Registro

ANO = agora_local().year
HOJE = agora_local().date()


def _h(csrf: str) -> dict:
    return {"X-CSRF-Token": csrf}


def _base(db, **extra_lote):
    """Prestador, especificação de tração/Charpy do PIN e um lote PIN fictícios."""
    db.add(Prestador(codigo="P1", razao_social="LAB EXEMPLO ENSAIOS", tipo_servico="Lab mecânico (tração/Charpy)"))
    db.add(Prestador(codigo="P2", razao_social="REVESTIDORA EXEMPLO", tipo_servico="Revestimento fosfato"))
    db.add(EspecificacaoTipo(tipo="PIN", dureza_min=Decimal("30"), dureza_max=Decimal("39"), tr_le_min=Decimal("517"),
                             tr_le_max=Decimal("655"), tr_al_min=Decimal("18.5"), ch_temp="-20 °C", ch_med_min=Decimal("27")))  # fmt: skip
    db.add(OrdemProducao(op="900001", cliente="CLIENTE EXEMPLO LTDA", coditem="123456", descricao="INSTR. CONTROLE TRAVAMENTO PIN 18"))
    db.commit()
    return lote_exemplo(db, **extra_lote)


def _corpo(lote_ids, tipo="Ensaio de tração + Charpy", prestador="LAB EXEMPLO ENSAIOS", **extra):
    itens = [{"lote_id": i, "qt_cp_tracao": 2, "qt_cp_impacto": 3} for i in lote_ids]
    return {"tipo_servico": tipo, "prestador": prestador, "data_envio": str(HOJE), "data_emissao": str(HOJE),
            "responsavel": "Fulano", "observacoes": "CPs usinados", "itens": itens, **extra}  # fmt: skip


def _png() -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(saida, format="PNG")
    return saida.getvalue()


def test_criar_envio_congela_especificacao_e_registra_no_lote(cliente, admin, db):
    lote = _base(db)
    r = cliente.post("/api/envios", json=_corpo([lote.id]), headers=_h(admin))
    assert r.status_code == 201, r.text
    assert r.json()["numero"] == f"EP-{ANO}-001"
    envio_id = r.json()["id"]

    d = cliente.get(f"/api/envios/{envio_id}").json()
    assert d["status"] == "enviado" and d["natureza"]["classe"] == "cp" and d["modo_pecas"] is False
    assert d["rotulo_fotos"] == "Fotos dos corpos de prova"
    assert d["criado_por"] == "Administrador" and d["responsavel"] == "Fulano"
    assert d["itens"][0]["qt_cp_tracao"] == 2 and d["itens"][0]["qt_cp_impacto"] == 3
    assert d["itens"][0]["cliente"] == "CLIENTE" and d["itens"][0]["descricao"] == "PIN 18"
    assert d["totais"]["qt_cp_tracao"] == 2 and d["qtd_cp_impacto"] == 3
    spec = d["especificacao"][0]
    assert spec["tipo"] == "PIN" and spec["material"] == "SC 4330 (ASTM A958)"
    assert ["Limite de escoamento (LE)", "517–655 MPa"] in spec["tracao"]
    assert ["Alongamento mín.", "≥ 18,5 %"] in spec["tracao"]
    assert ["Temperatura do ensaio", "-20 °C"] in spec["charpy"] and ["Charpy — média mín.", "≥ 27 J"] in spec["charpy"]
    # Mudar a especificação depois não mexe no envio (fica congelada)
    db.get(EspecificacaoTipo, "PIN").tr_le_min = Decimal("600")
    db.commit()
    assert cliente.get(f"/api/envios/{envio_id}").json()["especificacao"][0]["tracao"][0][1] == "517–655 MPa"

    eventos = db.scalars(select(Evento.texto).where(Evento.lote_id == lote.id)).all()
    assert any(f"EP-{ANO}-001" in t and "LAB EXEMPLO ENSAIOS" in t for t in eventos)
    acoes = db.scalars(select(Auditoria.acao).where(Auditoria.entidade == "envio_prestador")).all()
    assert "CRIAR" in acoes


def test_lista_por_aba_contagens_e_alerta_de_envio_parado(cliente, admin, db):
    lote = _base(db)
    a = cliente.post("/api/envios", json=_corpo([lote.id]), headers=_h(admin)).json()["id"]
    b = cliente.post("/api/envios", json=_corpo([lote.id], data_envio=str(HOJE - timedelta(days=12))), headers=_h(admin)).json()["id"]
    lista = cliente.get("/api/envios").json()
    assert [e["id"] for e in lista["itens"]] == [b, a]
    assert lista["contagens"] == {"ativos": 2, "retornados": 0, "cancelados": 0}
    parado = next(e for e in lista["itens"] if e["id"] == b)
    assert parado["dias_envio"] == 12 and parado["parado"] is True and parado["total_pecas"] == 72
    assert [e["numero"] for e in envios_sem_retorno(db)] == [f"EP-{ANO}-002"]
    assert envios_sem_retorno(db, dias=30) == []

    cliente.post(f"/api/envios/{a}/status", json={"status": "retornado"}, headers=_h(admin))
    lista = cliente.get("/api/envios?aba=retornados").json()
    assert [e["id"] for e in lista["itens"]] == [a] and lista["contagens"]["retornados"] == 1


def test_quem_nao_tem_o_modulo_nao_acessa(cliente, admin, db, como):
    lote = _base(db)
    pcp, csrf_pcp = como(modulos=["pcp"])
    assert pcp.get("/api/envios").status_code == 403
    assert pcp.get("/api/envios/opcoes").status_code == 403
    assert pcp.post("/api/envios", json=_corpo([lote.id]), headers=_h(csrf_pcp)).status_code == 403
    usinagem, csrf = como(modulos=["producao_usinagem"])
    assert usinagem.post("/api/envios", json=_corpo([lote.id]), headers=_h(csrf)).status_code == 201
    envio_id = usinagem.get("/api/envios").json()["itens"][0]["id"]
    assert pcp.get(f"/api/envios/{envio_id}/pdf").status_code == 403
    assert pcp.post(f"/api/envios/{envio_id}/status", json={"status": "retornado"}, headers=_h(csrf_pcp)).status_code == 403


def test_validacoes_do_formulario(cliente, admin, db):
    lote = _base(db)
    ark = lote_exemplo(db, numero="26-4-900002", op="900002", tipo="ARK")
    casos = [
        (_corpo([lote.id], tipo="Ensaio de dureza"), "tipo de serviço"),
        (_corpo([lote.id], prestador="  "), "prestador"),
        (_corpo([lote.id], data_envio=None), "data de envio"),
        (_corpo([]), "ao menos um lote"),
        (_corpo([9999]), "não existe"),
        (_corpo([ark.id], tipo="Revestimento fosfato", prestador="REVESTIDORA EXEMPLO"), "não passa por"),
    ]
    for corpo, trecho in casos:
        r = cliente.post("/api/envios", json=corpo, headers=_h(admin))
        assert r.status_code == 422 and trecho in r.json()["detail"], (trecho, r.text)
    corpo = _corpo([lote.id], tipo="Revestimento fosfato", prestador="REVESTIDORA EXEMPLO")
    corpo["itens"][0]["peso_liq"] = "abc"
    r = cliente.post("/api/envios", json=corpo, headers=_h(admin))
    assert r.status_code == 422 and "Peso inválido" in r.json()["detail"]
    corpo["itens"][0].update(peso_liq="12,5", peso_bruto=13.75, qt_liberar=70, volumes=2)
    r = cliente.post("/api/envios", json=corpo, headers=_h(admin))
    assert r.status_code == 201, r.text
    d = cliente.get(f"/api/envios/{r.json()['id']}").json()
    assert d["modo_pecas"] is True and d["natureza"]["classe"] == "pecas" and d["especificacao"] == []
    assert d["itens"][0]["peso_liq"] == 12.5 and d["totais"]["peso_bruto"] == 13.75 and d["totais"]["qt_liberar"] == 70
    assert db.scalar(select(EnvioPrestador).where(EnvioPrestador.numero == f"EP-{ANO}-001")) is not None  # só o válido gravou


def test_situacao_retorno_reabertura_e_cancelamento(cliente, admin, db):
    lote = _base(db)
    envio_id = cliente.post("/api/envios", json=_corpo([lote.id]), headers=_h(admin)).json()["id"]
    r = cliente.post(f"/api/envios/{envio_id}/status", json={"status": "retornado", "data_retorno": str(HOJE - timedelta(days=5))},
                     headers=_h(admin))  # fmt: skip
    assert r.status_code == 422 and "antes da data de envio" in r.json()["detail"]
    assert cliente.post(f"/api/envios/{envio_id}/status", json={"status": "retornado"}, headers=_h(admin)).status_code == 200
    assert cliente.get(f"/api/envios/{envio_id}").json()["data_retorno"] == str(HOJE)
    r = cliente.post(f"/api/envios/{envio_id}/status", json={"status": "cancelado", "motivo": "engano"}, headers=_h(admin))
    assert r.status_code == 409  # retornado só volta para enviado
    assert cliente.post(f"/api/envios/{envio_id}/status", json={"status": "enviado"}, headers=_h(admin)).status_code == 200
    assert cliente.get(f"/api/envios/{envio_id}").json()["data_retorno"] is None
    r = cliente.post(f"/api/envios/{envio_id}/status", json={"status": "cancelado"}, headers=_h(admin))
    assert r.status_code == 422 and "motivo" in r.json()["detail"]
    r = cliente.post(f"/api/envios/{envio_id}/status", json={"status": "cancelado", "motivo": "Lançado em duplicidade"}, headers=_h(admin))
    assert r.status_code == 200
    d = cliente.get(f"/api/envios/{envio_id}").json()
    assert d["status"] == "cancelado" and d["cancelado_motivo"] == "Lançado em duplicidade" and d["pode_editar"] is False
    assert db.get(EnvioPrestador, envio_id) is not None  # nada é apagado
    assert cliente.post(f"/api/envios/{envio_id}/status", json={"status": "enviado"}, headers=_h(admin)).status_code == 409
    assert cliente.put(f"/api/envios/{envio_id}", json=_corpo([lote.id]), headers=_h(admin)).status_code == 409
    assert cliente.post(f"/api/envios/{envio_id}/status", json={"status": "xyz"}, headers=_h(admin)).status_code == 422
    acoes = db.scalars(select(Auditoria.acao).where(Auditoria.entidade == "envio_prestador")).all()
    assert "CANCELAR" in acoes and "STATUS" in acoes


def test_laudo_lancado_na_etapa_marca_o_retorno(cliente, admin, db):
    lote = _base(db)
    so_tracao = cliente.post("/api/envios", json=_corpo([lote.id], tipo="Ensaio de tração"), headers=_h(admin)).json()["id"]
    ambos = cliente.post("/api/envios", json=_corpo([lote.id]), headers=_h(admin)).json()["id"]
    assert cliente.get(f"/api/envios/{so_tracao}").json()["todos_retornaram"] is False
    quando = datetime.combine(HOJE, datetime.min.time()).replace(hour=15)
    db.add(Registro(lote_id=lote.id, etapa="lab_ext", sub="tracao", status="reprovado", quando=quando))
    db.add(Registro(lote_id=lote.id, etapa="lp", sub="", status="aprovado", quando=quando))
    db.commit()
    d = cliente.get(f"/api/envios/{so_tracao}").json()
    assert d["itens"][0]["retornou"] is True and d["todos_retornaram"] is True
    assert d["etapa_referencia"] == "Ensaios de tração e impacto Charpy"
    assert cliente.get(f"/api/envios/{ambos}").json()["todos_retornaram"] is False  # falta o Charpy
    # Registro anterior ao envio não conta
    antigo = cliente.post("/api/envios", json=_corpo([lote.id], tipo="Ensaio de tração", data_envio=str(HOJE + timedelta(days=1))),
                          headers=_h(admin)).json()["id"]  # fmt: skip
    assert cliente.get(f"/api/envios/{antigo}").json()["todos_retornaram"] is False


def test_editar_troca_lotes_e_quantidades_e_refaz_especificacao_so_quando_precisa(cliente, admin, db):
    lote = _base(db)
    outro = lote_exemplo(db, numero="26-4-900002", op="900002", tipo="ARK", qtd=10)
    envio_id = cliente.post("/api/envios", json=_corpo([lote.id]), headers=_h(admin)).json()["id"]
    db.get(EspecificacaoTipo, "PIN").tr_le_min = Decimal("600")
    db.commit()
    corpo = _corpo([lote.id])
    corpo["itens"][0]["qt_cp_tracao"] = 4
    assert cliente.put(f"/api/envios/{envio_id}", json=corpo, headers=_h(admin)).status_code == 200
    d = cliente.get(f"/api/envios/{envio_id}").json()
    assert d["itens"][0]["qt_cp_tracao"] == 4 and d["qtd_cp_tracao"] == 4
    assert d["especificacao"][0]["tracao"][0][1] == "517–655 MPa"  # mesmos tipos: continua congelada

    corpo = _corpo([outro.id], tipo="Ensaio Charpy")
    assert cliente.put(f"/api/envios/{envio_id}", json=corpo, headers=_h(admin)).status_code == 200
    d = cliente.get(f"/api/envios/{envio_id}").json()
    assert [i["lote_id"] for i in d["itens"]] == [outro.id] and d["tipo_servico"] == "Ensaio Charpy"
    assert [s["tipo"] for s in d["especificacao"]] == ["ARK"] and d["especificacao"][0]["vazio"] is True
    textos = db.scalars(select(Evento.texto).where(Evento.lote_id == lote.id)).all()
    assert any("retirado do envio" in t for t in textos)
    alteracao = db.scalars(select(Auditoria).where(Auditoria.acao == "ALTERAR", Auditoria.entidade == "envio_prestador")).all()[-1]
    assert alteracao.detalhes["lotes"] == [["26-4-900001"], ["26-4-900002"]]


def test_lotes_disponiveis_lista_livre_e_filtra_revestimento(cliente, admin, db):
    lote = _base(db)
    ark = lote_exemplo(db, numero="26-4-900002", op="900002", tipo="ARK")
    cancelado = lote_exemplo(db, numero="26-4-900003", op="900003", cancelado_em=datetime(2026, 11, 21))
    r = cliente.get("/api/envios/lotes-disponiveis?tipo_servico=Ensaio Charpy").json()
    assert {x["id"] for x in r["lotes"]} == {lote.id, ark.id}
    assert r["lotes"][0]["etapa_atual"] == "Receb. MP" and r["natureza"]["classe"] == "cp"
    r = cliente.get("/api/envios/lotes-disponiveis?tipo_servico=Revestimento fosfato").json()
    assert [x["id"] for x in r["lotes"]] == [lote.id]
    r = cliente.get("/api/envios/lotes-disponiveis?tipo_servico=Revestimento oxidação negra").json()
    assert [x["id"] for x in r["lotes"]] == [ark.id]
    assert cliente.get("/api/envios/lotes-disponiveis?tipo_servico=Qualquer").status_code == 422
    assert cancelado.id not in {x["id"] for x in cliente.get("/api/envios/lotes-disponiveis").json()["lotes"]}

    previa = cliente.get(f"/api/envios/especificacao?tipo_servico=Ensaio de tração&lote_ids={lote.id},{ark.id}").json()
    assert previa["tipos_pecas"] == ["ARK", "PIN"] and [s["tipo"] for s in previa["especificacao"]] == ["ARK", "PIN"]
    assert previa["especificacao"][1]["charpy"] == []  # só tração foi pedida
    opcoes = cliente.get("/api/envios/opcoes").json()
    assert opcoes["numero_previsto"] == f"EP-{ANO}-001" and len(opcoes["tipos"]) == 7
    assert {p["razao_social"] for p in opcoes["prestadores"]} == {"LAB EXEMPLO ENSAIOS", "REVESTIDORA EXEMPLO"}


def test_fotos_entram_saem_com_motivo_e_aparecem_no_pdf(cliente, admin, db, pasta_arquivos):
    lote = _base(db)
    envio_id = cliente.post("/api/envios", json=_corpo([lote.id]), headers=_h(admin)).json()["id"]
    fotos = [("arquivos", ("cp1.png", _png(), "image/png")), ("arquivos", ("cp2.png", _png(), "image/png"))]
    r = cliente.post(f"/api/envios/{envio_id}/fotos", files=fotos, headers=_h(admin))
    assert r.status_code == 201 and r.json()["adicionadas"] == 2
    r = cliente.post(f"/api/envios/{envio_id}/fotos", files=[("arquivos", ("x.gif", b"GIF89a", "image/gif"))], headers=_h(admin))
    assert r.status_code == 422
    fotos = cliente.get(f"/api/envios/{envio_id}").json()["fotos"]
    assert [f["nome"] for f in fotos] == ["cp1.png", "cp2.png"]
    assert db.get(EnvioPrestadorFoto, fotos[0]["id"]).arquivo.startswith(f"envios_prestador/{envio_id}/fotos/")
    assert cliente.get(f"/api/envios/fotos/{fotos[0]['id']}/arquivo").status_code == 200

    pdf = cliente.get(f"/api/envios/{envio_id}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    with pymupdf.open(stream=pdf.content, filetype="pdf") as documento:
        assert len(documento[0].get_images()) >= 2

    r = cliente.post(f"/api/envios/fotos/{fotos[0]['id']}/remover", json={"motivo": ""}, headers=_h(admin))
    assert r.status_code == 422
    r = cliente.post(f"/api/envios/fotos/{fotos[0]['id']}/remover", json={"motivo": "Foto tremida"}, headers=_h(admin))
    assert r.status_code == 200
    assert [f["nome"] for f in cliente.get(f"/api/envios/{envio_id}").json()["fotos"]] == ["cp2.png"]
    assert cliente.get(f"/api/envios/fotos/{fotos[0]['id']}/arquivo").status_code == 404
    removida = db.get(EnvioPrestadorFoto, fotos[0]["id"])
    db.refresh(removida)
    assert removida.removido_motivo == "Foto tremida" and (pasta_arquivos / removida.arquivo).is_file()  # o arquivo fica


def test_pdf_do_envio_nunca_cita_o_cliente(cliente, admin, db):
    lote = _base(db)
    parametros.gravar(db, "cliente_nome", "CLIENTE EXEMPLO", "admin")
    parametros.gravar(db, "cliente_nome_curto", "EXEMPLO", "admin")
    parametros.gravar(db, "especificacao_codigo", "ESP-0001 rev.1", "admin")
    db.commit()
    envio_id = cliente.post("/api/envios", json=_corpo([lote.id]), headers=_h(admin)).json()["id"]
    r = cliente.get(f"/api/envios/{envio_id}/pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    with pymupdf.open(stream=r.content, filetype="pdf") as documento:
        texto = "\n".join(p.get_text() for p in documento)
    for esperado in ("SOLICITAÇÃO DE ENVIO A PRESTADOR EXTERNO", f"EP-{ANO}-001", "LAB EXEMPLO ENSAIOS", "Norma: ESP-0001 rev.1",
                     "CP Tração", "CP Impacto Charpy", "517–655 MPa", "ASTM A370", "ASTM E23", "Recebido pelo prestador",
                     "AçoKorte Indústria Metalúrgica e Comércio", "Natureza do envio"):  # fmt: skip
        assert esperado in texto, esperado
    assert "CLIENTE" not in texto and "EXEMPLO LTDA" not in texto
    assert db.scalar(select(Auditoria).where(Auditoria.acao == "GERAR_PDF")) is not None


def _modelo_docx(caminho):
    """Modelo mínimo de requisição de ensaio: só as células marcadas "Preencher" podem mudar."""
    doc = docx.Document()
    t0 = doc.add_table(rows=1, cols=4)
    for celula, texto in zip(t0.rows[0].cells, ["DATA:", "Preencher", "EMPRESA:", "Texto fixo da empresa"], strict=True):
        celula.text = texto
    t1 = doc.add_table(rows=6, cols=6)
    cabecalho = ["ITEM", "IDENTIFICAÇÃO DA AMOSTRA\n(como identificar)", "MATERIAL", "ENSAIO(S) / ANÁLISE(S)",
                 "NORMA DE ENSAIO\n(Ex: ASTM)", "O.S."]  # fmt: skip
    for celula, texto in zip(t1.rows[0].cells, cabecalho, strict=True):
        celula.text = texto
    for celula, texto in zip(t1.rows[1].cells, ["1", "Preencher", "Material fixo", "Ensaio fixo", "Preencher", ""], strict=True):
        celula.text = texto
    t1.rows[2].cells[1].paragraphs[0].add_run().add_picture(io.BytesIO(_png()))  # linha com imagem: não é "vazia"
    t2 = doc.add_table(rows=2, cols=1)
    t2.rows[0].cells[0].text = "INFORMAÇÕES ADICIONAIS:"
    t2.rows[1].cells[0].text = "Preencher"
    doc.add_paragraph("Texto do rodapé que não muda.")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(caminho))


def test_modelo_do_laboratorio_preenche_so_as_celulas_marcadas(cliente, admin, db, pasta_arquivos):
    lote = _base(db)
    ark = lote_exemplo(db, numero="26-4-900002", op="900002", tipo="ARK", qtd=10)
    _modelo_docx(pasta_arquivos / "recursos" / "modelos" / "modelo_teste.docx")
    corpo = _corpo([lote.id, ark.id])
    corpo["itens"][1].update(qt_cp_tracao=0, qt_cp_impacto=1)
    envio_id = cliente.post("/api/envios", json=corpo, headers=_h(admin)).json()["id"]
    # Sem o parâmetro do laboratório, não há botão nem documento
    assert cliente.get(f"/api/envios/{envio_id}").json()["modelo_ensaio"] is False
    assert cliente.get(f"/api/envios/{envio_id}/modelo-ensaio").status_code == 409
    parametros.gravar(db, "modelo_ensaio_prestador", "lab exemplo", "admin")
    parametros.gravar(db, "modelo_ensaio_arquivo", "modelo_teste.docx", "admin")
    parametros.gravar(db, "especificacao_codigo", "ESP-0001 rev.1", "admin")
    db.commit()
    assert cliente.get(f"/api/envios/{envio_id}").json()["modelo_ensaio"] is True

    r = cliente.get(f"/api/envios/{envio_id}/modelo-ensaio")
    assert r.status_code == 200 and r.content.startswith(b"PK") and "attachment" in r.headers["content-disposition"]
    gerado = docx.Document(io.BytesIO(r.content))
    t0, t1, t2 = gerado.tables
    assert [c.text for c in t0.rows[0].cells] == ["DATA:", HOJE.strftime("%d/%m/%Y"), "EMPRESA:", "Texto fixo da empresa"]
    # Uma linha por material + ensaio: SC 4330 tração, SC 4330 Charpy, H11 Charpy (cada uma ocupa uma linha vazia)
    assert len(t1.rows) == 6
    linhas = [[c.text for c in row.cells] for row in t1.rows[1:4]]
    assert [linha[0] for linha in linhas] == ["1", "2", "3"]
    assert all(linha[2] == "Material fixo" and linha[3] == "Ensaio fixo" for linha in linhas)  # texto fixo não muda
    assert "OP 900001 - 2 CPs" in linhas[0][1] and "Total: 2 CPs" in linhas[0][1] and "Ensaio de tração" in linhas[0][1]
    assert "OP 900001 - 3 CPs" in linhas[1][1] and "Ensaio de impacto Charpy" in linhas[1][1]
    assert "OP 900002 - 1 CP\n" in linhas[2][1] and "H11 Modified" in linhas[2][1]
    assert linhas[0][4] == "ASTM A370\nESP-0001 rev.1" and linhas[1][4] == "ASTM E23\nESP-0001 rev.1"
    assert t1.rows[4]._tr.xpath(".//w:drawing")  # a linha da imagem continua lá
    assert [c.text for c in t1.rows[5].cells] == [""] * 6
    assert "Nº interno: " + f"EP-{ANO}-001" in t2.rows[1].cells[0].text and "CPs usinados" in t2.rows[1].cells[0].text
    assert gerado.paragraphs[-1].text == "Texto do rodapé que não muda."
    marcadores = [c.text for t in gerado.tables for row in t.rows for c in row.cells if c.text.strip().lower() == "preencher"]
    assert marcadores == []  # nenhum marcador ficou para trás
    assert db.scalar(select(Auditoria).where(Auditoria.acao == "GERAR_DOCX")) is not None

    # Outro prestador: o modelo não vale
    corpo = _corpo([lote.id], prestador="OUTRO LABORATORIO")
    outro = cliente.post("/api/envios", json=corpo, headers=_h(admin)).json()["id"]
    assert cliente.get(f"/api/envios/{outro}/modelo-ensaio").status_code == 409


def test_envio_antigo_sem_data_nao_entra_no_alerta(db):
    lote = lote_exemplo(db)
    db.add(EnvioPrestador(numero="EP-2025-001", status="enviado", data_envio=None))
    db.add(EnvioPrestador(numero="EP-2025-002", status="retornado", data_envio=date(2025, 1, 2)))
    db.commit()
    assert envios_sem_retorno(db) == [] and lote.id
