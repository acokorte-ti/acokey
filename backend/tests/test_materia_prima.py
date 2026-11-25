"""Matéria-prima: corridas, saldo, certificados, decisão, carimbo APROVADO e lotes da corrida. Só dados fictícios."""
import io

import pymupdf
import pytest
from conftest import lote_exemplo
from PIL import Image
from sqlalchemy import select

from app.carimbo import ErroCarimbo, carimbar_pdf
from app.models import Anexo, Auditoria, Evento, Lote, MateriaPrima, MateriaPrimaAnexo, OrdemProducao, Usuario

CORRIDA = {
    "nf_entrada": "123456", "corrida": "M999/26", "fornecedor": "ACOS EXEMPLO", "tipo_destino": "PIN",
    "data_recebimento": "2026-11-20", "qt_fund": 220, "qt_real": 200, "qt_ok": 180, "qt_rej": 12, "qt_retrab": 8,
    "qt_cp_tt": 4, "observacoes": "",
}  # fmt: skip


def _pdf(paginas: int = 2, texto: str = "Certificado de teste") -> bytes:
    doc = pymupdf.open()
    for i in range(paginas):
        doc.new_page().insert_text((72, 72), f"{texto} - pagina {i + 1}")
    return doc.tobytes()


def _png() -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", (400, 120), (255, 255, 255)).save(saida, "PNG")
    return saida.getvalue()


@pytest.fixture
def qualidade(como):
    return como(modulos=["qualidade"])


@pytest.fixture
def aprovador(como, cliente, admin, db):
    """Usuário da Qualidade que pode aprovar e já tem assinatura cadastrada (pelo administrador)."""
    outro, csrf = como(modulos=["qualidade"], pode_aprovar=True, login="aprovador", nome="Fulano Aprovador")
    usuario = db.scalar(select(Usuario).where(Usuario.login == "aprovador"))
    r = cliente.post(f"/api/usuarios/{usuario.id}/assinatura", files={"arquivo": ("assinatura.png", _png(), "image/png")},
                     headers={"X-CSRF-Token": admin})  # fmt: skip
    assert r.status_code == 200, r.text
    return outro, csrf


