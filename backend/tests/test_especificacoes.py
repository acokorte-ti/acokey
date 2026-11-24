"""Especificações por tipo e cotas por desenho. Valores fictícios (não são os da especificação do cliente)."""
from decimal import Decimal

from sqlalchemy import select

from app.models import Auditoria, EspecificacaoCota, EspecificacaoTipo


def _salvar_tipo(cliente, csrf, tipo, **campos):
    return cliente.put(f"/api/especificacoes/tipos/{tipo}", json=campos, headers={"X-CSRF-Token": csrf})


def _salvar_cotas(cliente, csrf, coditem, cotas):
    return cliente.put("/api/especificacoes/cotas", json={"coditem": coditem, "cotas": cotas}, headers={"X-CSRF-Token": csrf})


def test_ver_sem_nada_cadastrado_nao_inventa_valor(cliente, admin):
    r = cliente.get("/api/especificacoes")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert [t["tipo"] for t in corpo["tipos"]] == ["PIN", "BOX", "ARK"]
    assert all(t["cadastrada"] is False and t["dureza_min"] == "" and t["ch_temp"] == "" for t in corpo["tipos"])
    assert corpo["desenhos"] == [] and corpo["itens"] == [] and corpo["pode_editar"] is True


def test_salvar_tipo_guarda_numeros_e_deixa_vazio_o_que_veio_vazio(cliente, admin, db):
    r = _salvar_tipo(cliente, admin, "pin", dureza_min="30", dureza_max="39,5", tr_le_min="", ch_temp="-20", ch_dim_cp="10 x 10 mm",
                     ch_med_min="27.25")  # fmt: skip
    assert r.status_code == 200, r.text
    assert r.json()["tipo"]["dureza_max"] == "39.5" and r.json()["tipo"]["tr_le_min"] == ""
    spec = db.get(EspecificacaoTipo, "PIN")
    assert spec.dureza_min == Decimal("30") and spec.dureza_max == Decimal("39.5") and spec.tr_le_min is None
    assert spec.ch_temp == "-20" and spec.ch_dim_cp == "10 x 10 mm" and spec.ch_med_min == Decimal("27.25")
    auditoria = db.scalars(select(Auditoria).where(Auditoria.entidade == "especificacao_tipo")).all()
    assert len(auditoria) == 1 and auditoria[0].acao == "CRIAR" and auditoria[0].entidade_id == "PIN"

    # Mesmos valores escritos de outro jeito: não muda nada, não audita de novo
    r = _salvar_tipo(cliente, admin, "PIN", dureza_min="30,00", dureza_max="39.50", ch_temp="-20", ch_dim_cp="10 x 10 mm",
                     ch_med_min="27,25")  # fmt: skip
    assert r.status_code == 200
    db.expire_all()
    assert len(db.scalars(select(Auditoria).where(Auditoria.entidade == "especificacao_tipo")).all()) == 1

    # Apagar um campo deixa vazio (None), nunca um valor "padrão"
    r = _salvar_tipo(cliente, admin, "PIN", dureza_min="", dureza_max="39,5")
    assert r.status_code == 200
    db.expire_all()
    assert db.get(EspecificacaoTipo, "PIN").dureza_min is None
    alteracao = db.scalars(select(Auditoria).where(Auditoria.acao == "ALTERAR", Auditoria.entidade == "especificacao_tipo")).one()
    assert alteracao.detalhes["dureza_min"] == ["30.00", None]


def test_salvar_tipo_valida_numeros(cliente, admin, db):
    for campos, trecho in [
        ({"dureza_min": "trinta"}, "não é um número"),
        ({"dureza_min": "1e3"}, "não é um número"),
        ({"tr_al_min": "12,345"}, "2 casas decimais"),
        ({"dureza_min": "40", "dureza_max": "30"}, "maior que o máximo"),
    ]:
        r = _salvar_tipo(cliente, admin, "BOX", **campos)
        assert r.status_code == 422 and trecho in r.json()["detail"], (campos, r.text)
    assert db.get(EspecificacaoTipo, "BOX") is None
    assert _salvar_tipo(cliente, admin, "XYZ", dureza_min="30").status_code == 404


