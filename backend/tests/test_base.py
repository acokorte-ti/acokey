"""Peças comuns aos módulos: numeração, arquivos, NC automática, parâmetros e criação de lote."""
import io

import pytest
from conftest import lote_exemplo
from fastapi import HTTPException, UploadFile

from app import arquivos, parametros
from app.models import NaoConformidade, Registro
from app.nc import abrir_nc_automatica, fechar_nc_se_aberta
from app.numeracao import proximo_numero


def test_numeracao_segue_e_continua_dos_numeros_migrados(db):
    lote = lote_exemplo(db)
    db.add(NaoConformidade(numero="NC-2026-007", lote_id=lote.id))  # veio do sistema antigo
    db.commit()
    assert proximo_numero(db, "NC", 2026) == "NC-2026-008"
    assert proximo_numero(db, "NC", 2026) == "NC-2026-009"
    assert proximo_numero(db, "NC", 2027) == "NC-2027-001"
    assert proximo_numero(db, "TT", 2026) == "TT-2026-001"
    with pytest.raises(ValueError):
        proximo_numero(db, "XX", 2026)


def test_nome_de_arquivo_seguro():
    assert arquivos.nome_seguro("Relatório Dureza (OP 1).PDF") == "Relatorio_Dureza_OP_1.pdf"
    assert arquivos.nome_seguro("../../etc/passwd") == "passwd"
    assert arquivos.nome_seguro("") == "arquivo"


def _upload(nome: str, conteudo: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(conteudo), filename=nome)


def test_envio_de_arquivo_confere_tipo_tamanho_e_conteudo(pasta_arquivos):
    relativo, original = arquivos.salvar_upload(_upload("Certificado MP.pdf", b"%PDF-1.4 x"), "lotes/1/anexos")
    assert original == "Certificado MP.pdf" and relativo.startswith("lotes/1/anexos/") and relativo.endswith("Certificado_MP.pdf")
    assert (pasta_arquivos / relativo).read_bytes() == b"%PDF-1.4 x"
    assert arquivos.caminho_seguro(relativo) is not None
    assert arquivos.caminho_seguro("../fora.txt") is None
    for nome, conteudo, status in [
        ("virus.exe", b"MZ", 422),  # extensão não aceita
        ("falso.pdf", b"MZ\x90\x00", 422),  # diz que é PDF, mas não é
        ("vazio.pdf", b"", 422),
        ("grande.pdf", b"%PDF-" + b"0" * (1024 * 1024 + 1), 413),
    ]:
        with pytest.raises(HTTPException) as erro:
            arquivos.salvar_upload(_upload(nome, conteudo), "lotes/1/anexos", limite_mb=1)
        assert erro.value.status_code == status, nome
    with pytest.raises(ValueError):
        arquivos.salvar_bytes(b"x", "../fora", "a.pdf")


def test_nc_abre_na_reprovacao_e_fecha_no_retrabalho_aprovado(db):
    lote = lote_exemplo(db)
    reprovado = Registro(lote_id=lote.id, etapa="dureza", status="reprovado")
    db.add(reprovado)
    db.flush()
    nc = abrir_nc_automatica(db, None, lote, reprovado, "Dureza fora da especificação")
    db.commit()
    assert nc.numero.startswith("NC-") and nc.status == "aberta" and nc.qtd_lote_na_abertura == 72
    assert fechar_nc_se_aberta(db, None, lote.id, "lab_ext", "tracao") is None  # outra etapa: não mexe
    fechada = fechar_nc_se_aberta(db, None, lote.id, "dureza", "")
    db.commit()
    assert fechada.id == nc.id and fechada.status == "encerrada" and fechada.disposicao == "retrabalho"


def test_parametros_tem_padrao_e_gravam(db):
    assert parametros.ler(db, "empresa_razao_social").startswith("AçoKorte")
    assert parametros.ler(db, "cliente_nome") == ""
    parametros.gravar(db, "cliente_nome", "CLIENTE EXEMPLO", "admin")
    db.commit()
    assert parametros.ler(db, "cliente_nome") == "CLIENTE EXEMPLO"
    assert parametros.todos(db)["cliente_nome"] == "CLIENTE EXEMPLO"