def _lancar(cliente, csrf, **mudancas) -> int:
    r = cliente.post("/api/materia-prima", json={**CORRIDA, **mudancas}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _anexar(cliente, csrf, mp_id, nome="Certificado M999.pdf", conteudo=None, tipo="application/pdf"):
    conteudo = _pdf() if conteudo is None else conteudo
    r = cliente.post(f"/api/materia-prima/{mp_id}/anexos", files=[("arquivos", (nome, conteudo, tipo))],
                     headers={"X-CSRF-Token": csrf})  # fmt: skip
    assert r.status_code == 201, r.text
    detalhe = cliente.get(f"/api/materia-prima/{mp_id}").json()
    return next(a["id"] for a in detalhe["anexos"] if a["nome"] == nome)


# ---------------------------------------------------------------- lançamento, saldo e permissões


def test_lanca_corrida_e_calcula_percentuais_e_saldo(qualidade, db):
    cli, csrf = qualidade
    mp_id = _lancar(cli, csrf)
    mp = db.get(MateriaPrima, mp_id)
    assert mp.responsavel == "Fulano de Tal" and mp.status == "pendente"  # quem lança é o usuário logado

    # Lote ligado pelo id, lote antigo ligado só pelo texto da corrida e lote cancelado (não conta)
    lote_exemplo(db, numero="26-4-900001", qtd=50, materia_prima_id=mp_id, corrida="M999/26")
    lote_exemplo(db, numero="26-4-900002", qtd=30, corrida="m999/26 ")
    from datetime import datetime

    lote_exemplo(db, numero="26-4-900003", qtd=99, materia_prima_id=mp_id, cancelado_em=datetime(2026, 11, 21))

    lista = cli.get("/api/materia-prima").json()
    item = next(i for i in lista["itens"] if i["id"] == mp_id)
    assert item["pct_refugo"] == 6.0 and item["pct_retrab"] == 4.0 and item["pct_aprov"] == 90.0
    assert item["rendimento"] == 81.8  # 180 / 220
    assert item["qt_disponivel"] == 176  # QT-OK menos os corpos de prova
    assert item["qt_consumida"] == 80 and item["qt_saldo"] == 96
    assert item["lotes_usando"] == 2 and item["tem_carimbado"] is False
    assert {"valor": "ACOS EXEMPLO", "rotulo": ""} in lista["fornecedores"]

    detalhe = cli.get(f"/api/materia-prima/{mp_id}").json()
    assert [lote["numero"] for lote in detalhe["lotes"]] == ["26-4-900002", "26-4-900001"]
    assert detalhe["lotes"][0]["etapa"] == "Receb. MP" and detalhe["corrida"]["qt_saldo"] == 96
    assert detalhe["tenho_assinatura"] is False


def test_validacoes_do_lancamento(qualidade):
    cli, csrf = qualidade
    h = {"X-CSRF-Token": csrf}
    assert cli.post("/api/materia-prima", json={**CORRIDA, "corrida": "  "}, headers=h).status_code == 422
    assert cli.post("/api/materia-prima", json={**CORRIDA, "tipo_destino": "XYZ"}, headers=h).status_code == 422
    assert cli.post("/api/materia-prima", json={**CORRIDA, "nf_entrada": ""}, headers=h).status_code == 422
    assert cli.post("/api/materia-prima", json={**CORRIDA, "qt_ok": -1}, headers=h).status_code == 422
    _lancar(cli, csrf)
    r = cli.post("/api/materia-prima", json=CORRIDA, headers=h)
    assert r.status_code == 409 and "já foi lançada" in r.json()["detail"]
    _lancar(cli, csrf, nf_entrada="654321")  # mesma corrida em outra NF é outra entrega


def test_acesso_negado(como, qualidade, db):
    pcp, csrf_pcp = como(modulos=["pcp"])
    cli, csrf = qualidade
    mp_id = _lancar(cli, csrf)
    assert pcp.get("/api/materia-prima").status_code == 403
    assert pcp.get(f"/api/materia-prima/{mp_id}").status_code == 403
    assert pcp.post("/api/materia-prima", json=CORRIDA, headers={"X-CSRF-Token": csrf_pcp}).status_code == 403
    assert pcp.get("/api/materia-prima/opcoes").status_code == 200  # seletor das outras telas
    # Qualidade sem "pode aprovar" não decide, não carimba, não reabre e não cancela
    h = {"X-CSRF-Token": csrf}
    assert cli.post(f"/api/materia-prima/{mp_id}/decisao", json={"decisao": "aprovada"}, headers=h).status_code == 403
    assert cli.post(f"/api/materia-prima/{mp_id}/reabrir", json={"motivo": "teste"}, headers=h).status_code == 403
    anexo_id = _anexar(cli, csrf, mp_id)
    assert cli.post(f"/api/materia-prima/{mp_id}/anexos/{anexo_id}/carimbar", headers=h).status_code == 403
    assert cli.post(f"/api/materia-prima/{mp_id}/cancelar", json={"motivo": "lançado errado"}, headers=h).status_code == 403
    assert db.get(MateriaPrima, mp_id).cancelado_em is None


def test_anexar_e_remover_certificado(qualidade, db, pasta_arquivos):
    cli, csrf = qualidade
    mp_id = _anexar_mp = _lancar(cli, csrf)
    pdf_id = _anexar(cli, csrf, _anexar_mp)
    _anexar(cli, csrf, mp_id, nome="foto.png", conteudo=_png(), tipo="image/png")
    r = cli.post(f"/api/materia-prima/{mp_id}/anexos", files=[("arquivos", ("x.exe", b"MZ", "application/octet-stream"))],
                 headers={"X-CSRF-Token": csrf})  # fmt: skip
    assert r.status_code == 422
    assert cli.get(f"/api/materia-prima/anexos/{pdf_id}/arquivo").content.startswith(b"%PDF")

    h = {"X-CSRF-Token": csrf}
    assert cli.post(f"/api/materia-prima/anexos/{pdf_id}/remover", json={"motivo": ""}, headers=h).status_code == 422
    r = cli.post(f"/api/materia-prima/anexos/{pdf_id}/remover", json={"motivo": "arquivo errado"}, headers=h)
    assert r.status_code == 200, r.text
    anexo = db.get(MateriaPrimaAnexo, pdf_id)
    assert anexo.removido_por == "Fulano de Tal" and anexo.removido_motivo == "arquivo errado"
    assert (pasta_arquivos / anexo.arquivo).is_file()  # nada é apagado do disco
    nomes = [a["nome"] for a in cli.get(f"/api/materia-prima/{mp_id}").json()["anexos"]]
    assert nomes == ["foto.png"]
    assert db.scalar(select(Auditoria).where(Auditoria.acao == "REMOVER", Auditoria.entidade == "anexo_mp"))


# ---------------------------------------------------------------- decisão e carimbo


def test_aprovar_reprovar_e_reabrir(qualidade, aprovador, db):
    cli, csrf = qualidade
    apr, csrf_apr = aprovador
    mp_id = _lancar(cli, csrf)
    h = {"X-CSRF-Token": csrf_apr}
    r = apr.post(f"/api/materia-prima/{mp_id}/decisao", json={"decisao": "reprovada", "observacao": ""}, headers=h)
    assert r.status_code == 422 and "motivo" in r.json()["detail"]
    r = apr.post(f"/api/materia-prima/{mp_id}/decisao", json={"decisao": "reprovada", "observacao": "Química fora"}, headers=h)
    assert r.status_code == 200, r.text
    mp = db.get(MateriaPrima, mp_id)
    db.refresh(mp)
    assert mp.status == "reprovada" and mp.aprovado_por == "Fulano Aprovador" and mp.obs_aprovacao == "Química fora"
    assert apr.post(f"/api/materia-prima/{mp_id}/decisao", json={"decisao": "aprovada"}, headers=h).status_code == 409
    # Reprovada não pode ser carimbada como aprovada
    anexo_id = _anexar(cli, csrf, mp_id)
    assert apr.post(f"/api/materia-prima/{mp_id}/anexos/{anexo_id}/carimbar", headers=h).status_code == 409

    assert apr.post(f"/api/materia-prima/{mp_id}/reabrir", json={"motivo": ""}, headers=h).status_code == 422
    assert apr.post(f"/api/materia-prima/{mp_id}/reabrir", json={"motivo": "Novo laudo"}, headers=h).status_code == 200
    db.refresh(mp)
    assert mp.status == "pendente" and mp.aprovado_por == "" and mp.aprovado_em is None
    assert apr.post(f"/api/materia-prima/{mp_id}/reabrir", json={"motivo": "de novo"}, headers=h).status_code == 409
    assert apr.post(f"/api/materia-prima/{mp_id}/decisao", json={"decisao": "aprovada"}, headers=h).status_code == 200
    acoes = list(db.scalars(select(Auditoria.acao).where(Auditoria.entidade == "materia_prima").order_by(Auditoria.id)))
    assert acoes == ["CRIAR", "REPROVAR", "ANEXAR", "REABRIR", "APROVAR"]


def test_carimbar_exige_assinatura(como, qualidade):
    cli, csrf = qualidade
    sem_assinatura, csrf_sem = como(modulos=["qualidade"], pode_aprovar=True)
    mp_id = _lancar(cli, csrf)
    anexo_id = _anexar(cli, csrf, mp_id)
    r = sem_assinatura.post(f"/api/materia-prima/{mp_id}/anexos/{anexo_id}/carimbar", headers={"X-CSRF-Token": csrf_sem})
    assert r.status_code == 422 and "assinatura" in r.json()["detail"]


def test_carimbar_aprova_e_propaga_para_os_lotes(qualidade, aprovador, db, pasta_arquivos):
    cli, csrf = qualidade
    apr, csrf_apr = aprovador
    mp_id = _lancar(cli, csrf)
    original_id = _anexar(cli, csrf, mp_id, nome="Certificado M999.pdf", conteudo=_pdf(3))
    outro_id = _anexar(cli, csrf, mp_id, nome="Laudo dimensional.pdf")
    imagem_id = _anexar(cli, csrf, mp_id, nome="foto.png", conteudo=_png(), tipo="image/png")
    # Um lote criado pela corrida (recebe os certificados) e um lote antigo ligado só pelo texto da corrida
    db.add(OrdemProducao(op="900001", tipo="PIN"))
    db.commit()
    r = cli.post(f"/api/materia-prima/{mp_id}/lotes", json={"op": "900001", "numero": "26-4-900001", "qtd": 50},
                 headers={"X-CSRF-Token": csrf})  # fmt: skip
    assert r.status_code == 201, r.text
    lote_novo = r.json()["lote_id"]
    antigo = lote_exemplo(db, numero="26-4-900002", qtd=20, corrida="M999/26")

    h = {"X-CSRF-Token": csrf_apr}
    assert apr.post(f"/api/materia-prima/{mp_id}/anexos/{imagem_id}/carimbar", headers=h).status_code == 422
    r = apr.post(f"/api/materia-prima/{mp_id}/anexos/{original_id}/carimbar", headers=h)
    assert r.status_code == 200, r.text
    resposta = r.json()
    assert resposta["corrida_aprovada"] is True and resposta["lotes_atualizados"] == 2
    assert resposta["nome"] == "Certificado M999_APROVADO.pdf"

    mp = db.get(MateriaPrima, mp_id)
    db.refresh(mp)
    assert mp.status == "aprovada" and mp.aprovado_por == "Fulano Aprovador"
    carimbado = db.get(MateriaPrimaAnexo, resposta["anexo_id"])
    doc = pymupdf.open(pasta_arquivos / carimbado.arquivo)
    assert doc.page_count == 3
    for pagina in doc:  # carimbo em TODAS as páginas, com a imagem da assinatura e sem data
        texto = pagina.get_text()
        assert "APROVADO" in texto and "Fulano Aprovador" in texto and "/2026" not in texto
        assert len(pagina.get_images()) == 1
    assert db.get(MateriaPrimaAnexo, original_id).removido_em is None  # o original continua na corrida

    def receb_mp(lote_id):
        return {a.nome: a for a in db.scalars(select(Anexo).where(Anexo.lote_id == lote_id, Anexo.etapa == "receb_mp"))}

    novo = receb_mp(lote_novo)
    assert novo["Certificado M999.pdf"].removido_em is not None  # o sem carimbo saiu da etapa (o arquivo fica)
    assert novo["Certificado M999_APROVADO.pdf"].removido_em is None
    assert novo["Laudo dimensional.pdf"].removido_em is None  # outro certificado da corrida não é tocado
    assert receb_mp(antigo.id)["Certificado M999_APROVADO.pdf"].removido_em is None
    eventos = list(db.scalars(select(Evento.texto).where(Evento.lote_id == antigo.id)))
    assert "Certificado APROVADO da corrida M999/26 propagado para Receb. MP" in eventos
    assert db.scalar(select(Auditoria).where(Auditoria.acao == "CARIMBAR", Auditoria.entidade_id == str(original_id)))

    # O carimbado não é carimbado de novo; refazer o carimbo substitui a versão anterior
    assert apr.post(f"/api/materia-prima/{mp_id}/anexos/{resposta['anexo_id']}/carimbar", headers=h).status_code == 422
    r = apr.post(f"/api/materia-prima/{mp_id}/anexos/{original_id}/carimbar", headers=h)
    assert r.status_code == 200 and r.json()["corrida_aprovada"] is False  # já estava aprovada
    db.expire_all()
    assert db.get(MateriaPrimaAnexo, resposta["anexo_id"]).removido_em is not None
    ativos = [a for a in db.scalars(select(Anexo).where(Anexo.lote_id == lote_novo, Anexo.removido_em.is_(None)))]
    assert sorted(a.nome for a in ativos) == ["Certificado M999_APROVADO.pdf", "Laudo dimensional.pdf", "foto.png"]
    lista = cli.get("/api/materia-prima").json()["itens"]
    assert lista[0]["tem_carimbado"] is True
    assert outro_id


def test_carimbo_de_pdf_girado_e_protegido(tmp_path):
    doc = pymupdf.open()
    doc.new_page().set_rotation(90)
    assinatura = tmp_path / "a.png"
    assinatura.write_bytes(_png())
    saida = pymupdf.open(stream=carimbar_pdf(doc.tobytes(), "Fulano", assinatura), filetype="pdf")
    assert saida[0].rotation == 0 and "APROVADO" in saida[0].get_text()
    protegido = pymupdf.open()
    protegido.new_page()
    cifrado = protegido.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="segredo", owner_pw="dono")
    with pytest.raises(ErroCarimbo):
        carimbar_pdf(cifrado, "Fulano", assinatura)
    with pytest.raises(ErroCarimbo):
        carimbar_pdf(b"%PDF-1.4 quebrado", "Fulano", assinatura)


