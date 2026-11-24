"""Databook: geração do PDF, conferência e controle de envio ao cliente (Enviado-DB). Tudo com dados fictícios."""
import io
import os
import time
import uuid
from datetime import datetime

import pymupdf
import pytest
from conftest import lote_exemplo
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import select

from app import api_databooks, fluxo
from app.models import Anexo, Auditoria, DatabookEnviado, Evento, OrdemProducao, Registro, Usuario

ARQ_PIN = "Databook_DB-26-4-900001-PIN_Rev0.pdf"


# ---------------------------------------------------------------- montagem do cenário


def _pdf(*linhas: str, paginas: int = 1) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for _ in range(paginas):
        y = 780
        for linha in linhas:
            c.drawString(72, y, linha)
            y -= 20
        c.showPage()
    c.save()
    return buf.getvalue()


def _png(largura: int = 300, altura: int = 200) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (largura, altura), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _anexar(db, pasta, lote, etapa, nome, conteudo, sub="", **extra):
    relativo = f"lotes/{lote.id}/anexos/{uuid.uuid4().hex[:8]}_{nome.replace(' ', '_')}"
    (pasta / relativo).parent.mkdir(parents=True, exist_ok=True)
    (pasta / relativo).write_bytes(conteudo)
    anexo = Anexo(lote_id=lote.id, etapa=etapa, sub=sub, nome=nome, arquivo=relativo, quando=datetime(2026, 11, 21, 9, 0), **extra)
    db.add(anexo)
    db.commit()
    return anexo


def _concluir(db, lote):
    """Registro aprovado em todas as etapas que se aplicam ao tipo (lote concluído)."""
    for etapa in fluxo.ETAPAS:
        if etapa.aplicavel(lote.tipo):
            for sub in etapa.subs_de(lote.tipo):
                db.add(Registro(lote_id=lote.id, etapa=etapa.chave, sub=sub, status="aprovado",
                                quando=datetime(2026, 11, 21, 9, 0), responsavel="Fulano"))  # fmt: skip
    db.commit()


def _lote_pin_completo(db, pasta):
    db.add(OrdemProducao(op="900001", cliente="EXEMPLO INDUSTRIAL S.A.", coditem="12345", projeto="PROJETO EXEMPLO",
                         po="PO-123", descricao="INSTR. CONTROLE TRAVAMENTO PIN 18-24 EXEMPLO", tipo="PIN"))  # fmt: skip
    lote = lote_exemplo(db, coditem="12345", corrida="M999/26")
    ref = "OP 900001 - Lote 26-4-900001"
    _anexar(db, pasta, lote, "receb_mp", "01 Certificado MP.pdf", _pdf("CERTIFICADO MP", ref))
    _anexar(db, pasta, lote, "trat_termico", "Relatorio TT.pdf", _pdf("RELATORIO TT", ref, paginas=2))
    _anexar(db, pasta, lote, "dureza", "Relatorio Dureza.pdf", _pdf("RELATORIO DUREZA", ref))
    _anexar(db, pasta, lote, "lab_ext", "Laudo Tracao Charpy.pdf", _pdf("LAUDO LABORATORIO", ref))  # sem sub: vale para as duas
    _anexar(db, pasta, lote, "usinagem", "Foto usinagem.png", _png())
    _anexar(db, pasta, lote, "dim_final", "RIP-33A.pdf", _pdf("DIMENSIONAL", ref))
    _anexar(db, pasta, lote, "lp", "Liquido penetrante.pdf", _pdf("LIQUIDO PENETRANTE", ref))
    _anexar(db, pasta, lote, "fosfato", "Certificado fosfato.pdf", _pdf("CERTIFICADO FOSFATO", ref))
    _anexar(db, pasta, lote, "visual", "Relatorio Visual.pdf", _pdf("VISUAL ANTIGO", ref))
    _anexar(db, pasta, lote, "visual", "Relatorio Visual.pdf", _pdf("VISUAL NOVO", ref))  # mesmo nome: vale o mais novo
    _anexar(db, pasta, lote, "visual", "Foto interna.pdf", _pdf("FOTO INTERNA"), apenas_registro=True)
    _anexar(db, pasta, lote, "lp", "Errado.pdf", _pdf("ANEXO REMOVIDO"), removido_em=datetime(2026, 11, 21, 10, 0))
    _concluir(db, lote)
    return lote


