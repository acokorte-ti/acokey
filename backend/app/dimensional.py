"""Verificação automática de relatórios dimensionais RIP-33A (Registro de Inspeção Final).

Porte de legado/verificacao_dimensional.py. Lê a tabela de CARs (características) de um PDF no formato RIP-33A,
calcula a faixa aceitável de cada característica a partir da especificação/tolerância e aponta quais amostras
(P1..P10) ficaram fora.

Não usa IA: extrai o texto do PDF (pymupdf). Só funciona com PDF "nascido digital" nesse formato de tabela; um PDF
escaneado (imagem) não tem texto e cai no caso "tabela não encontrada".

Diferença do original: o texto de TODAS as células é relido pela posição da célula (`page.get_text(clip=...)`).
O original só fazia isso nas colunas de requisito e especificação, porque o texto vinha embaralhado; na versão
atual do pymupdf o `extract()` da tabela também separa pontos e vírgulas dos números ("100.02" -> "10002\\n."),
o que daria falsos "fora da tolerância".
"""
import re

import pymupdf

_RE_NUM = re.compile(r"-?\d+(?:\.\d+)?")
_RE_CAR = re.compile(r"^\d{1,3}$")
_QUALITATIVOS = ("", "---", "--", "-")
COLUNA_AMOSTRAS = 8  # P1 está na 9ª coluna
AMOSTRAS = 10
TOLERANCIA_NUMERICA = 1e-6


def _num(texto: str | None) -> float | None:
    if not texto:
        return None
    achado = _RE_NUM.search(texto.strip().replace(",", "."))
    return float(achado.group()) if achado else None


def _nominal(espec: str | None) -> float | None:
    s = (espec or "").strip()
    if s in _QUALITATIVOS:
        return None
    s = re.sub(r"\(.*?\)", "", s)  # tira sufixos como (2x), (4x), (3 pontos)
    return _num(s)


def _faixa(tol: str | None, nominal: float | None) -> tuple[float, float] | None:
    t = (tol or "").strip()
    if t in _QUALITATIVOS or nominal is None:
        return None
    t = t.replace(",", ".")
    if "/" in t:
        a_s, _, b_s = t.partition("/")
        a, b = _num(a_s), _num(b_s)
        if a is None or b is None:
            return None
        lo, hi = nominal + a, nominal + b
        return (min(lo, hi), max(lo, hi))
    if "±" in t:
        val = _num(t.split("±", 1)[1])
        if val is None:
            return None
        return (nominal - val, nominal + val)
    return None


def _amostra(valor: str | None) -> float | str | None:
    s = (valor or "").strip()
    if s in _QUALITATIVOS:
        return None
    if s.upper() == "OK":
        return "ok"
    return _num(s)


def _texto_da_celula(palavras: list, retangulo) -> str:
    """Palavras cujo CENTRO está dentro da célula, linha a linha.

    O recorte `get_text(clip=...)` também pega caracteres que só encostam na borda: com fonte alta/larga
    (ex.: DejaVu, a do servidor Linux) entravam pedaços da linha de cima ou de baixo no valor lido.
    """
    x0, y0, x1, y1 = retangulo
    dentro = [p for p in palavras if x0 <= (p[0] + p[2]) / 2 <= x1 and y0 <= (p[1] + p[3]) / 2 <= y1]
    dentro.sort(key=lambda p: (p[5], p[6], p[7]))  # bloco, linha e posição da palavra no PDF
    linhas: list[list[str]] = []
    chave_anterior = None
    for p in dentro:
        if (p[5], p[6]) != chave_anterior:
            linhas.append([])
            chave_anterior = (p[5], p[6])
        linhas[-1].append(p[4])
    return "\n".join(" ".join(linha) for linha in linhas)


def _celulas(pagina, tabela, indice: int, extraida: list) -> list[str]:
    """Texto de cada célula da linha, relido pela posição; se não der, o que o extract() trouxe."""
    try:
        retangulos = tabela.rows[indice].cells
    except (IndexError, AttributeError):
        retangulos = []
    try:
        palavras = pagina.get_text("words")
    except (ValueError, RuntimeError):
        palavras = []
    saida = []
    for coluna, bruto in enumerate(extraida):
        retangulo = retangulos[coluna] if coluna < len(retangulos) else None
        texto = _texto_da_celula(palavras, retangulo).strip() if retangulo else ""
        saida.append(texto or (bruto or "").strip())
    return saida