# ---------------------------------------------------------------- lotes da corrida


def test_criar_lote_a_partir_da_corrida(qualidade, aprovador, db):
    cli, csrf = qualidade
    apr, csrf_apr = aprovador
    db.add(OrdemProducao(op="900001", coditem="12345", descricao="INSTR. CONTROLE TRAVAMENTO PIN 99 EXEMPLO", tipo="PIN"))
    db.add(OrdemProducao(op="900009", coditem="999", tipo="ARK"))
    db.commit()
    mp_id = _lancar(cli, csrf)
    original_id = _anexar(cli, csrf, mp_id, nome="Certificado M999.pdf")
    assert apr.post(f"/api/materia-prima/{mp_id}/anexos/{original_id}/carimbar", headers={"X-CSRF-Token": csrf_apr}).status_code == 200

    detalhe = cli.get(f"/api/materia-prima/{mp_id}").json()
    assert detalhe["ops"] == [{"op": "900001", "coditem": "12345", "descricao": "PIN 99 EXEMPLO", "qt_lote": None}]

    h = {"X-CSRF-Token": csrf}
    url = f"/api/materia-prima/{mp_id}/lotes"
    assert cli.post(url, json={"op": "900001", "numero": "L1", "qtd": 10, "tipo": "BOX"}, headers=h).status_code == 422
    r = cli.post(url, json={"op": "900001", "numero": "L1", "qtd": 177}, headers=h)
    assert r.status_code == 422 and "excede o saldo" in r.json()["detail"]  # saldo = 180 - 4
    assert cli.post(url, json={"op": "900001", "numero": "L1", "qtd": 0}, headers=h).status_code == 422
    r = cli.post(url, json={"op": "900001", "numero": "26-4-900001", "qtd": 176}, headers=h)
    assert r.status_code == 201, r.text
    lote = db.get(Lote, r.json()["lote_id"])
    assert (lote.materia_prima_id, lote.corrida, lote.coditem, lote.tipo) == (mp_id, "M999/26", "12345", "PIN")
    nomes = [a.nome for a in db.scalars(select(Anexo).where(Anexo.lote_id == lote.id, Anexo.etapa == "receb_mp"))]
    assert nomes == ["Certificado M999_APROVADO.pdf"]  # o original já tem versão carimbada: vai só ela
    eventos = list(db.scalars(select(Evento.texto).where(Evento.lote_id == lote.id).order_by(Evento.id)))
    assert eventos[0] == "Lote criado a partir da corrida M999/26 (NF 123456)" and "automaticamente" in eventos[1]
    assert cli.get(f"/api/materia-prima/{mp_id}").json()["corrida"]["qt_saldo"] == 0
    r = cli.post(url, json={"op": "900001", "numero": "26-4-900001", "qtd": 1}, headers=h)
    assert r.status_code == 422  # sem saldo