def _aprovador(como, db, pasta, com_assinatura=True):
    como(modulos=["qualidade"], pode_aprovar=True, login="aprovador", nome="Beltrano Aprovador")
    usuario = db.scalar(select(Usuario).where(Usuario.login == "aprovador"))
    usuario.cargo = "Gerente da Qualidade"
    if com_assinatura:
        (pasta / "assinaturas").mkdir(parents=True, exist_ok=True)
        (pasta / "assinaturas" / "aprovador.png").write_bytes(_png(400, 120))
        usuario.assinatura_arquivo = "assinaturas/aprovador.png"
    db.commit()
    return usuario


def _gerar(cliente, csrf, lote_id, aprovador_id, data="2026-11-24", **extra):
    corpo = {"data_aprovacao": data, "aprovador_id": aprovador_id, **extra}
    return cliente.post(f"/api/databooks/lote/{lote_id}/gerar", json=corpo, headers={"X-CSRF-Token": csrf})


def _paginas(conteudo: bytes) -> list[str]:
    with pymupdf.open(stream=conteudo, filetype="pdf") as doc:
        return [pagina.get_text() for pagina in doc]


# ---------------------------------------------------------------- geração


def test_gera_databook_com_capa_indice_secoes_e_rodape(como, db, pasta_arquivos):
    lote = _lote_pin_completo(db, pasta_arquivos)
    aprovador = _aprovador(como, db, pasta_arquivos)
    qualidade, csrf = como(modulos=["qualidade"], nome="Fulano Elaborador")

    r = _gerar(qualidade, csrf, lote.id, aprovador.id)
    assert r.status_code == 201, r.text
    resposta = r.json()
    assert resposta["arquivo"] == ARQ_PIN and resposta["revisao"] == 0
    assert resposta["alertas"] == []

    pdf = (pasta_arquivos / f"lotes/{lote.id}/databook/saida/{ARQ_PIN}").read_bytes()
    assert pdf.startswith(b"%PDF")
    # cópia na pasta da OP (a antiga DATABOOK\LOTE-OP...) e o relatório de conferência
    assert (pasta_arquivos / f"databooks/LOTE-OP900001-PIN/{ARQ_PIN}").read_bytes() == pdf
    relatorio = (pasta_arquivos / f"lotes/{lote.id}/databook/saida/Relatorio_Conferencia_DB-26-4-900001-PIN_Rev0.txt").read_text("utf-8")
    assert "ALERTAS" in relatorio and "Nenhum." in relatorio

    paginas = _paginas(pdf)
    capa = paginas[0]
    for texto in ("DATABOOK", "Dossiê de Qualidade do Produto", "Exemplo", "PROJETO EXEMPLO", "PIN 18-24 EXEMPLO", "PO-123",
                  "26-4-900001", "72", "DB-26-4-900001", "24/11/2026", "Fulano Elaborador", "Beltrano Aprovador",
                  "Gerente da Qualidade", "AçoKorte Indústria Metalúrgica e Comércio"):  # fmt: skip
        assert texto in capa, texto
    assert "Página" not in capa  # a capa não é numerada
    assert "ÍNDICE" in paginas[1] and "1. Certificado Composicao Quimica" in paginas[1]
    assert f"Página 2 de {len(paginas)}" in paginas[1] and "Exemplo - PROJETO EXEMPLO" in paginas[1]
    tudo = "\n".join(paginas)
    for secao in ("CERTIFICADO COMPOSICAO QUIMICA", "RELATORIO TRATAMENTO TERMICO", "RELATORIO DUREZA HRC", "ENSAIO DE TRACAO",
                  "ENSAIO DE IMPACTO CHARPY", "RELATORIO DIMENSIONAL", "ENSAIO LIQUIDO PENETRANTE",
                  "CERTIFICADO FOSFATO DE MANGANES", "INSPECAO VISUAL E MARCACAO LASER"):  # fmt: skip
        assert secao in tudo, secao
    assert tudo.count("LAUDO LABORATORIO") == 2  # laudo sem subdivisão entra em tração e em Charpy
    assert "VISUAL NOVO" in tudo and "VISUAL ANTIGO" not in tudo
    assert "FOTO INTERNA" not in tudo and "ANEXO REMOVIDO" not in tudo
    # capa (1) + índice (1) + 9 separadores + 11 páginas de documento (TT tem 2; a foto vira 1 página)
    assert len(paginas) == 2 + 9 + 11

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        assert len(doc[0].get_images()) == 2  # logo + assinatura digital do aprovador
        links = doc[1].get_links()
        assert len(links) == 9 and links[0]["page"] == 2  # o índice leva à seção 1 (página 3)
        marcadores = [t[1] for t in doc.get_toc()]
        assert marcadores[:3] == ["Capa", "Índice", "1. Certificado Composicao Quimica"]

    db.expire_all()
    assert db.scalar(select(Evento.texto).where(Evento.lote_id == lote.id)) == "Databook gerado (rev. 0)"
    auditoria = db.scalar(select(Auditoria).where(Auditoria.acao == "GERAR"))
    assert auditoria.lote_id == lote.id and auditoria.detalhes["aprovado_por"] == "Beltrano Aprovador"

    # nova revisão: Rev 1, sem mexer na Rev 0
    r = _gerar(qualidade, csrf, lote.id, aprovador.id, produto="CHAVETA PIN EXEMPLO")
    assert r.status_code == 201 and r.json()["revisao"] == 1
    assert (pasta_arquivos / f"lotes/{lote.id}/databook/saida/{ARQ_PIN}").read_bytes() == pdf
    info = qualidade.get(f"/api/databooks/lote/{lote.id}").json()
    assert info["databook"]["revisao"] == 1 and [r["revisao"] for r in info["revisoes"]] == [1, 0]
    assert info["capa"]["proxima_revisao"] == 2 and info["concluido"] is True
    baixado = qualidade.get(f"/api/databooks/lote/{lote.id}/pdf")
    assert baixado.status_code == 200 and "CHAVETA PIN EXEMPLO" in _paginas(baixado.content)[0]
    antigo = qualidade.get(f"/api/databooks/lote/{lote.id}/pdf", params={"arquivo": ARQ_PIN})
    assert antigo.content == pdf


