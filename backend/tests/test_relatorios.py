"""Relatórios gerados pelo sistema: Dureza (RIP-35), Tratamento Térmico e Inspeção Visual. Dados fictícios."""
import io
from datetime import date
from decimal import Decimal

import pymupdf
import pytest
from conftest import lote_exemplo
from PIL import Image
from sqlalchemy import select

from app import fluxo, leitura_foto
from app.api_relatorios import formatar_laser, formato_legivel, lote_completo
from app.config import config
from app.leitura_foto import CelulaLida, ErroLeitura, FolhaLida, LinhaLida
from app.models import (
    Anexo,
    Auditoria,
    CargaTT,
    Equipamento,
    EspecificacaoTipo,
    Evento,
    Lote,
    NaoConformidade,
    OrdemProducao,
    Registro,
    Usuario,
)
from app.relatorios_dados import codigo_do_desenho, item_sem_dimensoes

LOTE_PIN = {"numero": "26-4-900001", "op": "900001", "tipo": "PIN", "corrida": "M999/26", "coditem": "1234567"}


def _png(cor=(90, 127, 165)) -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", (60, 30), cor).save(saida, format="PNG")
    return saida.getvalue()


@pytest.fixture
def base(db, pasta_arquivos):
    """Especificação, equipamentos e as imagens dos pontos de dureza (fictícias)."""
    db.add_all([
        EspecificacaoTipo(tipo="PIN", dureza_min=Decimal("30"), dureza_max=Decimal("39")),
        EspecificacaoTipo(tipo="BOX", dureza_min=Decimal("30"), dureza_max=Decimal("39")),
        EspecificacaoTipo(tipo="ARK", dureza_min=Decimal("43"), dureza_max=Decimal("48")),
        Equipamento(codigo="DUR-01", descricao="Durômetro de bancada", marca="Marca Exemplo", certificado="0001/26",
                    data_calibracao=date(2026, 1, 10), validade_calibracao=date(2027, 1, 10)),
        Equipamento(codigo="FO-01", descricao="Forno de Têmpera", marca="Marca Exemplo"),
        Equipamento(codigo="FO-02", descricao="Forno de Revenimento", marca="Marca Exemplo"),
    ])  # fmt: skip
    db.commit()
    pasta = pasta_arquivos / "recursos" / "relatorios"
    pasta.mkdir(parents=True)
    (pasta / "dureza_pin.png").write_bytes(_png())
    (pasta / "dureza_box.png").write_bytes(_png((200, 120, 40)))


def _id(db, login: str) -> int:
    return db.scalar(select(Usuario.id).where(Usuario.login == login))


def _aprovados(db, lote: Lote, *etapas: str) -> None:
    for etapa in etapas:
        db.add(Registro(lote_id=lote.id, etapa=etapa, status="aprovado"))
    lote.etapa = fluxo.INDICE[etapas[-1]] + 1 if etapas else 0
    db.commit()


def _texto_pdf(pasta, anexo: Anexo) -> str:
    conteudo = (pasta / anexo.arquivo).read_bytes()
    assert conteudo.startswith(b"%PDF")
    with pymupdf.open(stream=conteudo, filetype="pdf") as doc:
        return "\n".join(pagina.get_text() for pagina in doc)


def _ultimo(db, modelo, lote_id: int, etapa: str):
    db.expire_all()
    return db.scalar(select(modelo).where(modelo.lote_id == lote_id, modelo.etapa == etapa).order_by(modelo.id.desc()))


# ---------------------------------------------------------------- dureza (RIP-35)


def _dureza(executor: int, aprovador: int, *valores: str, **extra) -> dict:
    return {"leituras": [{"cp": "", "valores": list(valores)}], "equipamento_codigo": "DUR-01", "executado_por": executor,
            "aprovado_por": aprovador, "data": "2026-11-24", "data_aprovacao": "2026-11-25"} | extra  # fmt: skip