def test_vincular_lote_existente(qualidade, db):
    cli, csrf = qualidade
    mp_id = _lancar(cli, csrf, qt_ok=100, qt_cp_tt=0)
    box = lote_exemplo(db, numero="26-4-900010", tipo="BOX", qtd=10)
    grande = lote_exemplo(db, numero="26-4-900011", qtd=150, corrida="OUTRA")
    certo = lote_exemplo(db, numero="26-4-900012", qtd=60, corrida="OUTRA")
    vinculaveis = [v["numero"] for v in cli.get(f"/api/materia-prima/{mp_id}").json()["vinculaveis"]]
    assert vinculaveis == ["26-4-900012", "26-4-900011"]  # só lotes do tipo da corrida

    h = {"X-CSRF-Token": csrf}
    url = f"/api/materia-prima/{mp_id}/vincular"
    assert cli.post(url, json={"lote_id": box.id}, headers=h).status_code == 422
    assert cli.post(url, json={"lote_id": grande.id}, headers=h).status_code == 422
    assert cli.post(url, json={"lote_id": 999}, headers=h).status_code == 404
    assert cli.post(url, json={"lote_id": certo.id}, headers=h).status_code == 200
    db.refresh(certo)
    assert certo.corrida == "M999/26" and certo.materia_prima_id == mp_id
    assert cli.post(url, json={"lote_id": certo.id}, headers=h).status_code == 409
    assert db.scalar(select(Auditoria).where(Auditoria.lote_id == certo.id, Auditoria.acao == "ALTERAR"))


