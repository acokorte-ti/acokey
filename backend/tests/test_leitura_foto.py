"""Leitura da foto do RIP-35: preparo da imagem, chamada à API (com um cliente falso) e conferência do que volta.

Nenhum teste fala com a API de verdade.
"""
import io
from types import SimpleNamespace

import anthropic
import httpx2
import pymupdf
import pytest
from PIL import Image

from app import leitura_foto
from app.leitura_foto import CelulaLida, ErroLeitura, FolhaLida, LinhaLida


def _c(valor: str, duvida: bool = False) -> CelulaLida:
    return CelulaLida(valor=valor, duvida=duvida)


def _linha(peca, *valores) -> LinhaLida:
    return LinhaLida(num_peca=peca if isinstance(peca, CelulaLida) else _c(peca),
                     leituras=[v if isinstance(v, CelulaLida) else _c(v) for v in valores])  # fmt: skip


def _folha(*linhas: LinhaLida, tabela: bool = True, observacao: str = "") -> FolhaLida:
    return FolhaLida(e_tabela_de_dureza=tabela, linhas=list(linhas), observacao=observacao)


# ---------------------------------------------------------------- conferência


def test_normalizar_deixa_em_branco_e_marca_o_que_nao_leu():
    linhas = leitura_foto.normalizar(_folha(
        _linha("17", "44", "44", "45", "45", "45"),
        _linha("10", "44", _c("4?", True), "44.5", "4", "450"),  # dúvida, ponto decimal, números absurdos
        _linha(_c("2", True), "43", "44"),  # só 2 leituras: as outras 3 voltam marcadas
        _linha("", "", "", "", "", ""),  # linha vazia: some
        _linha("40 ", "abc", "44", "44", "44", "44", "99"),  # texto no lugar do número; mais de 5 leituras
        _linha("33", _c("", True), _c("", True), _c("", True), _c("", True), _c("", True)),  # tudo ilegível: fica
    ))  # fmt: skip
    assert linhas[0] == {"peca": "17", "peca_nao_lida": False, "valores": ["44", "44", "45", "45", "45"],
                         "nao_lidos": [False] * 5}  # fmt: skip
    assert linhas[1]["valores"] == ["44", "", "44,5", "", ""]
    assert linhas[1]["nao_lidos"] == [False, True, False, True, True]
    assert linhas[2]["peca"] == "" and linhas[2]["peca_nao_lida"] is True
    assert linhas[2]["valores"] == ["43", "44", "", "", ""] and linhas[2]["nao_lidos"] == [False, False, True, True, True]
    assert linhas[3]["peca"] == "40" and linhas[3]["valores"] == ["", "44", "44", "44", "44"]
    assert linhas[4]["peca"] == "33" and linhas[4]["nao_lidos"] == [True] * 5
    assert len(linhas) == 5


# ---------------------------------------------------------------- imagem


def _imagem(tamanho: tuple[int, int], formato: str = "PNG", **salvar) -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", tamanho, (240, 240, 240)).save(saida, format=formato, **salvar)
    return saida.getvalue()


def _tamanho(jpeg: bytes) -> tuple[int, int]:
    assert jpeg[:2] == b"\xff\xd8"
    with Image.open(io.BytesIO(jpeg)) as imagem:
        return imagem.size


def test_foto_grande_e_reduzida_e_foto_deitada_fica_em_pe():
    [grande] = leitura_foto.preparar_imagens(_imagem((4000, 3000)), ".png")
    assert _tamanho(grande) == (2576, 1932)

    exif = Image.Exif()
    exif[0x0112] = 6  # orientação: celular de lado
    [deitada] = leitura_foto.preparar_imagens(_imagem((300, 100), "JPEG", exif=exif), ".jpg")
    assert _tamanho(deitada) == (100, 300)


def test_pdf_vira_ate_3_paginas_e_arquivo_estragado_e_recusado():
    with pymupdf.open() as documento:
        for _ in range(4):
            documento.new_page()
        pdf = documento.tobytes()
    paginas = leitura_foto.preparar_imagens(pdf, ".pdf")
    assert len(paginas) == 3 and all(_tamanho(p)[1] <= 2576 for p in paginas)

    with pytest.raises(ErroLeitura) as erro:
        leitura_foto.preparar_imagens(b"\xff\xd8\xff\xe0 nao e uma foto", ".jpg")
    assert erro.value.status == 422


# ---------------------------------------------------------------- chamada à API (cliente falso)


class _ClienteFalso:
    def __init__(self, resposta=None, erro: Exception | None = None):
        self.resposta, self.erro, self.criado_com, self.pedido = resposta, erro, None, None
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def __call__(self, **opcoes):  # faz o papel de anthropic.Anthropic(...)
        self.criado_com = opcoes
        return self

    def _parse(self, **pedido):
        self.pedido = pedido
        if self.erro:
            raise self.erro
        return self.resposta


def _resposta(folha: FolhaLida | None, parada: str = "end_turn"):
    return SimpleNamespace(stop_reason=parada, parsed_output=folha, model="claude-opus-5-5", _request_id="req_teste")


def test_chamada_manda_as_imagens_com_o_modelo_e_o_esquema(monkeypatch):
    folha = _folha(_linha("17", "44", "44", "45", "45", "45"))
    falso = _ClienteFalso(_resposta(folha))
    monkeypatch.setattr(leitura_foto.anthropic, "Anthropic", falso)

    assert leitura_foto.chamar_ia([b"\xff\xd8um", b"\xff\xd8dois"]) is folha
    pedido = falso.pedido
    assert pedido["model"] == "claude-opus-5-5" and pedido["output_format"] is FolhaLida
    assert pedido["fallbacks"] == "default" and pedido["betas"] == ["server-side-fallback-2026-07-01"]
    assert pedido["output_config"] == {"effort": "high"} and "NÃO adivinhe" in pedido["system"]
    conteudo = pedido["messages"][0]["content"]
    assert [b["type"] for b in conteudo] == ["image", "image", "text"]
    assert conteudo[0]["source"]["media_type"] == "image/jpeg"
    assert falso.criado_com["max_retries"] == 0 and falso.criado_com["timeout"] < 120  # o nginx corta em 120 s


@pytest.mark.parametrize(
    ("resposta", "erro", "status"),
    [
        (_resposta(None, "refusal"), None, 422),
        (_resposta(None, "max_tokens"), None, 502),
        (None, anthropic.APITimeoutError(request=httpx2.Request("POST", "https://api.exemplo")), 504),
        (None, anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.exemplo")), 502),
    ],
)
def test_falhas_da_api_viram_mensagem_simples(monkeypatch, resposta, erro, status):
    monkeypatch.setattr(leitura_foto.anthropic, "Anthropic", _ClienteFalso(resposta, erro))
    with pytest.raises(ErroLeitura) as falha:
        leitura_foto.chamar_ia([b"\xff\xd8"])
    assert falha.value.status == status and "à mão" in str(falha.value)
