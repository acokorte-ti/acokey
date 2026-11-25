from datetime import datetime

from conftest import SENHA_ADMIN_NOVA, admin_pronto, entrar

from app.models import Anexo, Lote, NaoConformidade, Registro


def _criar_usuario(cliente, csrf, **extra) -> dict:
    corpo = {"login": "maria.silva", "nome": "Maria Silva", "cargo": "Inspetora", "senha": "Provisoria-2026"} | extra
    r = cliente.post("/api/usuarios", json=corpo, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201, r.text
    return r.json()


def _como(cliente_novo, login: str, provisoria: str = "Provisoria-2026") -> str:
    csrf = entrar(cliente_novo, login, provisoria)
    r = cliente_novo.post("/api/auth/trocar-senha", json={"senha_atual": provisoria, "senha_nova": "Minha-Senha-Nova-9"},
                          headers={"X-CSRF-Token": csrf})  # fmt: skip
    assert r.status_code == 200, r.text
    return csrf


def test_saude(cliente):
    assert cliente.get("/api/saude").json() == {"status": "ok"}


def test_sem_login_nao_entra(cliente):
    assert cliente.get("/api/lotes").status_code == 401


def test_senha_errada_bloqueia_depois_de_cinco_tentativas(cliente):
    for _ in range(5):
        assert cliente.post("/api/auth/login", json={"login": "admin", "senha": "errada-123"}).status_code == 401
    # Mesmo com a senha certa, fica bloqueado
    assert cliente.post("/api/auth/login", json={"login": "admin", "senha": "Senha-Inicial-2026"}).status_code == 401


def test_administrador_inicial_precisa_trocar_a_senha(cliente):
    entrar(cliente, "admin", "Senha-Inicial-2026")
    r = cliente.get("/api/lotes")
    assert r.status_code == 403 and r.json()["detail"] == "TROCAR_SENHA"


def test_senha_e_livre_na_provisoria_e_na_escolhida_pela_pessoa(cliente):
    """Sem regra de formato: curta, só números ou igual ao login. Só não pode ficar em branco nem repetir a atual."""
    from fastapi.testclient import TestClient

    from app.main import app

    csrf = admin_pronto(cliente)
    maria = _criar_usuario(cliente, csrf, senha="1")
    with TestClient(app) as sessao_maria:
        csrf_maria = entrar(sessao_maria, "maria.silva", "1")
        troca = {"senha_atual": "1", "senha_nova": "1"}
        r = sessao_maria.post("/api/auth/trocar-senha", json=troca, headers={"X-CSRF-Token": csrf_maria})
        assert r.status_code == 422 and "diferente da atual" in r.json()["detail"]
        troca["senha_nova"] = "maria.silva"
        r = sessao_maria.post("/api/auth/trocar-senha", json=troca, headers={"X-CSRF-Token": csrf_maria})
        assert r.status_code == 200, r.text
        assert r.json()["usuario"]["trocar_senha"] is False

    r = cliente.post(f"/api/usuarios/{maria['id']}/senha", json={"senha": "123"}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    with TestClient(app) as sessao_maria:
        entrar(sessao_maria, "maria.silva", "123")

    r = cliente.post(f"/api/usuarios/{maria['id']}/senha", json={"senha": ""}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 422


def test_gravacao_sem_token_csrf_e_recusada(cliente):
    admin_pronto(cliente)
    r = cliente.post("/api/usuarios", json={"login": "x.y", "nome": "Xy", "senha": "Provisoria-2026"})
    assert r.status_code == 403
    r = cliente.post("/api/usuarios", json={"login": "x.y", "nome": "Xy", "senha": "Provisoria-2026"},
                     headers={"X-CSRF-Token": "token-errado"})  # fmt: skip
    assert r.status_code == 403


def test_permissoes_por_modulo(cliente):
    from fastapi.testclient import TestClient

    from app.main import app

    csrf = admin_pronto(cliente)
    r = cliente.post("/api/usuarios", json={"login": "x.y", "nome": "Xy", "senha": "Provisoria-2026", "modulos": ["financeiro"]},
                     headers={"X-CSRF-Token": csrf})  # fmt: skip
    assert r.status_code == 422
    _criar_usuario(cliente, csrf, modulos=["pcp"])
    _criar_usuario(cliente, csrf, login="joao.qual", nome="João", modulos=["qualidade"])

    with TestClient(app) as maria:
        _como(maria, "maria.silva")
        assert maria.get("/api/lotes").status_code == 200
        assert maria.get("/api/usuarios").status_code == 403  # só administrador
        assert maria.get("/api/auditoria").status_code == 403  # precisa do módulo Qualidade
    with TestClient(app) as joao:
        _como(joao, "joao.qual")
        assert joao.get("/api/auditoria").status_code == 200
        assert joao.get("/api/usuarios").status_code == 403


def test_regras_de_alteracao_de_usuario(cliente):
    csrf = admin_pronto(cliente)
    h = {"X-CSRF-Token": csrf}
    eu = next(u for u in cliente.get("/api/usuarios").json() if u["login"] == "admin")
    assert cliente.patch(f"/api/usuarios/{eu['id']}", json={"ativo": False}, headers=h).status_code == 422
    assert cliente.patch(f"/api/usuarios/{eu['id']}", json={"admin": False}, headers=h).status_code == 422  # único admin

    aprovadora = _criar_usuario(cliente, csrf, pode_aprovar=True, modulos=["qualidade"])
    r = cliente.patch(f"/api/usuarios/{aprovadora['id']}", json={"pode_aprovar": False}, headers=h)
    assert r.status_code == 422  # ficaria sem ninguém para aprovar
    outro = _criar_usuario(cliente, csrf, login="outro.aprov", nome="Outro", pode_aprovar=True)
    r = cliente.patch(f"/api/usuarios/{aprovadora['id']}", json={"pode_aprovar": False}, headers=h)
    assert r.status_code == 200 and r.json()["pode_aprovar"] is False
    assert outro["pode_aprovar"] is True

    acoes = [a["acao"] for a in cliente.get("/api/auditoria").json()["itens"]]
    assert "ALTERAR" in acoes and "CRIAR" in acoes


def test_mudar_permissao_derruba_a_sessao_da_pessoa(cliente):
    from fastapi.testclient import TestClient

    from app.main import app

    csrf = admin_pronto(cliente)
    maria = _criar_usuario(cliente, csrf, modulos=["qualidade"])
    with TestClient(app) as sessao_maria:
        _como(sessao_maria, "maria.silva")
        assert sessao_maria.get("/api/auditoria").status_code == 200
        cliente.patch(f"/api/usuarios/{maria['id']}", json={"modulos": []}, headers={"X-CSRF-Token": csrf})
        assert sessao_maria.get("/api/auditoria").status_code == 401


def _lote(db, numero="26-4-900001", tipo="PIN", **extra) -> Lote:
    lote = Lote(numero=numero, op="900001", tipo=tipo, qtd=72, etapa_desde=datetime(2026, 11, 20, 8, 0), **extra)
    db.add(lote)
    db.flush()
    return lote


def test_lista_e_detalhe_dos_lotes(cliente, db):
    pin = _lote(db)
    ark = _lote(db, numero="26-4-900002", tipo="ARK")
    for etapa in ("receb_mp", "trat_termico"):
        db.add(Registro(lote_id=pin.id, etapa=etapa, status="aprovado", responsavel="Inspetor", quando=datetime(2026, 11, 20, 9)))
        db.add(Registro(lote_id=ark.id, etapa=etapa, status="aprovado", responsavel="Inspetor"))
    reprovado = Registro(lote_id=pin.id, etapa="dureza", status="reprovado", responsavel="Inspetor")
    db.add(reprovado)
    db.flush()
    db.add(NaoConformidade(numero="NC-2026-001", lote_id=pin.id, etapa="dureza", registro_id=reprovado.id, status="aberta"))
    db.commit()

    admin_pronto(cliente)
    itens = {i["numero"]: i for i in cliente.get("/api/lotes").json()["itens"]}
    assert itens["26-4-900001"]["etapa_atual"]["chave"] == "dureza"
    assert itens["26-4-900001"]["progresso"] == {"aprovadas": 2, "total": 11}
    assert itens["26-4-900001"]["nc_aberta"] is True
    assert itens["26-4-900002"]["etapa_atual"] == {"indice": 3, "chave": "lab_ext", "curto": "Charpy", "setor": "Laboratório externo"}
    assert itens["26-4-900002"]["nc_aberta"] is False

    detalhe = cliente.get(f"/api/lotes/{pin.id}").json()
    situacoes = {e["chave"]: e["situacao"] for e in detalhe["etapas"]}
    assert situacoes["receb_mp"] == "aprovada" and situacoes["dureza"] == "reprovada" and situacoes["lab_ext"] == "futura"
    assert detalhe["ncs"][0]["numero"] == "NC-2026-001"
    detalhe_ark = cliente.get(f"/api/lotes/{ark.id}").json()
    lab = next(e for e in detalhe_ark["etapas"] if e["chave"] == "lab_ext")
    assert [s["sub"] for s in lab["subs"]] == ["charpy"] and lab["situacao"] == "atual"
    assert next(e for e in detalhe_ark["etapas"] if e["chave"] == "dureza")["situacao"] == "nao_aplicavel"
    assert cliente.get("/api/lotes/9999").status_code == 404


def test_registro_anulado_nao_conta(cliente, db):
    lote = _lote(db)
    db.add(Registro(lote_id=lote.id, etapa="receb_mp", status="aprovado"))
    db.add(Registro(lote_id=lote.id, etapa="trat_termico", status="aprovado", anulado=True, anulado_motivo="digitação"))
    db.commit()
    admin_pronto(cliente)
    item = cliente.get("/api/lotes").json()["itens"][0]
    assert item["etapa_atual"]["chave"] == "trat_termico"


def test_download_de_anexo_so_dentro_da_pasta_de_arquivos(cliente, db, pasta_arquivos):
    lote = _lote(db)
    (pasta_arquivos / "lotes/1/anexos").mkdir(parents=True)
    (pasta_arquivos / "lotes/1/anexos/certificado.pdf").write_bytes(b"%PDF-1.4 teste")
    (pasta_arquivos.parent / "segredo.txt").write_text("não pode sair")
    bom = Anexo(lote_id=lote.id, etapa="receb_mp", nome="Certificado MP.pdf", arquivo="lotes/1/anexos/certificado.pdf")
    fuga = Anexo(lote_id=lote.id, etapa="receb_mp", nome="x.txt", arquivo="../segredo.txt")
    sumido = Anexo(lote_id=lote.id, etapa="receb_mp", nome="y.pdf", arquivo="lotes/1/anexos/nao-existe.pdf")
    db.add_all([bom, fuga, sumido])
    db.commit()

    assert cliente.get(f"/api/anexos/{bom.id}/arquivo").status_code == 401
    admin_pronto(cliente)
    r = cliente.get(f"/api/anexos/{bom.id}/arquivo")
    assert r.status_code == 200 and r.content == b"%PDF-1.4 teste"
    assert r.headers["content-type"] == "application/pdf" and r.headers["content-disposition"].startswith("inline")
    assert cliente.get(f"/api/anexos/{fuga.id}/arquivo").status_code == 404
    assert cliente.get(f"/api/anexos/{sumido.id}/arquivo").status_code == 404


def test_logout_encerra_a_sessao(cliente):
    csrf = entrar(cliente, "admin", "Senha-Inicial-2026")
    cliente.post("/api/auth/trocar-senha", json={"senha_atual": "Senha-Inicial-2026", "senha_nova": SENHA_ADMIN_NOVA},
                 headers={"X-CSRF-Token": csrf})  # fmt: skip
    assert cliente.get("/api/auth/eu").status_code == 200
    cliente.post("/api/auth/logout")
    assert cliente.get("/api/auth/eu").status_code == 401