def test_ark_sem_tracao_dureza_e_com_oxidacao_negra(como, db, pasta_arquivos):
    (pasta_arquivos / "recursos/desenhos").mkdir(parents=True)
    (pasta_arquivos / "recursos/desenhos/ORIGEM - 55555 ARK 18-24 EXEMPLO.pdf").write_bytes(_pdf("DESENHO"))
    lote = lote_exemplo(db, numero="26-4-900003", op="900003", tipo="ARK", coditem="55555")
    _anexar(db, pasta_arquivos, lote, "receb_mp", "Certificado.pdf", _pdf("MP"))
    _anexar(db, pasta_arquivos, lote, "lab_ext", "Charpy.pdf", _pdf("CHARPY ARK"))
    _anexar(db, pasta_arquivos, lote, "fosfato", "Oxidacao.pdf", _pdf("OXIDACAO"))
    _concluir(db, lote)
    aprovador = _aprovador(como, db, pasta_arquivos, com_assinatura=False)
    qualidade, csrf = como(modulos=["qualidade"])

    info = qualidade.get(f"/api/databooks/lote/{lote.id}").json()
    assert info["capa"]["produto"] == 'ANTI-ROTATIONAL KEY 18-24"'  # sem descrição da OP: palpite pelo desenho
    r = _gerar(qualidade, csrf, lote.id, aprovador.id)
    assert r.status_code == 201, r.text
    tudo = "\n".join(_paginas((pasta_arquivos / f"lotes/{lote.id}/databook/saida/{r.json()['arquivo']}").read_bytes()))
    assert "CERTIFICADO OXIDACAO NEGRA" in tudo and "FOSFATO" not in tudo
    assert "ENSAIO DE TRACAO" not in tudo and tudo.count("CHARPY ARK") == 1
    assert "ANTI-ROTATIONAL KEY 18-24\"" in tudo
    # o checklist do ARK não cobra dureza nem tração
    alertas = r.json()["alertas"]
    assert not any("dureza" in a or "tracao" in a for a in alertas)
    assert any("termico" in a for a in alertas) and any("oxidacao" not in a for a in alertas)


