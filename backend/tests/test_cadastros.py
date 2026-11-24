"""Cadastros: equipamentos, prestadores, fornecedores de MP, ordens de produção, parâmetros e assinaturas. Dados fictícios."""
import io
import json
from datetime import date, timedelta

import openpyxl
import pytest
from conftest import lote_exemplo
from PIL import Image
from sqlalchemy import select

from app.config import agora_local
from app.models import Auditoria, Equipamento, OrdemProducao, Parametro, Usuario
from app.ordens_producao import COLUNAS


@pytest.fixture
def cadastros(como):
    return como(modulos=["cadastros"])


def _h(csrf: str) -> dict:
    return {"X-CSRF-Token": csrf}


# ---------------------------------------------------------------- equipamentos


def test_equipamentos_cadastro_vencimento_e_inativar(como, cadastros, db):
    cli, csrf = cadastros
    hoje = agora_local().date()
    corpo = {"codigo": "DUR-900001", "descricao": "Durômetro de bancada", "setor": "Qualidade", "marca": "EXEMPLO",
             "data_calibracao": str(hoje - timedelta(days=400)), "validade_calibracao": str(hoje - timedelta(days=1)),
             "certificado": "C-001", "empresa_calibracao": "CALIBRA EXEMPLO"}  # fmt: skip
    r = cli.post("/api/equipamentos", json=corpo, headers=_h(csrf))
    assert r.status_code == 201, r.text
    equip = r.json()
    assert equip["vencido"] is True and equip["ativo"] is True
    assert cli.post("/api/equipamentos", json={**corpo, "codigo": "dur-900001"}, headers=_h(csrf)).status_code == 409
    assert cli.post("/api/equipamentos", json={**corpo, "codigo": "X", "descricao": " "}, headers=_h(csrf)).status_code == 422
    invertida = {**corpo, "codigo": "FOR-1", "data_calibracao": str(hoje), "validade_calibracao": str(hoje - timedelta(days=1))}
    assert cli.post("/api/equipamentos", json=invertida, headers=_h(csrf)).status_code == 422

    r = cli.put(f"/api/equipamentos/{equip['id']}", json={**corpo, "validade_calibracao": str(hoje + timedelta(days=10))},
                headers=_h(csrf))  # fmt: skip
    assert r.status_code == 200 and r.json()["vencido"] is False and r.json()["vence_logo"] is True
    assert db.scalar(select(Auditoria).where(Auditoria.entidade == "equipamento", Auditoria.acao == "ALTERAR"))

    # Qualidade consulta, mas não grava; PCP não consulta, mas lê a lista curta dos relatórios
    qualidade, csrf_q = como(modulos=["qualidade"])
    pcp, _ = como(modulos=["pcp"])
    assert qualidade.get("/api/equipamentos").status_code == 200
    assert qualidade.post("/api/equipamentos", json={**corpo, "codigo": "Z"}, headers=_h(csrf_q)).status_code == 403
    assert qualidade.post(f"/api/equipamentos/{equip['id']}/inativar", headers=_h(csrf_q)).status_code == 403
    assert pcp.get("/api/equipamentos").status_code == 403
    assert [e["codigo"] for e in pcp.get("/api/equipamentos/opcoes").json()] == ["DUR-900001"]

    assert cli.post(f"/api/equipamentos/{equip['id']}/inativar", headers=_h(csrf)).json()["ativo"] is False
    assert pcp.get("/api/equipamentos/opcoes").json() == []
    assert len(cli.get("/api/equipamentos").json()) == 1  # inativo continua na lista do cadastro
    assert cli.post(f"/api/equipamentos/{equip['id']}/reativar", headers=_h(csrf)).json()["ativo"] is True
    assert db.get(Equipamento, equip["id"]).ativo is True


# ---------------------------------------------------------------- prestadores e fornecedores