def test_dureza_aprovada_gera_pdf_registro_e_avanca_o_lote(db, base, como, pasta_arquivos):
    lote = lote_exemplo(db, **LOTE_PIN)
    _aprovados(db, lote, "receb_mp", "trat_termico")  # cursor parado na dureza
    qualidade, csrf = como(modulos=["qualidade"], pode_aprovar=True, login="gerente", nome="Beltrano Gerente")
    gerente = _id(db, "gerente")

    tela = qualidade.get(f"/api/relatorios/dureza/{lote.id}")
    assert tela.status_code == 200, tela.text
    tela = tela.json()
    assert tela["info"]["especificacao"] == "30 a 39 HRc" and tela["info"]["material"] == "SC 4330"
    assert tela["imagem_pontos"] == "dureza_pin.png" and tela["tem_imagem_pontos"] is True
    assert [d["codigo"] for d in tela["durometros"]] == ["DUR-01"]
    assert [a["id"] for a in tela["aprovadores"]] == [gerente]

    r = qualidade.post(f"/api/relatorios/dureza/{lote.id}", json=_dureza(gerente, gerente, "36,0", "35,5", "36", "", "34"),
                       headers={"X-CSRF-Token": csrf})  # fmt: skip
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "APROVADO" and r.json()["avancou"] is True and r.json()["nc"] is None

    registro = _ultimo(db, Registro, lote.id, "dureza")
    assert registro.status == "aprovado" and registro.responsavel == "Beltrano Gerente" and registro.usuario_id == gerente
    assert registro.dados["leituras"] == [{"cp": "OP900001-DUR1", "peca": "", "valores": [36.0, 35.5, 36.0, 34.0],
                                           "status": "APROVADO"}]  # fmt: skip
    assert registro.dados["data_aprovacao"] == "25/11/2026" and "assinatura_executado" not in registro.dados
    anexo = _ultimo(db, Anexo, lote.id, "dureza")
    assert anexo.nome == "3-RIP-35-Dureza-OP900001-PIN.pdf" and anexo.arquivo.startswith(f"lotes/{lote.id}/anexos/")
    texto = _texto_pdf(pasta_arquivos, anexo)
    for esperado in ("RELATÓRIO DE ENSAIO DE DUREZA ROCKWELL C", "FOR-DUR-RIP-35", "DUR-2026-900001", "36,0", "APROVADO",
                     "Especificado 30 a 39 HRc", "COD.DUR-01", "Beltrano Gerente", "IS.8.5-06-8 Rev.00"):  # fmt: skip
        assert esperado in texto, esperado
    db.expire_all()
    assert db.get(Lote, lote.id).etapa == fluxo.INDICE["lab_ext"]
    assert "Relatório de Dureza gerado pelo sistema (RIP-35) - APROVADO" in db.scalars(
        select(Evento.texto).where(Evento.lote_id == lote.id)
    ).all()


def test_dureza_reprovada_abre_nc_e_retrabalho_aprovado_encerra(db, base, como):
    lote = lote_exemplo(db, **LOTE_PIN)
    _aprovados(db, lote, "receb_mp", "trat_termico")
    qualidade, csrf = como(modulos=["qualidade"], pode_aprovar=True, login="gerente")
    gerente = _id(db, "gerente")
    cab = {"X-CSRF-Token": csrf}

    r = qualidade.post(f"/api/relatorios/dureza/{lote.id}", json=_dureza(gerente, gerente, "36", "41,0"), headers=cab)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "REPROVADO" and r.json()["nc"].startswith("NC-")
    nc = _ultimo(db, NaoConformidade, lote.id, "dureza")
    assert nc.status == "aberta" and "30-39 HRc" in nc.descricao
    assert db.get(Lote, lote.id).etapa == fluxo.INDICE["dureza"]  # reprovado não avança

    r = qualidade.post(f"/api/relatorios/dureza/{lote.id}", json=_dureza(gerente, gerente, "36", "37"), headers=cab)
    assert r.json()["status"] == "APROVADO"
    nc = _ultimo(db, NaoConformidade, lote.id, "dureza")
    assert nc.status == "encerrada" and nc.disposicao == "retrabalho"


def test_dureza_validacoes(db, base, como):
    lote = lote_exemplo(db, **LOTE_PIN)
    qualidade, csrf = como(modulos=["qualidade"], pode_aprovar=True, login="gerente")
    _, _ = como(modulos=["qualidade"], login="inspetor")
    gerente, inspetor, admin = _id(db, "gerente"), _id(db, "inspetor"), _id(db, "admin")
    cab = {"X-CSRF-Token": csrf}
    url = f"/api/relatorios/dureza/{lote.id}"

    casos = [
        (_dureza(inspetor, gerente, "", ""), "pelo menos uma leitura"),
        (_dureza(inspetor, gerente, "abc"), "use números"),
        (_dureza(inspetor, gerente, "360"), "fora da escala"),
        (_dureza(inspetor, gerente, "36", equipamento_codigo=""), "durômetro"),
        (_dureza(inspetor, inspetor, "36"), "Aprovado por"),  # inspetor não pode aprovar
        (_dureza(inspetor, admin, "36"), "Aprovado por"),  # administrador também não, sem "pode aprovar"
        (_dureza(0, gerente, "36"), "executou"),
    ]
    for corpo, trecho in casos:
        r = qualidade.post(url, json=corpo, headers=cab)
        assert r.status_code == 422 and trecho in r.json()["detail"], (trecho, r.text)

    db.delete(db.get(EspecificacaoTipo, "PIN"))
    db.commit()
    r = qualidade.get(url)
    assert r.status_code == 422 and "especificação de dureza" in r.json()["detail"]  # nunca inventar o limite
    assert db.scalar(select(Registro).where(Registro.etapa == "dureza")) is None