def test_alertas_de_checklist_e_arquivo_com_problema(como, db, pasta_arquivos):
    lote = lote_exemplo(db)
    _anexar(db, pasta_arquivos, lote, "receb_mp", "Certificado.pdf", _pdf("MP"))
    _anexar(db, pasta_arquivos, lote, "trat_termico", "Corrompido.pdf", b"%PDF-1.4 isto nao e um pdf")
    sumido = _anexar(db, pasta_arquivos, lote, "lp", "Sumiu.pdf", _pdf("LP"))
    (pasta_arquivos / sumido.arquivo).unlink()
    _concluir(db, lote)
    aprovador = _aprovador(como, db, pasta_arquivos, com_assinatura=False)
    qualidade, csrf = como(modulos=["qualidade"])

    r = _gerar(qualidade, csrf, lote.id, aprovador.id)
    assert r.status_code == 201, r.text
    alertas = r.json()["alertas"]
    assert "[FALTA] Nenhum documento com 'dureza' (checklist)" in alertas
    assert any(a.startswith("[ERRO ] Arquivo ignorado: Relatorio Tratamento Termico/Corrompido.pdf") for a in alertas)
    assert any("Sumiu.pdf: arquivo não encontrado no servidor" in a for a in alertas)
    assert "[VAZIA] Seção sem documentos: Relatorio Tratamento Termico" in alertas
    assert qualidade.get(f"/api/databooks/lote/{lote.id}").json()["alertas"] == alertas


def test_bloqueios_da_geracao(como, db, pasta_arquivos):
    lote = lote_exemplo(db)
    _anexar(db, pasta_arquivos, lote, "receb_mp", "Certificado.pdf", _pdf("MP"))
    aprovador = _aprovador(como, db, pasta_arquivos, com_assinatura=False)
    qualidade, csrf = como(modulos=["qualidade"], login="semaprovar")
    sem_poder = db.scalar(select(Usuario).where(Usuario.login == "semaprovar"))

    r = _gerar(qualidade, csrf, lote.id, aprovador.id)
    assert r.status_code == 409 and "todas as etapas" in r.json()["detail"]
    _concluir(db, lote)
    r = _gerar(qualidade, csrf, lote.id, aprovador.id, data=None)
    assert r.status_code == 422 and "DATA DE APROVAÇÃO" in r.json()["detail"]
    r = _gerar(qualidade, csrf, lote.id, sem_poder.id)
    assert r.status_code == 422 and "Aprovado por" in r.json()["detail"]
    assert qualidade.get(f"/api/databooks/lote/{lote.id}/pdf").status_code == 404
    assert qualidade.get(f"/api/databooks/lote/{lote.id}/conferencia").status_code == 404

    vazio = lote_exemplo(db, numero="26-4-900009", op="900009")
    _concluir(db, vazio)
    r = _gerar(qualidade, csrf, vazio.id, aprovador.id)
    assert r.status_code == 422 and "Nenhum documento" in r.json()["detail"]
    assert not (pasta_arquivos / f"lotes/{vazio.id}/databook").exists()


def test_revisao_nunca_sobrescreve_pdf_da_pasta_da_op(como, db, pasta_arquivos):
    """PDF trazido do sistema antigo na pasta da OP, sem o da pasta do lote: a geração continua a numeração."""
    lote = _lote_pin_completo(db, pasta_arquivos)
    antigo = pasta_arquivos / f"databooks/LOTE-OP900001-PIN/{ARQ_PIN}"
    antigo.parent.mkdir(parents=True)
    antigo.write_bytes(b"%PDF-1.4 antigo")
    aprovador = _aprovador(como, db, pasta_arquivos, com_assinatura=False)
    qualidade, csrf = como(modulos=["qualidade"])
    r = _gerar(qualidade, csrf, lote.id, aprovador.id)
    assert r.status_code == 201 and r.json()["revisao"] == 1
    assert antigo.read_bytes() == b"%PDF-1.4 antigo"
    # a revisão que só está na pasta da OP também abre pelo lote; nome fora do padrão não abre nada
    assert qualidade.get(f"/api/databooks/lote/{lote.id}/pdf", params={"arquivo": ARQ_PIN}).content == b"%PDF-1.4 antigo"
    assert qualidade.get(f"/api/databooks/lote/{lote.id}/pdf", params={"arquivo": "../../teste.db"}).status_code == 404


# ---------------------------------------------------------------- conferência