def test_prestadores_tipos_fechados_e_opcoes_por_etapa(como, cadastros, db):
    cli, csrf = cadastros
    base = {"razao_social": "Laboratório Exemplo", "contato": "", "observacoes": ""}
    assert cli.post("/api/prestadores", json={**base, "codigo": "LAB1", "tipo_servico": "Pintura"}, headers=_h(csrf)).status_code == 422
    for codigo, tipo in [("lab1", "Lab mecânico (tração/Charpy)"), ("fosf", "Revestimento fosfato"),
                         ("oxid", "Revestimento oxidação negra"), ("ndt", "NDT - líquido penetrante")]:  # fmt: skip
        r = cli.post("/api/prestadores", json={**base, "codigo": codigo, "tipo_servico": tipo}, headers=_h(csrf))
        assert r.status_code == 201, r.text
    assert r.json()["codigo"] == "NDT"  # código sempre em maiúsculas

    qualidade, _ = como(modulos=["qualidade"])
    assert qualidade.get("/api/prestadores").status_code == 403
    assert [p["codigo"] for p in qualidade.get("/api/prestadores/opcoes?etapa=fosfato&tipo_lote=ARK").json()] == ["OXID"]
    assert [p["codigo"] for p in qualidade.get("/api/prestadores/opcoes?etapa=fosfato&tipo_lote=PIN").json()] == ["FOSF"]
    assert [p["codigo"] for p in qualidade.get("/api/prestadores/opcoes?etapa=lab_ext").json()] == ["LAB1"]
    assert qualidade.get("/api/prestadores/opcoes?etapa=dureza").json() == []
    assert len(qualidade.get("/api/prestadores/opcoes").json()) == 4
    assert "Outro" in qualidade.get("/api/cadastros/listas").json()["tipos_prestador"]

    # Tipo antigo fora da lista (veio da planilha) continua aceito enquanto não for mexido
    from app.models import Prestador

    antigo = Prestador(codigo="VELHO", razao_social="Antigo", tipo_servico="Ensaio especial")
    db.add(antigo)
    db.commit()
    corpo = {**base, "codigo": "VELHO", "tipo_servico": "Ensaio especial", "contato": "Fulano"}
    assert cli.put(f"/api/prestadores/{antigo.id}", json=corpo, headers=_h(csrf)).status_code == 200
    assert cli.put(f"/api/prestadores/{antigo.id}", json={**corpo, "tipo_servico": "Pintura"}, headers=_h(csrf)).status_code == 422


def test_fornecedores_mp(como, cadastros):
    cli, csrf = cadastros
    corpo = {"codigo": "acos", "razao_social": "Aços Exemplo S.A.", "materiais": "SC4330 (ASTM A958)", "contato": "", "observacoes": ""}
    r = cli.post("/api/fornecedores-mp", json=corpo, headers=_h(csrf))
    assert r.status_code == 201 and r.json()["codigo"] == "ACOS"
    assert cli.post("/api/fornecedores-mp", json=corpo, headers=_h(csrf)).status_code == 409
    fid = r.json()["id"]
    assert cli.put(f"/api/fornecedores-mp/{fid}", json={**corpo, "contato": "Fulano"}, headers=_h(csrf)).json()["contato"] == "Fulano"
    pcp, csrf_pcp = como(modulos=["pcp"])
    assert pcp.post("/api/fornecedores-mp", json={**corpo, "codigo": "B"}, headers=_h(csrf_pcp)).status_code == 403
    assert [f["codigo"] for f in pcp.get("/api/fornecedores-mp/opcoes").json()] == ["ACOS"]
    cli.post(f"/api/fornecedores-mp/{fid}/inativar", headers=_h(csrf))
    assert pcp.get("/api/fornecedores-mp/opcoes").json() == []


# ---------------------------------------------------------------- ordens de produção


def _planilha(linhas: list[list]) -> bytes:
    livro = openpyxl.Workbook()
    aba = livro.active
    aba.title = "Dados"
    aba.append([titulo for _, titulo in COLUNAS])
    for linha in linhas:
        aba.append(linha)
    saida = io.BytesIO()
    livro.save(saida)
    return saida.getvalue()