def _sem_quebra(texto: str) -> str:
    return " ".join(texto.split())


def _depois_do_rotulo(texto: str) -> str:
    """'Inspecionado por\\nFulano' -> 'Fulano'."""
    return texto.split("\n", 1)[-1].strip()


def analisar_rip33a(caminho=None, dados: bytes | None = None) -> dict:
    """Analisa um PDF RIP-33A. Informe `caminho` (Path/str) OU `dados` (bytes)."""
    try:
        doc = pymupdf.open(stream=dados, filetype="pdf") if dados is not None else pymupdf.open(caminho)
    except Exception:  # pymupdf levanta vários tipos para arquivo corrompido
        return {"ok": False, "erro": "Não foi possível abrir o PDF. Confira se o arquivo é um PDF válido e não está corrompido."}

    cars: list[dict] = []
    rodape: dict[str, str] = {}
    achou_tabela = False
    with doc:
        for pagina in doc:
            try:
                tabelas = pagina.find_tables().tables
            except Exception:  # página sem estrutura reconhecível
                tabelas = []
            for tabela in tabelas:
                linhas = tabela.extract()
                if not linhas:
                    continue
                achou_tabela = True
                for indice, extraida in enumerate(linhas):
                    if not extraida:
                        continue
                    linha = _celulas(pagina, tabela, indice, extraida)
                    c0 = linha[0]
                    junto = _sem_quebra(" ".join(linha))

                    if c0.startswith("Inspecionado por"):
                        rodape["inspecionado_por"] = _depois_do_rotulo(c0)
                        if len(linha) > 2 and linha[2]:
                            rodape["data_inspecao"] = _depois_do_rotulo(linha[2])
                        if len(linha) > 4 and linha[4]:
                            rodape["aprovado_por"] = _depois_do_rotulo(linha[4])
                        if len(linha) > 5 and linha[5]:
                            rodape["data_aprovacao"] = _depois_do_rotulo(linha[5])
                    if len(linha) > COLUNA_AMOSTRAS and linha[COLUNA_AMOSTRAS].upper() == "X":
                        if "Aprovado - Inspeção" in junto:
                            rodape["status"] = "Aprovado - Inspeção"
                        elif "Aprovado com Desvio" in junto:
                            rodape["status"] = "Aprovado com Desvio Dimensional"

                    if not _RE_CAR.match(c0) or len(linha) < COLUNA_AMOSTRAS + AMOSTRAS:
                        continue

                    requisito, espec, tol = _sem_quebra(linha[1]), _sem_quebra(linha[2]), linha[3]
                    nominal = _nominal(espec)
                    faixa = _faixa(tol, nominal)
                    amostras = [_amostra(v) for v in linha[COLUNA_AMOSTRAS:COLUNA_AMOSTRAS + AMOSTRAS]]
                    fora = [
                        {"amostra": f"P{i + 1}", "valor": v}
                        for i, v in enumerate(amostras)
                        if isinstance(v, float) and faixa is not None
                        and not (faixa[0] - TOLERANCIA_NUMERICA <= v <= faixa[1] + TOLERANCIA_NUMERICA)
                    ]  # fmt: skip
                    numericos = [v for v in amostras if isinstance(v, float)]
                    aviso = tol.strip() not in _QUALITATIVOS and (nominal is None or faixa is None) and bool(numericos)
                    cars.append({
                        "car": c0, "requisito": requisito, "espec": espec, "tol": _sem_quebra(tol),
                        "nominal": nominal, "faixa": list(faixa) if faixa else None, "fora": fora, "aviso": aviso,
                        "amostras": amostras,
                        "minimo": min(numericos) if numericos else None,
                        "maximo": max(numericos) if numericos else None,
                    })  # fmt: skip

    if not achou_tabela or not cars:
        return {
            "ok": False,
            "erro": "Não encontrei uma tabela de CARs reconhecível neste PDF (pode ser um PDF escaneado/imagem, ou um "
                    "formato diferente do RIP-33A). Confira o relatório manualmente.",
        }  # fmt: skip
    return {
        "ok": True,
        "erro": None,
        "total_cars": len(cars),
        "cars": cars,
        "cars_fora": [c for c in cars if c["fora"]],
        "cars_aviso": [c for c in cars if c["aviso"] and not c["fora"]],
        "rodape": rodape,
    }