def test_rip35_traz_a_amostra_de_10_por_cento_do_lote(db, base, como, pasta_arquivos):
    """Linhas prontas = 10% das peças do LOTE (a quantidade liberada), arredondado para cima; nunca a da OP."""
    lote = lote_exemplo(db, **LOTE_PIN)  # 72 peças no lote
    db.add(OrdemProducao(op="900001", cliente="CLIENTE EXEMPLO", tipo="PIN", qt_lote=105))  # a OP tem mais peças
    db.commit()
    qualidade, csrf = como(modulos=["qualidade"], pode_aprovar=True, login="gerente")
    gerente = _id(db, "gerente")
    url = f"/api/relatorios/dureza/{lote.id}"
    assert qualidade.get(url).json()["amostra"] == {"qtd": 72, "base": "lote", "linhas": 8, "limite": 200}

    for qtd, linhas in ((50, 5), (40, 4), (41, 5), (1, 1), (9, 1), (2500, 200)):  # 50 liberadas de uma OP de 105: 5
        db.get(Lote, lote.id).qtd = qtd
        db.commit()
        assert qualidade.get(url).json()["amostra"] == {"qtd": qtd, "base": "lote", "linhas": linhas, "limite": 200}, qtd
    db.get(Lote, lote.id).qtd = 0  # lote antigo sem quantidade: só então vale a da OP
    db.commit()
    assert qualidade.get(url).json()["amostra"] == {"qtd": 105, "base": "op", "linhas": 11, "limite": 200}
    db.get(Lote, lote.id).qtd = 72
    db.commit()

    leituras = [{"cp": f"OP900001-DUR{i}", "valores": ["35", "36"]} for i in range(1, 61)]  # mais que as 50 de antes
    r = qualidade.post(url, json=_dureza(gerente, gerente) | {"leituras": leituras}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    texto = _texto_pdf(pasta_arquivos, _ultimo(db, Anexo, lote.id, "dureza"))
    assert "60 CP(s) / 120 pontos" in texto and "OP900001-DUR60" in texto and "Pág. 2/" in texto
    r = qualidade.post(url, json=_dureza(gerente, gerente) | {"leituras": leituras * 4}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 422  # acima do limite de 200 linhas

def _folha_lida() -> FolhaLida:
    """O que a IA devolveria para uma folha com 2 peças, uma delas com um número e o nº da peça ilegíveis."""
    def c(valor: str, duvida: bool = False) -> CelulaLida:
        return CelulaLida(valor=valor, duvida=duvida)

    return FolhaLida(e_tabela_de_dureza=True, observacao="Foto um pouco torta.", linhas=[
        LinhaLida(num_peca=c("17"), leituras=[c("36"), c("35"), c("36"), c("37"), c("36")]),
        LinhaLida(num_peca=c("", True), leituras=[c("35"), c("", True), c("36"), c("36"), c("36")]),
    ])  # fmt: skip


def test_rip35_le_a_foto_da_folha_e_guarda_a_foto_como_anexo_interno(db, base, como, pasta_arquivos, monkeypatch):
    lote = lote_exemplo(db, **LOTE_PIN)
    _aprovados(db, lote, "receb_mp", "trat_termico")
    qualidade, csrf = como(modulos=["qualidade"], pode_aprovar=True, login="gerente")
    gerente, cab = _id(db, "gerente"), {"X-CSRF-Token": csrf}
    url = f"/api/relatorios/dureza/{lote.id}"
    folha = {"arquivo": ("folha.jpg", _jpg(), "image/jpeg")}

    monkeypatch.setattr(config(), "anthropic_api_key", "")  # sem chave: leitura desligada
    assert qualidade.get(url).json()["leitura_foto"] is False
    r = qualidade.post(f"{url}/ler-foto", files=folha, headers=cab)
    assert r.status_code == 503 and "à mão" in r.json()["detail"]

    monkeypatch.setattr(config(), "anthropic_api_key", "chave-de-teste")
    enviadas = []
    monkeypatch.setattr(leitura_foto, "chamar_ia", lambda imagens: enviadas.append(imagens) or _folha_lida())
    assert qualidade.get(url).json()["leitura_foto"] is True
    r = qualidade.post(f"{url}/ler-foto", files=folha, headers=cab)
    assert r.status_code == 200, r.text
    lido = r.json()
    assert lido["linhas"][0] == {"peca": "17", "peca_nao_lida": False, "valores": ["36", "35", "36", "37", "36"],
                                 "nao_lidos": [False] * 5}  # fmt: skip
    assert lido["linhas"][1]["peca_nao_lida"] is True and lido["linhas"][1]["nao_lidos"] == [False, True, False, False, False]
    assert lido["nao_lidos"] == 2 and lido["aviso"] == "Foto um pouco torta."
    assert len(enviadas) == 1 and enviadas[0][0][:2] == b"\xff\xd8"  # vai como JPEG
    foto = lido["foto"]
    assert foto["nome"] == "folha.jpg" and foto["arquivo"].startswith(f"lotes/{lote.id}/fotos_dureza/")
    assert (pasta_arquivos / foto["arquivo"]).is_file()
    db.expire_all()
    auditoria = db.scalar(select(Auditoria).where(Auditoria.acao == "LER_FOTO"))
    assert auditoria.lote_id == lote.id and auditoria.detalhes["nao_lidos"] == 2 and auditoria.detalhes["linhas"] == 2
    assert _ultimo(db, Registro, lote.id, "dureza") is None  # ler a foto não grava nada no lote

    leituras = [{"cp": "", "peca": "17", "valores": lido["linhas"][0]["valores"]},
                {"cp": "", "peca": "21", "valores": ["35", "36", "36", "36", "36"]}]  # fmt: skip
    r = qualidade.post(url, json=_dureza(gerente, gerente) | {"leituras": leituras, "fotos": [foto, foto]}, headers=cab)
    assert r.status_code == 200, r.text
    registro = _ultimo(db, Registro, lote.id, "dureza")
    assert [(item["cp"], item["peca"]) for item in registro.dados["leituras"]] == [("OP900001-DUR1", "17"), ("OP900001-DUR2", "21")]
    anexos = db.scalars(select(Anexo).where(Anexo.lote_id == lote.id, Anexo.etapa == "dureza").order_by(Anexo.id)).all()
    assert [(a.nome, a.apenas_registro) for a in anexos] == [("3-RIP-35-Dureza-OP900001-PIN.pdf", False),
                                                             ("Foto do RIP-35 em papel - folha.jpg", True)]  # fmt: skip
    assert anexos[1].arquivo == foto["arquivo"]
    with pymupdf.open(stream=(pasta_arquivos / anexos[0].arquivo).read_bytes(), filetype="pdf") as doc:
        palavras = doc[0].get_text("words")
    cabecalho = next(p for p in palavras if p[4] == "Peça" and any(q[4] == "Nº" and abs(q[1] - p[1]) < 2 for q in palavras))
    coluna = [p[4] for p in palavras if p[0] >= cabecalho[0] - 15 and p[2] <= cabecalho[2] + 15 and p[1] > cabecalho[3]]
    assert coluna[:2] == ["17", "21"]

    for arquivo in (f"lotes/{lote.id + 1}/fotos_dureza/x.jpg", f"lotes/{lote.id}/fotos_dureza/../anexos/x.pdf",
                    f"lotes/{lote.id}/fotos_dureza/nao-existe.jpg", anexos[0].arquivo):  # fmt: skip
        r = qualidade.post(url, json=_dureza(gerente, gerente, "36") | {"fotos": [{"arquivo": arquivo}]}, headers=cab)
        assert r.status_code == 422 and "foto da folha" in r.json()["detail"], arquivo


def test_rip35_foto_que_nao_e_a_tabela_e_falha_da_leitura(db, base, como, monkeypatch):
    lote = lote_exemplo(db, **LOTE_PIN)
    qualidade, csrf = como(modulos=["qualidade"], login="inspetor")
    url = f"/api/relatorios/dureza/{lote.id}/ler-foto"
    folha = {"arquivo": ("folha.png", _png(), "image/png")}
    monkeypatch.setattr(config(), "anthropic_api_key", "chave-de-teste")

    monkeypatch.setattr(leitura_foto, "chamar_ia", lambda _: FolhaLida(e_tabela_de_dureza=False, linhas=[], observacao=""))
    r = qualidade.post(url, files=folha, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and r.json()["linhas"] == [] and "não parece ser a tabela" in r.json()["aviso"]

    def demora(_):
        raise ErroLeitura("A leitura demorou demais. Tente de novo ou preencha à mão.", 504)

    monkeypatch.setattr(leitura_foto, "chamar_ia", demora)
    r = qualidade.post(url, files=folha, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 504 and "demorou demais" in r.json()["detail"]
    planilha = {"arquivo": ("folha.xlsx", b"PK", "application/octet-stream")}
    r = qualidade.post(url, files=planilha, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 422


def test_rip35_do_ark_usa_a_faixa_do_ark_e_sai_sem_figura(db, base, como):
    """Dureza é opcional no ARK: o RIP-35 sai com a faixa do ARK; sem a imagem dos pontos no servidor, sem a figura."""
    ark = lote_exemplo(db, numero="26-4-900002", op="900002", tipo="ARK")
    qualidade, csrf = como(modulos=["qualidade"], pode_aprovar=True, login="gerente")
    gerente = _id(db, "gerente")
    tela = qualidade.get(f"/api/relatorios/dureza/{ark.id}")
    assert tela.status_code == 200, tela.text
    assert tela.json()["info"]["especificacao"] == "43 a 48 HRc" and tela.json()["info"]["material"] == "H11 Modified"
    assert tela.json()["imagem_pontos"] == "dureza_ark.png" and tela.json()["tem_imagem_pontos"] is False

    cab = {"X-CSRF-Token": csrf}
    r = qualidade.post(f"/api/relatorios/dureza/{ark.id}", json=_dureza(gerente, gerente, "44", "45", "45", "44", "45"), headers=cab)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "APROVADO" and r.json()["avancou"] is False
    assert _ultimo(db, Anexo, ark.id, "dureza").nome == "3-RIP-35-Dureza-OP900002-ARK.pdf"
    r = qualidade.post(f"/api/relatorios/dureza/{ark.id}", json=_dureza(gerente, gerente, "36"), headers=cab)
    assert r.json()["status"] == "REPROVADO"  # 36 serve para PIN/BOX, não para o ARK


def test_item_e_desenho_do_cabecalho_sem_dimensoes():
    assert item_sem_dimensoes("ARK99XY99 -51,5x26,6x120mm  ABCDEF99XY99 R0") == "ARK99XY99"
    assert item_sem_dimensoes("CHAVETA EXEMPLO ARK 32-36 51x26,5x120mm DES ABC1234 REV 0") == "CHAVETA EXEMPLO ARK 32-36"
    assert item_sem_dimensoes("ABC-DE-XYZ1-PIN-18-22 REV 0") == "ABC-DE-XYZ1-PIN-18-22 REV 0"  # sem dimensões: inteiro
    assert item_sem_dimensoes("") == ""

    assert codigo_do_desenho("CHAVETA EXEMPLO ARK 99XY-99XY-99 51,5x26,6x120mm DES ABCDEF99XY99 REV 0") == "ABCDEF99XY99 REV 0"
    assert codigo_do_desenho("INSTR. CONTROLE TRAVAMENTO DES ABC-DE-XYZ1-PIN-18-22 REV 0") == "ABC-DE-XYZ1-PIN-18-22 REV 0"
    assert codigo_do_desenho("INSTR. CONTROLE TRAVAMENTO ABC-DE-XYZ-BOX-18-22 REV 0") == "ABC-DE-XYZ-BOX-18-22 REV 0"
    assert codigo_do_desenho("DESENHO SEM CODIGO") == "DESENHO SEM CODIGO"  # sem código reconhecível: o nome inteiro


def test_rip35_do_ark_com_figura_item_desenho_cargo_e_equipamento_comprido(db, base, como, pasta_arquivos):
    """Cabeçalho só com o item (sem dimensões) e o código do desenho; cargo do cadastro; equipamento quebra a linha."""
    db.add(OrdemProducao(op="900002", cliente="CLIENTE EXEMPLO", tipo="ARK",
                         descricao="INSTR. CONTROLE TRAVAMENTO ARK99XY99 -51,5x26,6x120mm  ABCDEF99XY99 R0"))  # fmt: skip
    db.add(Equipamento(codigo="DUR-02", descricao="Durômetro de bancada com penetrador de diamante e mesa para peças longas",
                       marca="Marca Exemplo de Nome Bem Comprido", certificado="0002/26-EXEMPLO-DE-CERTIFICADO",
                       data_calibracao=date(2026, 1, 10), validade_calibracao=date(2027, 1, 10)))  # fmt: skip
    db.commit()
    desenhos = pasta_arquivos / "recursos" / "desenhos"
    desenhos.mkdir(parents=True)
    (desenhos / "ORIGEM - 7654321 CHAVETA EXEMPLO ARK 99XY-99XY-99 51,5x26,6x120mm DES ABCDEF99XY99 REV 0.pdf").write_bytes(b"%PDF")
    (pasta_arquivos / "recursos" / "relatorios" / "dureza_ark.png").write_bytes(_png((10, 200, 10)))
    ark = lote_exemplo(db, numero="26-4-900002", op="900002", tipo="ARK", coditem="7654321")
    qualidade, csrf = como(modulos=["qualidade"], pode_aprovar=True, login="gerente", nome="Beltrano Garantia")
    gerente = _id(db, "gerente")
    db.get(Usuario, gerente).cargo = "Garantia da Qualidade"
    db.commit()

    tela = qualidade.get(f"/api/relatorios/dureza/{ark.id}").json()
    assert tela["info"]["nome_peca"] == "ARK99XY99" and tela["info"]["desenho"] == "ABCDEF99XY99 REV 0"
    assert tela["tem_imagem_pontos"] is True
    corpo = _dureza(gerente, gerente, "44", "45", equipamento_codigo="DUR-02")
    r = qualidade.post(f"/api/relatorios/dureza/{ark.id}", json=corpo, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    assert _ultimo(db, Registro, ark.id, "dureza").dados["aprovado_por_cargo"] == "Garantia da Qualidade"

    conteudo = (pasta_arquivos / _ultimo(db, Anexo, ark.id, "dureza").arquivo).read_bytes()
    with pymupdf.open(stream=conteudo, filetype="pdf") as doc:
        texto = "\n".join(pagina.get_text() for pagina in doc)
        assert sum(len(pagina.get_images()) for pagina in doc) >= 1  # Figura 1 (pontos de medição do ARK)
        direita = max(palavra[2] for pagina in doc for palavra in pagina.get_text("words"))
        largura = doc[0].rect.width
    corrido = " ".join(texto.split())  # o equipamento quebra a linha onde a fonte do servidor mandar
    for esperado in ("ARK99XY99", "ABCDEF99XY99 REV 0", "Garantia da Qualidade", "vencimento em 10/01/2027."):
        assert esperado in corrido, esperado
    assert "51,5x26,6x120mm" not in texto and "Gerente da Qualidade" not in texto
    assert direita <= largura - 10 * 72 / 25.4, "texto passou da margem direita da página"


def test_dureza_e_visual_so_para_a_qualidade(db, base, como):
    lote = lote_exemplo(db, **LOTE_PIN)
    tt, csrf = como(modulos=["producao_tt", "pcp"])
    cab = {"X-CSRF-Token": csrf}
    assert tt.get(f"/api/relatorios/dureza/{lote.id}").status_code == 403
    assert tt.post(f"/api/relatorios/dureza/{lote.id}", json=_dureza(1, 1, "36"), headers=cab).status_code == 403
    assert tt.post(f"/api/relatorios/dureza/{lote.id}/ler-foto", files={"arquivo": ("folha.jpg", _jpg(), "image/jpeg")},
                   headers=cab).status_code == 403  # fmt: skip
    assert tt.get(f"/api/relatorios/visual/{lote.id}").status_code == 403
    assert tt.post(f"/api/relatorios/visual/{lote.id}", data={"qtd": "1"}, headers=cab).status_code == 403
    usinagem, csrf = como(modulos=["producao_usinagem"], login="usinagem")
    assert usinagem.get(f"/api/relatorios/tt?lote={lote.id}").status_code == 403
    assert usinagem.post("/api/relatorios/tt", data={"lote_id": str(lote.id)}, headers={"X-CSRF-Token": csrf}).status_code == 403


# ---------------------------------------------------------------- tratamento térmico


def _tt(tecnico: int, aprovador: int, **extra) -> dict:
    return {"forno_tempera_codigo": "FO-01", "forno_revenimento_codigo": "FO-02", "pre_temp": "800", "pre_tempo": "25",
            "z2_temp": "870", "z2_tempo": "25", "z3_temp": "870", "z3_tempo": "25", "resfr_z3": "Óleo",
            "rev1_temp": "520", "rev1_tempo": "180", "rev2_temp": "", "rev2_tempo": "", "dur_pos_min": "35,0",
            "dur_pos_max": "37", "tecnico": str(tecnico), "aprovado_por": str(aprovador), "data_tratamento": "2026-11-23",
            "data_registro": "2026-11-24", "obs": "Teste"} | extra  # fmt: skip


def test_tt_pela_carga_replica_em_todos_os_lotes_e_conclui_a_carga(db, base, como, pasta_arquivos):
    a = lote_exemplo(db, **LOTE_PIN)
    b = lote_exemplo(db, numero="26-4-900002", op="900002", tipo="BOX", qtd=40)
    _aprovados(db, a, "receb_mp")
    _aprovados(db, b, "receb_mp")
    tecnico, csrf = como(modulos=["producao_tt"], login="tecnico", nome="Fulano Técnico")
    como(modulos=["qualidade"], pode_aprovar=True, login="gerente", nome="Beltrano Gerente")
    id_tecnico, gerente = _id(db, "tecnico"), _id(db, "gerente")
    cab = {"X-CSRF-Token": csrf}
    carga = tecnico.post("/api/cargas-tt", json={"forno_tempera_codigo": "FO-01", "forno_revenimento_codigo": "FO-02",
                                                 "lote_ids": [a.id, b.id]}, headers=cab).json()  # fmt: skip

    tela = tecnico.get(f"/api/relatorios/tt?carga={carga['id']}")
    assert tela.status_code == 200, tela.text
    tela = tela.json()
    assert tela["lote"]["id"] == a.id and [lo["id"] for lo in tela["lotes_carga"]] == [a.id, b.id]
    assert tela["info"]["esp_dureza"] == "30/39 HRc" and tela["forno_tempera_padrao"] == "FO-01"
    assert id_tecnico in [t["id"] for t in tela["tecnicos"]]
    assert tecnico.get(f"/api/relatorios/tt?lote={a.id}").json()["carga_do_lote"]["id"] == carga["id"]

    r = tecnico.post("/api/relatorios/tt", data=_tt(id_tecnico, gerente, lote_id=str(a.id), carga_id=str(carga["id"])),
                     files={"grafico_tempera": ("tempera.png", _png(), "image/png"),
                            "grafico_rev1": ("rev1.png", _png(), "image/png")}, headers=cab)  # fmt: skip
    assert r.status_code == 200, r.text
    assert r.json()["lotes"] == 2 and r.json()["avancados"] == 2

    db.expire_all()
    for lote in (a, b):
        registro = _ultimo(db, Registro, lote.id, "trat_termico")
        assert registro.status == "aprovado" and registro.dados["carga_numero"] == carga["numero"]
        assert registro.dados["dureza_pos_tt"]["status"] == "APROVADO"
        assert [x["op"] for x in registro.dados["lotes_incluidos"]] == ["900001", "900002"]
        anexo = _ultimo(db, Anexo, lote.id, "trat_termico")
        assert anexo.nome == "2-Relatorio-TT-OP900001-PIN.pdf"
        texto = _texto_pdf(pasta_arquivos, anexo)
        for esperado in ("RELATÓRIO DE TRATAMENTO TÉRMICO", "FOR-TT-IS.8.5-06-8", "IT-TT-IS 8.5-06", "900002", "Fulano Técnico",
                         "Forno: Forno de Têmpera - Marca Exemplo (FO-01)", "35,0 HRc", "1º Revenimento"):  # fmt: skip
            assert esperado in texto, esperado
        assert "2º Revenimento" not in texto
        assert "Gerente da Qualidade" not in texto and "Teste" in texto  # cargo do cadastro de quem aprovou
    assert db.get(Lote, a.id).etapa == fluxo.INDICE["dureza"]
    assert db.get(Lote, b.id).etapa == fluxo.INDICE["dureza"]
    concluida = db.get(CargaTT, carga["id"])
    assert concluida.status == "concluida" and concluida.data_fim is not None
    assert db.get(Anexo, concluida.relatorio_anexo_id).lote_id == a.id
    assert registro.dados["graficos"]["tempera"].startswith(f"lotes/{a.id}/graficos_tt/")


def test_tt_sem_carga_com_lote_extra_e_validacoes(db, base, como):
    a = lote_exemplo(db, **LOTE_PIN)
    b = lote_exemplo(db, numero="26-4-900002", op="900002")
    qualidade, csrf = como(modulos=["qualidade"], pode_aprovar=True, login="gerente")
    gerente = _id(db, "gerente")
    cab = {"X-CSRF-Token": csrf}

    for extra, trecho in [
        ({"dur_pos_max": ""}, "dureza máxima"),
        ({"dur_pos_min": "38", "dur_pos_max": "36"}, "mínima não pode ser maior"),
        ({"forno_tempera_codigo": "FO-99"}, "forno de têmpera"),
        ({"aprovado_por": str(_id(db, "admin"))}, "Aprovado por"),
        ({"data_registro": "24/11/2026"}, "data inválida"),
    ]:
        r = qualidade.post("/api/relatorios/tt", data=_tt(gerente, gerente, lote_id=str(a.id)) | extra, headers=cab)
        assert r.status_code == 422 and trecho in r.json()["detail"], (trecho, r.text)

    corpo = _tt(gerente, gerente, lote_id=str(a.id), lotes_extras=f"{b.id},{a.id}", dur_pos_min="", dur_pos_max="",
                rev2_temp="500", rev2_tempo="180")  # fmt: skip
    r = qualidade.post("/api/relatorios/tt", data=corpo, headers=cab)
    assert r.status_code == 200, r.text
    assert r.json()["lotes"] == 2 and r.json()["avancados"] == 0  # cursores não estavam no TT
    registro = _ultimo(db, Registro, b.id, "trat_termico")
    assert registro.dados["origem"] == "Relatório pelo sistema" and "dureza_pos_tt" not in registro.dados
    assert len(registro.dados["revenimento"]) == 2

    db.delete(db.get(EspecificacaoTipo, "PIN"))
    db.commit()
    assert qualidade.get(f"/api/relatorios/tt?lote={a.id}").status_code == 422


# ---------------------------------------------------------------- inspeção visual e laser


def test_formato_do_laser_e_lote_completo():
    formato = "{ano}T{tri}-C{corrida}-L{lote}-{seq:03d}"
    assert formatar_laser(formato, ano="2026", tri="4", corrida="M999/26", lote="900001", seq=7) == "2026T4-CM999/26-L900001-007"
    assert formatar_laser("{ano.__class__}-{x}", ano="2026") == "{ano.__class__}-{x}"  # não executa nada do formato
    assert formato_legivel(formato) == "<ano>T<tri>-C<corrida>-L<lote>-<seq>"
    assert lote_completo("26-4-900001", 2027, 1) == "26-4-900001"
    assert lote_completo("900001", 2026, 4) == "26-4-900001"


def _visual(executor: int, aprovador: int, **extra) -> dict:
    return {"resultado": "APROVADO", "qtd": "72", "rnc": "N/A", "obs1": "Aspecto geral ok", "obs2": "", "obs3": "Laser ok",
            "ano": "2026", "tri": "4", "executado_por": str(executor), "aprovado_por": str(aprovador),
            "data": "2026-11-24"} | extra  # fmt: skip


def test_visual_aprovado_com_fotos_e_codigo_laser(db, base, como, pasta_arquivos):
    lote = lote_exemplo(db, **LOTE_PIN)
    qualidade, csrf = como(modulos=["qualidade"], pode_aprovar=True, login="gerente", nome="Beltrano Gerente")
    gerente = _id(db, "gerente")

    tela = qualidade.get(f"/api/relatorios/visual/{lote.id}").json()
    assert tela["laser"] == {"formato": "{ano}T{tri}-C{corrida}-L{lote}-{seq:03d}", "corrida": "M999/26", "lote": "26-4-900001"}
    assert "Fosfato de Manganês" in tela["info"]["obs1"] and "M6x1x10mm" in tela["info"]["obs2"]
    assert tela["pode_usar_como_esta"] is True

    r = qualidade.post(f"/api/relatorios/visual/{lote.id}", data=_visual(gerente, gerente),
                       files={"foto_geral": ("geral.png", _png(), "image/png"), "foto_laser": ("laser.jpg", _jpg(), "image/jpeg")},
                       headers={"X-CSRF-Token": csrf})  # fmt: skip
    assert r.status_code == 200, r.text
    registro = _ultimo(db, Registro, lote.id, "visual")
    assert registro.status == "aprovado"
    assert registro.dados["laser_primeiro"] == "2026T4-CM999/26-L26-4-900001-001"
    assert registro.dados["laser_ultimo"] == "2026T4-CM999/26-L26-4-900001-072"
    assert set(registro.dados["fotos"]) == {"geral", "laser"}
    texto = _texto_pdf(pasta_arquivos, _ultimo(db, Anexo, lote.id, "visual"))
    for esperado in ("RELATÓRIO DE INSPEÇÃO VISUAL E MARCAÇÃO A LASER", "FOR-VIS-IS-100.1-F", "IS.100.1-F Rev.00",
                     "RESULTADO DA INSPEÇÃO: APROVADO", "Aspecto geral ok", "[Imagem a anexar]", "VIS-2026-900001"):  # fmt: skip
        assert esperado in texto, esperado
    assert "Gerente da Qualidade" not in texto and "Controle de Qualidade" not in texto  # cargos do cadastro ("Teste")


def _jpg() -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", (40, 40), (10, 10, 10)).save(saida, format="JPEG")
    return saida.getvalue()


def test_visual_reprovado_e_usar_como_esta(db, base, como):
    lote = lote_exemplo(db, **LOTE_PIN)
    inspetor, csrf_insp = como(modulos=["qualidade"], login="inspetor")
    gerente_cli, csrf_ger = como(modulos=["qualidade"], pode_aprovar=True, login="gerente")
    id_insp, gerente = _id(db, "inspetor"), _id(db, "gerente")
    url = f"/api/relatorios/visual/{lote.id}"

    r = inspetor.post(url, data=_visual(id_insp, gerente, resultado="REPROVADO", rnc="NC-2026-050"), headers={"X-CSRF-Token": csrf_insp})
    assert r.status_code == 200, r.text
    nc = _ultimo(db, NaoConformidade, lote.id, "visual")
    assert nc.status == "aberta" and nc.descricao == "Inspeção visual reprovada (RNC NC-2026-050)"

    uce = _visual(id_insp, gerente, resultado="USAR COMO ESTÁ (RNC)")
    r = inspetor.post(url, data=uce, headers={"X-CSRF-Token": csrf_insp})
    assert r.status_code == 403  # só quem pode aprovar
    r = gerente_cli.post(url, data=uce, headers={"X-CSRF-Token": csrf_ger})
    assert r.status_code == 422 and "RNC" in r.json()["detail"]
    r = gerente_cli.post(url, data=uce | {"rnc": nc.numero}, headers={"X-CSRF-Token": csrf_ger})
    assert r.status_code == 200, r.text
    assert _ultimo(db, Registro, lote.id, "visual").status == "aprovado"
    nc = _ultimo(db, NaoConformidade, lote.id, "visual")
    assert nc.status == "encerrada" and nc.disposicao == "uso_como_esta" and nc.numero in nc.justificativa

    for extra, trecho in [({"qtd": "0"}, "quantidade"), ({"tri": "5"}, "Trimestre"), ({"resultado": "TALVEZ"}, "Resultado")]:
        r = inspetor.post(url, data=_visual(id_insp, gerente) | extra, headers={"X-CSRF-Token": csrf_insp})
        assert r.status_code == 422 and trecho in r.json()["detail"], (trecho, r.text)