def test_conferencia_aponta_pagina_com_op_errada(como, db, pasta_arquivos):
    lote = _lote_pin_completo(db, pasta_arquivos)
    _anexar(db, pasta_arquivos, lote, "dim_final", "Trocado.pdf", _pdf("RELATORIO DA OP 900002", "Lote 26-4-900002"))
    aprovador = _aprovador(como, db, pasta_arquivos, com_assinatura=False)
    qualidade, csrf = como(modulos=["qualidade"])
    assert _gerar(qualidade, csrf, lote.id, aprovador.id).status_code == 201

    r = qualidade.get(f"/api/databooks/lote/{lote.id}/conferencia")
    assert r.status_code == 200, r.text
    corpo = r.json()
    resultado = corpo["resultado"]
    assert corpo["arquivo"] == ARQ_PIN and resultado["ok"] is True
    assert resultado["op_esperada"] == "900001" and resultado["lote_esperado"] == "26-4-900001"
    paginas = _paginas((pasta_arquivos / f"lotes/{lote.id}/databook/saida/{ARQ_PIN}").read_bytes())
    pagina_trocada = next(i + 1 for i, texto in enumerate(paginas) if "900002" in texto)
    assert [i["pagina"] for i in resultado["inconsistencias"]] == [pagina_trocada]
    inconsistencia = resultado["inconsistencias"][0]
    assert inconsistencia["ops_erradas"] == ["900002"] and inconsistencia["lotes_errados"] == ["26-4-900002"]
    assert "900002" in inconsistencia["contexto"]
    assert resultado["total_paginas"] == len(paginas)
    assert resultado["paginas_ok"] == resultado["paginas_com_referencia"] - 1


# ---------------------------------------------------------------- controle de envio (Enviado-DB)


def test_marcar_enviado_e_desfazer_sem_apagar_nada(como, db, pasta_arquivos):
    lote = _lote_pin_completo(db, pasta_arquivos)
    aprovador = _aprovador(como, db, pasta_arquivos, com_assinatura=False)
    qualidade, csrf = como(modulos=["qualidade"], nome="Fulano Qualidade")
    cab = {"X-CSRF-Token": csrf}
    assert _gerar(qualidade, csrf, lote.id, aprovador.id).status_code == 201

    painel = qualidade.get("/api/databooks").json()
    assert painel["n_a_enviar"] == 1 and painel["n_enviados"] == 0
    item = painel["a_enviar"][0]
    assert (item["op"], item["tipo"], item["lote"], item["revisao"], item["arquivo"], item["lote_id"]) == (
        "900001", "PIN", "26-4-900001", 0, ARQ_PIN, lote.id)  # fmt: skip
    assert qualidade.get("/api/databooks", params={"tipo": "BOX"}).json()["a_enviar"] == []
    aberto = qualidade.get("/api/databooks/arquivo", params={"op": "900001", "tipo": "PIN", "arquivo": ARQ_PIN})
    assert aberto.status_code == 200 and aberto.content.startswith(b"%PDF")
    assert qualidade.get(f"/api/databooks/lote/{lote.id}").json()["pendente_envio"]["arquivo"] == ARQ_PIN

    envio = {"op": "900001", "tipo": "PIN", "arquivo": ARQ_PIN, "data_envio": "2026-11-24", "destinatario": "  ",
             "nf_saida": "NF 123", "observacoes": "Enviado por e-mail"}  # fmt: skip
    r = qualidade.post("/api/databooks/envios", json=envio, headers=cab)
    assert r.status_code == 422 and "destinatário" in r.json()["detail"]
    envio["destinatario"] = "Fulano (CLIENTE EXEMPLO)"
    r = qualidade.post("/api/databooks/envios", json=envio, headers=cab)
    assert r.status_code == 201, r.text
    criado = r.json()
    assert criado["revisao"] == 0 and criado["lote"] == "26-4-900001" and criado["enviado_por"] == "Fulano Qualidade"
    assert criado["data_envio"] == "2026-11-24" and criado["lote_id"] == lote.id
    # copiado para Enviados; o original continua na pasta da OP
    assert (pasta_arquivos / f"databooks/Enviados/{ARQ_PIN}").is_file()
    assert (pasta_arquivos / f"databooks/LOTE-OP900001-PIN/{ARQ_PIN}").is_file()
    assert qualidade.post("/api/databooks/envios", json=envio, headers=cab).status_code == 409

    painel = qualidade.get("/api/databooks").json()
    assert painel["n_a_enviar"] == 0 and painel["n_enviados"] == 1
    assert painel["enviados"][0]["destinatario"] == "Fulano (CLIENTE EXEMPLO)"
    assert qualidade.get(f"/api/databooks/envios/{criado['id']}/arquivo").content.startswith(b"%PDF")
    info = qualidade.get(f"/api/databooks/lote/{lote.id}").json()
    assert info["pendente_envio"] is None and info["envios"][0]["id"] == criado["id"]
    assert api_databooks.ops_com_databook_enviado(db) == {("900001", "PIN")}
    assert api_databooks.databook_enviado(db, "900001", "pin") is True

    r = qualidade.post(f"/api/databooks/envios/{criado['id']}/desfazer", json={"motivo": ""}, headers=cab)
    assert r.status_code == 422
    r = qualidade.post(f"/api/databooks/envios/{criado['id']}/desfazer", json={"motivo": "Marcado por engano"}, headers=cab)
    assert r.status_code == 200 and r.json()["desfeito_por"] == "Fulano Qualidade"
    assert qualidade.post(f"/api/databooks/envios/{criado['id']}/desfazer", json={"motivo": "De novo"}, headers=cab).status_code == 409
    db.expire_all()
    linha = db.get(DatabookEnviado, criado["id"])
    assert linha is not None and linha.desfeito_em is not None and linha.desfeito_motivo == "Marcado por engano"
    assert (pasta_arquivos / f"databooks/Enviados/{ARQ_PIN}").is_file()  # nada é apagado
    painel = qualidade.get("/api/databooks").json()
    assert painel["n_a_enviar"] == 1 and painel["n_enviados"] == 0 and painel["enviados"] == []
    assert len(qualidade.get("/api/databooks", params={"incluir_desfeitos": True}).json()["enviados"]) == 1
    assert api_databooks.databook_enviado(db, "900001", "PIN") is False

    # de novo, agora é outro nome em Enviados (o primeiro continua lá)
    r = qualidade.post("/api/databooks/envios", json=envio, headers=cab)
    assert r.status_code == 201
    assert len(list((pasta_arquivos / "databooks/Enviados").iterdir())) == 2
    acoes = list(db.scalars(select(Auditoria.acao).where(Auditoria.entidade == "databook_envio").order_by(Auditoria.id)))
    assert acoes == ["ENVIAR", "DESFAZER", "ENVIAR"]


