"""Leitura das medições de dureza escritas à mão no RIP-35 de papel (foto do celular ou PDF digitalizado).

A tabela do papel tem, por linha: Código Peça, Num. Peça e 5 leituras HRc. A foto vai para a API da Anthropic
(modelo de IA com visão), que devolve as linhas em JSON validado. O que a IA não leu com certeza volta em branco
e marcado, para a pessoa digitar olhando o papel: o sistema nunca "chuta" um número.

A foto sai da empresa (o cabeçalho do papel tem o nome do cliente): decisão tomada com a Qualidade em 26/11/2026.
Sem ANTHROPIC_API_KEY no .env a leitura fica desligada e a tela só aceita digitação.
"""
import base64
import io
import logging
import re

import anthropic
import pymupdf
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from app.config import config

log = logging.getLogger(__name__)

MAX_LADO_PX = 2576  # maior lado que o modelo enxerga sem reduzir
MAX_BYTES_IMAGEM = 4_500_000  # a API aceita até 5 MB por imagem
MAX_PAGINAS_PDF = 3
LEITURAS_POR_LINHA = 5
HRC_PLAUSIVEL = (15.0, 75.0)  # fora disso é erro de leitura (não é a faixa da especificação)
TEMPO_LIMITE_S = 100.0  # o nginx espera 120 s pela API

INSTRUCOES = """Você transcreve tabelas de ensaio de dureza Rockwell C (HRc) preenchidas à mão em formulários \
de inspeção de uma metalúrgica. A transcrição vai para o registro oficial de qualidade, então um número errado é \
muito pior que um número em branco.

O formulário (RIP-35) tem uma tabela "Valores Encontrados - HRc" com as colunas, da esquerda para a direita: \
"Código Peça", "Num. Peça", "1", "2", "3", "4", "5" e "STATUS". Cada linha preenchida é uma peça medida; as colunas \
1 a 5 são as leituras de dureza nos 5 pontos da peça (números como 44, 45 ou 36,5).

Regras:
- Transcreva só as linhas que têm algo escrito à mão, de cima para baixo, na ordem do papel. Ignore linhas vazias, \
o cabeçalho impresso, a coluna STATUS, assinaturas, datas e rabiscos fora da tabela.
- Para cada linha devolva o número da peça (coluna "Num. Peça") e exatamente 5 leituras, na ordem das colunas 1 a 5.
- Copie o número como está escrito, com vírgula se tiver casa decimal. Não arredonde nem corrija.
- Se um algarismo estiver ambíguo (por exemplo 4 ou 9, 1 ou 7, 3 ou 8), rasurado, cortado pela foto ou fora de foco, \
NÃO adivinhe: devolva valor vazio e duvida = true. Não use o que está nas outras linhas para deduzir o valor.
- Célula em branco no papel: valor vazio e duvida = false.
- Se a imagem não for uma tabela de dureza preenchida, devolva e_tabela_de_dureza = false e nenhuma linha.
- Em observacao, escreva em português, numa frase curta, qualquer problema que a pessoa deva conferir \
(foto cortada, linha ilegível, folha de outro formulário). Deixe vazio se não houver."""

PEDIDO = "Transcreva a tabela de dureza desta folha seguindo as regras."


class CelulaLida(BaseModel):
    valor: str = Field(description="Como está escrito no papel, ex.: '44' ou '36,5'. Vazio se não leu com certeza.")
    duvida: bool = Field(description="true quando há algo escrito mas não dá para ler com certeza.")


class LinhaLida(BaseModel):
    num_peca: CelulaLida
    leituras: list[CelulaLida] = Field(description="Exatamente 5 leituras, na ordem das colunas 1 a 5.")


class FolhaLida(BaseModel):
    e_tabela_de_dureza: bool
    linhas: list[LinhaLida]
    observacao: str


class ErroLeitura(Exception):
    """Falha que a tela mostra para a pessoa (texto simples, sem jargão)."""

    def __init__(self, mensagem: str, status: int = 502) -> None:
        super().__init__(mensagem)
        self.status = status


def disponivel() -> bool:
    return bool(config().anthropic_api_key.strip())


# ---------------------------------------------------------------- imagem


def _jpeg(imagem: Image.Image) -> bytes:
    imagem = ImageOps.exif_transpose(imagem).convert("RGB")  # foto de celular "deitada" fica em pé
    imagem.thumbnail((MAX_LADO_PX, MAX_LADO_PX))
    for qualidade in (90, 80, 70, 60):
        saida = io.BytesIO()
        imagem.save(saida, "JPEG", quality=qualidade, optimize=True)
        if saida.tell() <= MAX_BYTES_IMAGEM:
            break
    return saida.getvalue()


