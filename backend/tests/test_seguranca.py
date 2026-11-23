import pytest
from fastapi import HTTPException

from app.seguranca import celula_segura, diferencas, hash_senha, limpar_texto, validar_senha_nova, verificar_senha


def test_senha_confere_e_nao_fica_legivel():
    gravado = hash_senha("Uma-senha-de-teste-123")
    assert "Uma-senha" not in gravado
    assert gravado.startswith("$argon2id$")
    assert verificar_senha(gravado, "Uma-senha-de-teste-123")
    assert not verificar_senha(gravado, "outra-senha-456")


def test_login_inexistente_nunca_confere():
    assert not verificar_senha(None, "qualquer-coisa-1")
    assert not verificar_senha(None, "senha-que-nao-existe")  # nem com o texto do hash falso


def test_hash_e_texto_puro_do_sistema_antigo_nao_valem():
    """O sistema antigo aceitava pbkdf2/scrypt e até senha em texto puro. No novo, nada disso entra."""
    assert not verificar_senha("pbkdf2:sha256:600000$abc$def", "qualquer")
    assert not verificar_senha("minhasenha123", "minhasenha123")


@pytest.mark.parametrize("senha", ["curta1", "somenteletrasaqui", "12345678901234", "fulano.tal-2026"])
def test_senhas_fracas_sao_recusadas(senha):
    with pytest.raises(HTTPException):
        validar_senha_nova(senha, "fulano.tal")


def test_senha_boa_passa():
    validar_senha_nova("Chaveta-Forno-2026", "fulano.tal")


def test_texto_perde_caracteres_de_controle_mas_mantem_quebra_de_linha():
    assert limpar_texto("trinca\x0b na\x00 peça\nlinha 2\tfim") == "trinca na peça\nlinha 2\tfim"
    assert limpar_texto(None) is None
    assert limpar_texto(42) == 42


def test_celula_de_planilha_nao_vira_formula():
    assert celula_segura('=HYPERLINK("http://x")') == "'=HYPERLINK(\"http://x\")"
    assert celula_segura("- conferir a cota") == "- conferir a cota"
    assert celula_segura(3.5) == 3.5


def test_diferencas_so_traz_o_que_mudou():
    assert diferencas({"a": 1, "b": 2}, {"a": 1, "b": 3}) == {"b": [2, 3]}
    assert diferencas({"a": 1}, {"a": 1}) == {}