def test_editar_corrida_acompanha_os_lotes(qualidade, db):
    cli, csrf = qualidade
    mp_id = _lancar(cli, csrf)
    lote = lote_exemplo(db, numero="26-4-900001", qtd=10, materia_prima_id=mp_id, corrida="M999/26")
    h = {"X-CSRF-Token": csrf}
    r = cli.put(f"/api/materia-prima/{mp_id}", json={**CORRIDA, "tipo_destino": "BOX"}, headers=h)
    assert r.status_code == 409  # há lote PIN usando a corrida
    r = cli.put(f"/api/materia-prima/{mp_id}", json={**CORRIDA, "corrida": "M998/26", "qt_ok": 170}, headers=h)
    assert r.status_code == 200, r.text
    db.refresh(lote)
    assert lote.corrida == "M998/26"
    auditoria = db.scalar(select(Auditoria).where(Auditoria.entidade == "materia_prima", Auditoria.acao == "ALTERAR"))
    assert auditoria.detalhes == {"corrida": ["M999/26", "M998/26"], "qt_ok": [180, 170]}
    assert cli.put(f"/api/materia-prima/{mp_id}", json={**CORRIDA, "corrida": "M998/26", "qt_ok": 170},
                   headers=h).json()["mensagem"] == "Nada foi alterado."  # fmt: skip