def test_envio_trazido_do_sistema_antigo(como, db, pasta_arquivos):
    """No antigo o PDF enviado SAÍA da pasta da OP. Desfazer devolve uma cópia para lá."""
    lote = lote_exemplo(db)
    enviado = pasta_arquivos / f"databooks/Enviados/{ARQ_PIN}"
    enviado.parent.mkdir(parents=True)
    enviado.write_bytes(_pdf("DATABOOK ANTIGO"))
    (pasta_arquivos / "databooks/LOTE-OP900001-PIN").mkdir()
    db.add(DatabookEnviado(op="900001", tipo="PIN", lote="26-4-900001", revisao=0, arquivo=ARQ_PIN,
                           caminho=f"databooks/Enviados/{ARQ_PIN}", destinatario="Fulano"))  # fmt: skip
    db.commit()
    qualidade, csrf = como(modulos=["qualidade"])
    painel = qualidade.get("/api/databooks").json()
    assert painel["n_a_enviar"] == 0 and painel["enviados"][0]["lote_id"] == lote.id
    envio_id = painel["enviados"][0]["id"]
    r = qualidade.post(f"/api/databooks/envios/{envio_id}/desfazer", json={"motivo": "Teste"}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    assert (pasta_arquivos / f"databooks/LOTE-OP900001-PIN/{ARQ_PIN}").read_bytes() == enviado.read_bytes()
    assert qualidade.get("/api/databooks").json()["a_enviar"][0]["arquivo"] == ARQ_PIN


def test_a_enviar_mostra_so_a_revisao_mais_recente_de_cada_lote(como, db, pasta_arquivos):
    pasta = pasta_arquivos / "databooks/LOTE-OP900001-PIN"
    pasta.mkdir(parents=True)
    for nome in (ARQ_PIN, "Databook_DB-26-4-900001-PIN_Rev1.pdf", "Databook_DB-26-4-900001A-PIN_Rev0.pdf", "outro.pdf"):
        (pasta / nome).write_bytes(_pdf("X"))
    (pasta_arquivos / "databooks/Enviados").mkdir()
    qualidade, _csrf = como(modulos=["qualidade"])
    itens = qualidade.get("/api/databooks").json()["a_enviar"]
    assert [(i["lote"], i["revisao"]) for i in itens] == [("26-4-900001", 1), ("26-4-900001A", 0)]
    # revisão mais nova já enviada: a antiga não volta para a lista
    db.add(DatabookEnviado(op="900001", tipo="PIN", lote="26-4-900001", revisao=1, arquivo="Databook_DB-26-4-900001-PIN_Rev1.pdf",
                           caminho="", destinatario="Fulano"))  # fmt: skip
    db.commit()
    (pasta / "Databook_DB-26-4-900001-PIN_Rev1.pdf").unlink()
    itens = qualidade.get("/api/databooks").json()["a_enviar"]
    assert [(i["lote"], i["revisao"]) for i in itens] == [("26-4-900001A", 0)]
    # databook de lote cancelado não vai para o cliente
    lote_exemplo(db, numero="26-4-900001A", cancelado_em=datetime(2026, 11, 22, 8, 0), cancelado_motivo="Teste")
    assert qualidade.get("/api/databooks").json()["a_enviar"] == []


def test_nomes_de_arquivo_invalidos(como):
    qualidade, csrf = como(modulos=["qualidade"])
    for params in ({"op": "900001", "tipo": "PIN", "arquivo": "../../teste.db"},
                   {"op": "..", "tipo": "PIN", "arquivo": ARQ_PIN},
                   {"op": "900001", "tipo": "XYZ", "arquivo": ARQ_PIN},
                   {"op": "900001", "tipo": "PIN", "arquivo": ARQ_PIN}):  # fmt: skip
        assert qualidade.get("/api/databooks/arquivo", params=params).status_code == 404, params
    r = qualidade.post("/api/databooks/envios", json={"op": "900001", "tipo": "PIN", "arquivo": "../x.pdf", "destinatario": "Fulano"},
                       headers={"X-CSRF-Token": csrf})  # fmt: skip
    assert r.status_code == 404


# ---------------------------------------------------------------- funções para o painel


def test_pendentes_e_concluidos_sem_databook(como, db, pasta_arquivos):
    lote = _lote_pin_completo(db, pasta_arquivos)
    outro = lote_exemplo(db, numero="26-4-900005", op="900005", tipo="BOX")
    _concluir(db, outro)
    assert {d["lote_id"] for d in api_databooks.concluidos_sem_databook(db)} == {lote.id, outro.id}
    aprovador = _aprovador(como, db, pasta_arquivos, com_assinatura=False)
    qualidade, csrf = como(modulos=["qualidade"])
    assert _gerar(qualidade, csrf, lote.id, aprovador.id).status_code == 201
    assert [d["lote_id"] for d in api_databooks.concluidos_sem_databook(db)] == [outro.id]
    assert api_databooks.databooks_pendentes(db) == []  # gerado agora: ainda não passou de 3 dias

    quatro_dias = time.time() - 4 * 86400
    os.utime(pasta_arquivos / f"lotes/{lote.id}/databook/saida/{ARQ_PIN}", (quatro_dias, quatro_dias))
    pendentes = api_databooks.databooks_pendentes(db, dias=3)
    assert [(p["lote_id"], p["dias"]) for p in pendentes] == [(lote.id, 4)]
    db.add(DatabookEnviado(op="900001", tipo="PIN", lote="26-4-900001", revisao=0, arquivo=ARQ_PIN, destinatario="Fulano"))
    db.commit()
    assert api_databooks.databooks_pendentes(db) == []


# ---------------------------------------------------------------- permissões


@pytest.mark.parametrize("metodo,caminho", [
    ("get", "/api/databooks"),
    ("get", "/api/databooks/arquivo?op=900001&tipo=PIN&arquivo=" + ARQ_PIN),
    ("post", "/api/databooks/envios"),
    ("post", "/api/databooks/envios/1/desfazer"),
    ("get", "/api/databooks/envios/1/arquivo"),
    ("get", "/api/databooks/lote/1"),
    ("post", "/api/databooks/lote/1/gerar"),
    ("get", "/api/databooks/lote/1/pdf"),
    ("get", "/api/databooks/lote/1/conferencia"),
])  # fmt: skip
def test_sem_modulo_qualidade_nao_acessa(como, db, metodo, caminho):
    lote_exemplo(db)
    outro, csrf = como(modulos=["pcp", "producao_tt"], pode_aprovar=True)
    if metodo == "get":
        r = outro.get(caminho)
    else:
        r = outro.post(caminho, json={}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 403, r.text