def test_cotas_substituem_a_lista_e_o_historico_fica_na_auditoria(cliente, admin, db):
    r = _salvar_cotas(cliente, admin, " 90009 ", [
        {"descricao": "Comprimento", "nominal": "100,00", "tol_min": "-0,05", "tol_max": "+0,05"},
        {"descricao": "", "nominal": "", "tol_min": "", "tol_max": ""},  # linha em branco: ignorada
        {"descricao": "Largura", "nominal": "20", "tol_min": "-0,1", "tol_max": "+0,1"},
    ])  # fmt: skip
    assert r.status_code == 200, r.text
    assert [c["descricao"] for c in r.json()["cotas"]] == ["Comprimento", "Largura"] and r.json()["coditem"] == "90009"
    assert cliente.get("/api/especificacoes/cotas/90009").json()["cotas"][0]["nominal"] == "100,00"  # texto, como digitado
    assert cliente.get("/api/especificacoes").json()["itens"] == [{"coditem": "90009", "n_cotas": 2, "descricao": ""}]

    r = _salvar_cotas(cliente, admin, "90009", [{"descricao": "Comprimento", "nominal": "100,10", "tol_min": "-0,05", "tol_max": "+0,05"}])
    assert r.status_code == 200
    db.expire_all()
    assert [c.nominal for c in db.scalars(select(EspecificacaoCota).where(EspecificacaoCota.coditem == "90009"))] == ["100,10"]
    historico = db.scalars(select(Auditoria).where(Auditoria.entidade == "especificacao_cotas").order_by(Auditoria.id)).all()
    assert len(historico) == 2 and len(historico[1].detalhes["antes"]) == 2 and historico[1].detalhes["antes"][1]["descricao"] == "Largura"

    # Lista vazia: o item fica sem cotas, mas a lista anterior continua na auditoria
    r = _salvar_cotas(cliente, admin, "90009", [])
    assert r.status_code == 200 and "sem cotas" in r.json()["mensagem"]
    db.expire_all()
    ultima = db.scalars(select(Auditoria).where(Auditoria.entidade == "especificacao_cotas")).all()[-1]
    assert ultima.detalhes["antes"][0]["nominal"] == "100,10" and ultima.detalhes["depois"] == []
    assert cliente.get("/api/especificacoes").json()["itens"] == []


def test_cotas_validam_entrada(cliente, admin):
    assert _salvar_cotas(cliente, admin, "  ", []).status_code == 422
    r = _salvar_cotas(cliente, admin, "90009", [{"descricao": "", "nominal": "100", "tol_min": "", "tol_max": ""}])
    assert r.status_code == 422 and "linha 1" in r.json()["detail"]


def test_desenhos_da_pasta_aparecem_com_a_classificacao(cliente, admin, pasta_arquivos):
    pasta = pasta_arquivos / "recursos" / "desenhos"
    pasta.mkdir(parents=True)
    (pasta / "ORIGEM - 90001 CHAVETA PIN EXEMPLO.pdf").write_bytes(b"%PDF-1.4 x")
    (pasta / "ORIGEM - 90002 CHAVETA ARK EXEMPLO.pdf").write_bytes(b"%PDF-1.4 x")
    desenhos = cliente.get("/api/especificacoes").json()["desenhos"]
    assert [(d["coditem"], d["classificacao"], d["n_cotas"]) for d in desenhos] == [("90001", "PIN", 0), ("90002", "ARK", 0)]
    assert cliente.get("/api/especificacoes/cotas/90002").json()["desenho"]["classificacao"] == "ARK"


def test_permissoes_ver_qualidade_ou_cadastros_gravar_so_cadastros(como):
    pcp, csrf_pcp = como(modulos=["pcp"])
    assert pcp.get("/api/especificacoes").status_code == 403
    assert pcp.get("/api/especificacoes/cotas/90009").status_code == 403
    qualidade, csrf_q = como(modulos=["qualidade"])
    r = qualidade.get("/api/especificacoes")
    assert r.status_code == 200 and r.json()["pode_editar"] is False
    assert _salvar_tipo(qualidade, csrf_q, "PIN", dureza_min="30").status_code == 403
    assert _salvar_cotas(qualidade, csrf_q, "90009", []).status_code == 403
    cadastros, csrf_c = como(modulos=["cadastros"])
    assert _salvar_tipo(cadastros, csrf_c, "PIN", dureza_min="30").status_code == 200
    assert _salvar_cotas(cadastros, csrf_c, "90009", [{"descricao": "Comprimento"}]).status_code == 200
    assert cadastros.put("/api/especificacoes/tipos/PIN", json={"dureza_min": "31"}).status_code == 403  # sem CSRF