def preparar_imagens(conteudo: bytes, extensao: str) -> list[bytes]:
    """Foto (JPG/PNG) ou PDF digitalizado -> lista de JPEGs prontos para enviar (no máximo 3 páginas)."""
    try:
        if extensao == ".pdf":
            with pymupdf.open(stream=conteudo, filetype="pdf") as documento:
                paginas = []
                for pagina in list(documento)[:MAX_PAGINAS_PDF]:
                    figura = pagina.get_pixmap(dpi=200)
                    paginas.append(_jpeg(Image.open(io.BytesIO(figura.tobytes("png")))))
                if not paginas:
                    raise ErroLeitura("O PDF não tem páginas.", 422)
                return paginas
        with Image.open(io.BytesIO(conteudo)) as imagem:
            return [_jpeg(imagem)]
    except ErroLeitura:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, RuntimeError) as erro:
        log.info("Foto do RIP-35 ilegível: %s", erro)
        raise ErroLeitura("Não foi possível abrir este arquivo como foto ou PDF. Tire a foto de novo.", 422) from erro


# ---------------------------------------------------------------- IA


def chamar_ia(imagens: list[bytes]) -> FolhaLida:
    """Envia as páginas para o modelo e devolve a tabela transcrita (validada pelo esquema FolhaLida)."""
    cfg = config()
    cliente = anthropic.Anthropic(api_key=cfg.anthropic_api_key, timeout=TEMPO_LIMITE_S, max_retries=0)
    conteudo: list[dict] = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(img).decode()}}
        for img in imagens
    ]
    conteudo.append({"type": "text", "text": PEDIDO})
    try:
        resposta = cliente.beta.messages.parse(
            model=cfg.leitura_foto_modelo,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # se o modelo recusar, a API tenta outro modelo na mesma chamada
            output_config={"effort": "high"},
            system=INSTRUCOES,
            messages=[{"role": "user", "content": conteudo}],
            output_format=FolhaLida,
        )
    except anthropic.AuthenticationError as erro:
        log.error("Leitura de foto: chave da API recusada (%s)", erro.status_code)
        raise ErroLeitura("A leitura automática está com problema de configuração. Avise a TI e preencha à mão.", 503) from erro
    except anthropic.RateLimitError as erro:
        raise ErroLeitura("Muitas leituras seguidas. Espere um minuto e tente de novo, ou preencha à mão.", 503) from erro
    except anthropic.APITimeoutError as erro:
        raise ErroLeitura("A leitura demorou demais. Tente de novo ou preencha à mão.", 504) from erro
    except anthropic.APIConnectionError as erro:
        log.warning("Leitura de foto: sem conexão com a API (%s)", erro)
        raise ErroLeitura("O serviço de leitura não respondeu. Tente de novo ou preencha à mão.", 502) from erro
    except anthropic.APIStatusError as erro:
        log.warning("Leitura de foto: API respondeu %s (pedido %s)", erro.status_code, erro.request_id)
        raise ErroLeitura("O serviço de leitura não conseguiu ler agora. Tente de novo ou preencha à mão.", 502) from erro

    log.info("Leitura de foto: %s, %s imagem(ns), parada=%s, pedido=%s", resposta.model, len(imagens),
             resposta.stop_reason, resposta._request_id)  # fmt: skip
    if resposta.stop_reason == "refusal":
        raise ErroLeitura("O serviço de leitura não leu esta foto. Preencha a tabela à mão.", 422)
    folha = resposta.parsed_output
    if resposta.stop_reason == "max_tokens" or folha is None:
        raise ErroLeitura("A leitura veio incompleta. Tente de novo com uma foto só da tabela, ou preencha à mão.", 502)
    return folha


# ---------------------------------------------------------------- conferência do que voltou


_RE_PECA = re.compile(r"[^0-9A-Za-z./-]")


def _valor_hrc(celula: CelulaLida) -> str:
    """'44' / '36,5' se for uma leitura HRc com cara de válida; '' se não leu, ficou na dúvida ou é absurdo."""
    if celula.duvida:
        return ""
    texto = celula.valor.strip().replace(" ", "").replace(".", ",")
    if not re.fullmatch(r"\d{1,3}(,\d{1,2})?", texto):
        return ""
    numero = float(texto.replace(",", "."))
    return texto if HRC_PLAUSIVEL[0] <= numero <= HRC_PLAUSIVEL[1] else ""


def normalizar(folha: FolhaLida) -> list[dict]:
    """Linhas para a tela: {peca, peca_nao_lida, valores[5], nao_lidos[5]}.

    Numa linha com alguma leitura, toda célula vazia volta marcada (nao_lidos): cada peça tem 5 pontos, então
    célula vazia é algo que a pessoa precisa conferir no papel. Linhas sem nenhuma leitura são descartadas.
    """
    linhas = []
    for linha in folha.linhas:
        celulas = (list(linha.leituras) + [CelulaLida(valor="", duvida=False)] * LEITURAS_POR_LINHA)[:LEITURAS_POR_LINHA]
        valores = [_valor_hrc(c) for c in celulas]
        if not any(valores) and not any(c.duvida for c in celulas):
            continue
        peca = "" if linha.num_peca.duvida else _RE_PECA.sub("", linha.num_peca.valor)[:20]
        linhas.append({
            "peca": peca,
            "peca_nao_lida": linha.num_peca.duvida or (not peca and bool(linha.num_peca.valor.strip())),
            "valores": valores,
            "nao_lidos": [not v for v in valores],
        })  # fmt: skip
    return linhas
