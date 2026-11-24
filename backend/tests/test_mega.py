"""Integração com o Mega: desligada por padrão e sem nenhum segredo no código."""
import pytest

from app import mega
from app.config import config


def test_mega_comeca_desligado():
    pronto, motivo = mega.situacao()
    assert not pronto and "desligada" in motivo


def test_testar_sem_configuracao_avisa_e_nao_conecta(monkeypatch):
    monkeypatch.setattr(config(), "mega_dsn", "")
    with pytest.raises(SystemExit, match="ainda não estão no .env"):
        mega.testar()


def test_mensagem_de_erro_nao_mostra_dados_da_conexao():
    erro = Exception("DPY-6005: cannot connect to database (CONNECTION_ID=abc). usuario/senha@host:1521/servico")
    assert mega._mensagem_publica(erro).startswith("DPY-6005")
    assert mega._mensagem_publica(Exception("senha errada em host")) == "Exception"