def test_cancelar_corrida(como, qualidade, db, admin, cliente):
    cli, csrf = qualidade
    mp_id = _lancar(cli, csrf)
    lote = lote_exemplo(db, numero="26-4-900001", qtd=10, materia_prima_id=mp_id)
    h = {"X-CSRF-Token": admin}  # administrador cancela mesmo sem "pode aprovar"
    url = f"/api/materia-prima/{mp_id}/cancelar"
    assert cliente.post(url, json={"motivo": "x"}, headers=h).status_code == 422
    r = cliente.post(url, json={"motivo": "lançada em dobro"}, headers=h)
    assert r.status_code == 409 and "26-4-900001" in r.json()["detail"]
    lote.materia_prima_id = None
    db.commit()
    assert cliente.post(url, json={"motivo": "lançada em dobro"}, headers=h).status_code == 200
    assert cli.get(f"/api/materia-prima/{mp_id}").status_code == 404
    assert all(i["id"] != mp_id for i in cli.get("/api/materia-prima").json()["itens"])
    mp = db.get(MateriaPrima, mp_id)
    db.refresh(mp)
    assert mp.cancelado_por == "Administrador" and mp.cancelado_motivo == "lançada em dobro"  # continua no banco


def test_opcoes_para_outras_telas(como, qualidade):
    cli, csrf = qualidade
    _lancar(cli, csrf)
    _lancar(cli, csrf, corrida="M1/26", tipo_destino="ARK")
    pcp, _ = como(modulos=["pcp"])
    todas = pcp.get("/api/materia-prima/opcoes").json()
    assert [o["corrida"] for o in todas] == ["M1/26", "M999/26"] and todas[1]["qt_saldo"] == 176
    assert [o["corrida"] for o in pcp.get("/api/materia-prima/opcoes?tipo=ark").json()] == ["M1/26"]


ROTAS_DE_GRAVACAO = [
    ("post", "/api/materia-prima", CORRIDA),
    ("put", "/api/materia-prima/{mp}", CORRIDA),
    ("post", "/api/materia-prima/{mp}/cancelar", {"motivo": "teste"}),
    ("post", "/api/materia-prima/anexos/{anexo}/remover", {"motivo": "teste"}),
    ("post", "/api/materia-prima/{mp}/decisao", {"decisao": "aprovada"}),
    ("post", "/api/materia-prima/{mp}/reabrir", {"motivo": "teste"}),
    ("post", "/api/materia-prima/{mp}/anexos/{anexo}/carimbar", None),
    ("post", "/api/materia-prima/{mp}/lotes", {"op": "900001", "numero": "L1", "qtd": 1}),
    ("post", "/api/materia-prima/{mp}/vincular", {"lote_id": 1}),
]


def test_sem_modulo_qualidade_nada_e_gravado(como, qualidade, db):
    cli, csrf = qualidade
    mp_id = _lancar(cli, csrf)
    anexo_id = _anexar(cli, csrf, mp_id)
    pcp, csrf_pcp = como(modulos=["pcp", "producao_tt", "cadastros"], pode_aprovar=True)
    for metodo, rota, corpo in ROTAS_DE_GRAVACAO:
        url = rota.format(mp=mp_id, anexo=anexo_id)
        r = getattr(pcp, metodo)(url, json=corpo, headers={"X-CSRF-Token": csrf_pcp})
        assert r.status_code == 403, (metodo, url, r.text)
    r = pcp.post(f"/api/materia-prima/{mp_id}/anexos", files=[("arquivos", ("a.pdf", _pdf(), "application/pdf"))],
                 headers={"X-CSRF-Token": csrf_pcp})  # fmt: skip
    assert r.status_code == 403
    assert pcp.get(f"/api/materia-prima/anexos/{anexo_id}/arquivo").status_code == 403
    gravado = select(Auditoria).where(Auditoria.login == "usuario2", Auditoria.acao.not_in(["LOGIN", "TROCAR_SENHA"]))
    assert db.scalar(gravado) is None