def _xlsx(conteudo: bytes, nome: str = "ops.xlsx"):
    return {"arquivo": (nome, conteudo, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}


def test_ordens_de_producao_edicao_e_exportacao(como, cadastros, db):
    cli, csrf = cadastros
    corpo = {"op": "900001", "cliente": "CLIENTE EXEMPLO", "coditem": "12345", "descricao": "Chaveta PIN", "tipo": "pin",
             "data_faturamento": "2026-11-20", "nf": "1", "piv": "PIV-1", "qt_lote": 72, "qt_faturada": None,
             "projeto": "PROJ", "po": "PO-1"}  # fmt: skip
    r = cli.post("/api/ordens-producao", json=corpo, headers=_h(csrf))
    assert r.status_code == 201 and r.json()["tipo"] == "PIN"
    oid = r.json()["id"]
    assert cli.post("/api/ordens-producao", json=corpo, headers=_h(csrf)).status_code == 409
    assert cli.post("/api/ordens-producao", json={**corpo, "op": "900002", "tipo": "XYZ"}, headers=_h(csrf)).status_code == 422

    lote_exemplo(db, op="900001")
    assert cli.get("/api/ordens-producao").json()[0]["lotes"] == 1
    r = cli.put(f"/api/ordens-producao/{oid}", json={**corpo, "op": "900003"}, headers=_h(csrf))
    assert r.status_code == 409  # já há lote com esta OP
    r = cli.put(f"/api/ordens-producao/{oid}", json={**corpo, "qt_lote": 80}, headers=_h(csrf))
    assert r.status_code == 200 and r.json()["qt_lote"] == 80

    qualidade, _ = como(modulos=["qualidade"])
    assert qualidade.get("/api/ordens-producao").status_code == 403
    assert qualidade.get("/api/ordens-producao/exportar").status_code == 403
    assert [o["op"] for o in qualidade.get("/api/ordens-producao/opcoes?tipo=PIN").json()] == ["900001"]

    r = cli.get("/api/ordens-producao/exportar")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    aba = openpyxl.load_workbook(io.BytesIO(r.content))["Dados"]
    assert [c.value for c in aba[1]] == [titulo for _, titulo in COLUNAS]
    linha = [c.value for c in aba[2]]
    assert linha[1] == "900001" and linha[4] == "PIN" and linha[5].date() == date(2026, 11, 20) and linha[8] == 80


def test_importacao_so_inclui_as_ops_novas_confirmadas(cadastros, como, db):
    cli, csrf = cadastros
    db.add_all([
        OrdemProducao(op="900001", cliente="CLIENTE EXEMPLO", coditem="111", tipo="PIN", qt_lote=72),
        OrdemProducao(op="900002", cliente="CLIENTE EXEMPLO", coditem="222", tipo="BOX", qt_lote=10),
    ])  # fmt: skip
    db.commit()
    planilha = _planilha([
        ["CLIENTE EXEMPLO", 900001, 111, None, "PIN", None, None, None, 72, None, None, None],  # igual
        ["CLIENTE EXEMPLO", 900003, "333", "Chaveta ARK", "ark", "20/11/2026", "", "PIV-3", "15", None, "P", "PO-3"],
        ["CLIENTE EXEMPLO", 900004, "444", "", "XYZ", "data ruim", "", "", 5, None, "", ""],
        ["OUTRO CLIENTE", 900001.0, 111, None, "PIN", None, None, None, 80, None, None, None],  # repetida: vale esta
    ])  # fmt: skip
    r = cli.post("/api/ordens-producao/importacao/comparar", files=_xlsx(planilha), headers=_h(csrf))
    assert r.status_code == 200, r.text
    resultado = r.json()
    assert [n["op"] for n in resultado["novas"]] == ["900003", "900004"]
    assert resultado["alteradas"] == [{"op": "900001", "diferencas": {"Cliente": ["CLIENTE EXEMPLO", "OUTRO CLIENTE"],
                                                                      "QT_Lote": ["72", "80"]}}]  # fmt: skip
    assert resultado["ausentes"] == ["900002"] and resultado["total_planilha"] == 3
    assert any("mais de uma vez" in a for a in resultado["avisos"])
    assert any("XYZ" in a for a in resultado["avisos"]) and any("data ruim" in a for a in resultado["avisos"])
    assert db.scalar(select(OrdemProducao).where(OrdemProducao.op == "900003")) is None  # comparar não grava

    r = cli.post("/api/ordens-producao/importacao/aplicar", files=_xlsx(planilha), data={"ops": json.dumps(["900003"])},
                 headers=_h(csrf))  # fmt: skip
    assert r.status_code == 200, r.text
    assert r.json()["incluidas"] == ["900003"]
    nova = db.scalar(select(OrdemProducao).where(OrdemProducao.op == "900003"))
    assert (nova.tipo, nova.data_faturamento, nova.qt_lote, nova.piv, nova.coditem) == ("ARK", date(2026, 11, 20), 15, "PIV-3", "333")
    alterada = db.scalar(select(OrdemProducao).where(OrdemProducao.op == "900001"))
    assert alterada.cliente == "CLIENTE EXEMPLO" and alterada.qt_lote == 72  # alterada nunca é sobrescrita
    assert db.scalar(select(OrdemProducao).where(OrdemProducao.op == "900004")) is None  # não confirmada
    assert db.scalar(select(OrdemProducao).where(OrdemProducao.op == "900002")) is not None  # ausente não sai
    auditoria = db.scalar(select(Auditoria).where(Auditoria.acao == "IMPORTAR"))
    assert auditoria.detalhes["incluidas"] == ["900003"]

    r = cli.post("/api/ordens-producao/importacao/aplicar", files=_xlsx(planilha), data={"ops": json.dumps(["900003"])},
                 headers=_h(csrf))  # fmt: skip
    assert r.status_code == 409

    sem_aba = openpyxl.Workbook()
    saida = io.BytesIO()
    sem_aba.save(saida)
    r = cli.post("/api/ordens-producao/importacao/comparar", files=_xlsx(saida.getvalue()), headers=_h(csrf))
    assert r.status_code == 422 and "Dados" in r.json()["detail"]
    assert cli.post("/api/ordens-producao/importacao/comparar", files=_xlsx(b"nao e planilha"), headers=_h(csrf)).status_code == 422
    assert cli.post("/api/ordens-producao/importacao/comparar", files=_xlsx(planilha, "ops.csv"), headers=_h(csrf)).status_code == 422
    qualidade, csrf_q = como(modulos=["qualidade"])
    assert qualidade.post("/api/ordens-producao/importacao/comparar", files=_xlsx(planilha), headers=_h(csrf_q)).status_code == 403


# ---------------------------------------------------------------- parâmetros


def test_parametros_so_administrador(cliente, admin, como, db):
    lista = cliente.get("/api/parametros").json()
    chaves = [p["chave"] for p in lista]
    assert chaves[:3] == ["empresa_razao_social", "empresa_endereco", "cliente_nome"]
    razao = next(p for p in lista if p["chave"] == "empresa_razao_social")
    assert razao["valor"] == "" and razao["em_uso"].startswith("AçoKorte") and razao["descricao"]

    r = cliente.put("/api/parametros/cliente_nome", json={"valor": " CLIENTE EXEMPLO "}, headers=_h(admin))
    assert r.status_code == 200 and r.json()["valor"] == "CLIENTE EXEMPLO" and r.json()["alterado_por"] == "admin"
    auditoria = db.scalar(select(Auditoria).where(Auditoria.entidade == "parametro"))
    assert auditoria.entidade_id == "cliente_nome" and auditoria.detalhes == {"valor": ["", "CLIENTE EXEMPLO"]}
    assert cliente.put("/api/parametros/laser_formato", json={"valor": "{ano}-{xpto}"}, headers=_h(admin)).status_code == 422
    assert cliente.put("/api/parametros/laser_formato", json={"valor": "{ano}T{tri}-{seq:03d}"}, headers=_h(admin)).status_code == 200
    assert cliente.put("/api/parametros/elementos_quimicos", json={"valor": "C,,Mn"}, headers=_h(admin)).status_code == 422
    assert cliente.put("/api/parametros/Chave Ruim", json={"valor": "x"}, headers=_h(admin)).status_code == 422
    assert cliente.put("/api/parametros/chave_nova", json={"valor": "x"}, headers=_h(admin)).status_code == 200
    assert any(p["chave"] == "chave_nova" and not p["conhecido"] for p in cliente.get("/api/parametros").json())
    assert db.get(Parametro, "chave_nova").valor == "x"

    qualidade, csrf = como(modulos=["qualidade", "cadastros"], pode_aprovar=True)
    assert qualidade.get("/api/parametros").status_code == 403
    assert qualidade.put("/api/parametros/cliente_nome", json={"valor": "x"}, headers=_h(csrf)).status_code == 403


# ---------------------------------------------------------------- assinatura digital


def _imagem(formato: str = "PNG") -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", (400, 120), (255, 255, 255)).save(saida, formato)
    return saida.getvalue()


def test_assinatura_digital(cliente, admin, como, db, pasta_arquivos):
    aprovador, csrf_apr = como(modulos=["qualidade"], pode_aprovar=True, login="aprovador")
    comum, csrf_comum = como(modulos=["qualidade"], login="comum")
    alvo = db.scalar(select(Usuario).where(Usuario.login == "aprovador"))
    url = f"/api/usuarios/{alvo.id}/assinatura"

    assert cliente.get(url).status_code == 404
    falsa = {"arquivo": ("assinatura.png", b"\x89PNG\r\n\x1a\nnao e imagem", "image/png")}
    assert cliente.post(url, files=falsa, headers=_h(admin)).status_code == 422
    assert cliente.post(url, files={"arquivo": ("a.pdf", b"%PDF-1.4", "application/pdf")}, headers=_h(admin)).status_code == 422
    r = cliente.post(url, files={"arquivo": ("assinatura.jpg", _imagem("JPEG"), "image/jpeg")}, headers=_h(admin))
    assert r.status_code == 200 and r.json()["tem_assinatura"] is True
    db.refresh(alvo)
    primeira = alvo.assinatura_arquivo
    assert primeira.startswith("assinaturas/") and (pasta_arquivos / primeira).is_file()

    assert cliente.get(url).status_code == 200  # administrador
    assert aprovador.get(url).headers["content-type"] == "image/jpeg"  # quem pode aprovar
    assert comum.get(url).status_code == 403
    assert comum.post(url, files={"arquivo": ("a.png", _imagem(), "image/png")}, headers=_h(csrf_comum)).status_code == 403
    assert aprovador.delete(url, headers=_h(csrf_apr)).status_code == 403

    r = cliente.post(url, files={"arquivo": ("nova.png", _imagem(), "image/png")}, headers=_h(admin))
    assert r.status_code == 200
    db.refresh(alvo)
    assert alvo.assinatura_arquivo != primeira and (pasta_arquivos / primeira).is_file()  # a anterior fica guardada
    r = cliente.delete(url, headers=_h(admin))
    assert r.status_code == 200 and r.json()["tem_assinatura"] is False
    db.refresh(alvo)
    assert alvo.assinatura_arquivo is None
    acoes = db.scalars(select(Auditoria.detalhes).where(Auditoria.entidade == "usuario", Auditoria.acao == "ALTERAR"))
    assert sum(1 for d in acoes if "assinatura" in d) == 3


def test_rotas_de_cadastro_recusam_quem_nao_tem_o_modulo(como, db):
    """Qualidade (sem Cadastros) não grava nenhum cadastro; ninguém sem ser administrador mexe em parâmetros."""
    qualidade, csrf = como(modulos=["qualidade", "pcp", "producao_tt", "producao_usinagem"], pode_aprovar=True)
    h = _h(csrf)
    equipamento = {"codigo": "E1", "descricao": "Forno"}
    prestador = {"codigo": "P1", "razao_social": "Exemplo", "tipo_servico": "Outro"}
    fornecedor = {"codigo": "F1", "razao_social": "Exemplo"}
    for metodo, url, corpo in [
        ("post", "/api/equipamentos", equipamento), ("put", "/api/equipamentos/1", equipamento),
        ("post", "/api/equipamentos/1/inativar", None), ("post", "/api/equipamentos/1/reativar", None),
        ("get", "/api/prestadores", None), ("post", "/api/prestadores", prestador), ("put", "/api/prestadores/1", prestador),
        ("post", "/api/prestadores/1/inativar", None), ("post", "/api/prestadores/1/reativar", None),
        ("get", "/api/fornecedores-mp", None), ("post", "/api/fornecedores-mp", fornecedor),
        ("put", "/api/fornecedores-mp/1", fornecedor), ("post", "/api/fornecedores-mp/1/inativar", None),
        ("post", "/api/fornecedores-mp/1/reativar", None),
        ("get", "/api/ordens-producao", None), ("post", "/api/ordens-producao", {"op": "900001"}),
        ("put", "/api/ordens-producao/1", {"op": "900001"}), ("get", "/api/ordens-producao/exportar", None),
        ("get", "/api/parametros", None), ("put", "/api/parametros/cliente_nome", {"valor": "x"}),
        ("delete", "/api/usuarios/1/assinatura", None),
    ]:  # fmt: skip
        argumentos = {"headers": h} if metodo == "get" or metodo == "delete" else {"headers": h, "json": corpo}
        r = getattr(qualidade, metodo)(url, **argumentos)
        assert r.status_code == 403, (metodo, url, r.text)
    planilha = _xlsx(_planilha([]))
    r = qualidade.post("/api/ordens-producao/importacao/aplicar", files=planilha, data={"ops": "[]"}, headers=h)
    assert r.status_code == 403
    r = qualidade.post("/api/usuarios/1/assinatura", files={"arquivo": ("a.png", _imagem(), "image/png")}, headers=h)
    assert r.status_code == 403
    assert qualidade.get("/api/equipamentos").status_code == 200  # Qualidade consulta os equipamentos
    sem_login = qualidade.__class__(qualidade.app)
    assert sem_login.get("/api/prestadores/opcoes").status_code == 401
