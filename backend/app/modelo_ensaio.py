"""Preenchimento do modelo .docx de requisição de ensaio do laboratório externo.

Trazido do sistema antigo (legado/app.py: geração do .docx do laboratório e auxiliares), com a regra do dono: o sistema
preenche SÓ as células marcadas literalmente "Preencher" no modelo e não mexe em mais nada do layout ou do texto.

- O que vai em cada célula "Preencher" sai do rótulo dela (a célula à esquerda terminada em ":" ou, senão, o
  título da coluna acima): DATA, IDENTIFICAÇÃO DA AMOSTRA, MATERIAL, ENSAIO, NORMA, QUANTIDADE, ITEM,
  INFORMAÇÕES ADICIONAIS. Rótulo desconhecido (ou sem valor): o marcador fica, para a Qualidade preencher à mão.
- A linha que tem a identificação é a linha-modelo: sai uma linha por grupo de material + ensaio (as OPs do grupo
  com a quantidade de CPs de cada uma, sem lote nem corrida). Cada linha a mais ocupa uma linha vazia do modelo
  (sem texto e sem imagem), para a tabela não crescer.
- Qual laboratório usa o modelo e qual é o arquivo ficam nos parâmetros (nada de nome de laboratório no código):
  `modelo_ensaio_prestador` (trecho do nome do prestador; vazio = o botão não aparece) e `modelo_ensaio_arquivo`
  (nome do .docx em recursos/modelos/; vazio = o único .docx da pasta).
"""
import io
import unicodedata
from copy import deepcopy
from pathlib import Path

import docx
from docx.shared import RGBColor
from docx.table import Table, _Cell, _Row
from sqlalchemy.orm import Session

from app import parametros
from app.arquivos import caminho_seguro
from app.config import config
from app.expedicao import material, numero_br
from app.models import EspecificacaoTipo

MARCADOR = "preencher"
PAPEIS_DO_GRUPO = frozenset({"identificacao", "material", "ensaio", "norma", "quantidade"})
# (trecho do rótulo, papel). A ordem importa: "NORMA DE ENSAIO" é norma, não ensaio.
_PAPEIS = (
    ("identifica", "identificacao"),
    ("norma", "norma"),
    ("material", "material"),
    ("ensaio", "ensaio"),
    ("analise", "ensaio"),
    ("quantidade", "quantidade"),
    ("qtd", "quantidade"),
    ("item", "item"),
    ("data", "data"),
    ("informa", "informacoes"),
    ("observa", "informacoes"),
)
NOME_ENSAIO = {"tracao": "Ensaio de tração", "charpy": "Ensaio de impacto Charpy"}
NORMA_PADRAO = {"tracao": "ASTM A370", "charpy": "ASTM E23"}
CAMPO_CPS = {"tracao": "qt_cp_tracao", "charpy": "qt_cp_impacto"}
# Elementos do parágrafo que carregam o texto do marcador (o resto, como a formatação do parágrafo, fica)
_COM_TEXTO = frozenset({"r", "hyperlink", "sdt", "ins", "smartTag", "fldSimple"})


def _normalizar(texto: str | None) -> str:
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower().strip()


def prestador_usa_modelo(db: Session, prestador: str | None) -> bool:
    trecho = _normalizar(parametros.ler(db, "modelo_ensaio_prestador", ""))
    return bool(trecho) and trecho in _normalizar(prestador)


def arquivo_modelo(db: Session) -> Path | None:
    """O .docx do modelo dentro de recursos/modelos/ (nunca fora da pasta de arquivos)."""
    nome = parametros.ler(db, "modelo_ensaio_arquivo", "").strip()
    if nome:
        return caminho_seguro(f"recursos/modelos/{Path(nome).name}")
    pasta = config().pasta_arquivos / "recursos" / "modelos"
    candidatos = [p for p in pasta.glob("*.docx") if not p.name.startswith("~$")] if pasta.is_dir() else []
    return candidatos[0] if len(candidatos) == 1 else None


def modelo_disponivel(db: Session, prestador: str | None) -> bool:
    return prestador_usa_modelo(db, prestador) and arquivo_modelo(db) is not None


# ---------------------------------------------------------------- textos de cada grupo


def texto_material(db: Session, tipo: str) -> str:
    """'Aço SC 4330 – Temperado e Revenido para 30/39 HRc', com a dureza do cadastro de especificações."""
    espec = db.get(EspecificacaoTipo, tipo)
    base = f"Aço {material(tipo)} – Temperado e Revenido"
    if espec is not None and espec.dureza_min is not None and espec.dureza_max is not None:
        return f"{base} para {numero_br(espec.dureza_min)}/{numero_br(espec.dureza_max)} HRc"
    return base


def texto_ensaio(db: Session, ensaio: str) -> str:
    return parametros.ler(db, f"modelo_ensaio_texto_{ensaio}", NOME_ENSAIO[ensaio])


def texto_norma(db: Session, ensaio: str) -> str:
    norma = parametros.ler(db, f"modelo_ensaio_norma_{ensaio}", NORMA_PADRAO[ensaio])
    codigo = parametros.ler(db, "especificacao_codigo").strip()
    return f"{norma}\n{codigo}" if codigo and codigo not in norma else norma


def grupos_do_envio(db: Session, dados: dict) -> list[dict]:
    """Uma linha por material (SC 4330 x H11 Modified) e ensaio, listando as OPs e os CPs de cada uma."""
    ensaios = [e for e, mostrar in (("tracao", dados["mostrar_tracao"]), ("charpy", dados["mostrar_charpy"])) if mostrar]
    por_material: dict[str, list[dict]] = {}
    for item in dados["itens"]:
        por_material.setdefault(material(item["tipo"]), []).append(item)
    grupos = []
    for itens in por_material.values():
        tipo = itens[0]["tipo"]
        if not ensaios:  # serviço sem CPs: só as OPs
            grupos.append({"identificacao": "OP " + ", ".join(str(i["op"]) for i in itens), "material": texto_material(db, tipo),
                           "ensaio": "", "norma": "", "quantidade": str(sum(i["qt_liberar"] or i["qtd"] for i in itens)),
                           "nome_ensaio": "", "nome_material": material(tipo)})  # fmt: skip
            continue
        for ensaio in ensaios:
            partes = [(i["op"], i[CAMPO_CPS[ensaio]]) for i in itens if i[CAMPO_CPS[ensaio]]]
            if not partes:
                continue  # nenhuma OP deste material tem CP para este ensaio
            total = sum(q for _, q in partes)
            linhas = [f"OP {op} - {q} CP{'s' if q > 1 else ''}" for op, q in partes] + [f"Total: {total} CPs"]
            grupos.append({
                "identificacao": "\n".join(linhas), "material": texto_material(db, tipo), "ensaio": texto_ensaio(db, ensaio),
                "norma": texto_norma(db, ensaio), "quantidade": str(total), "nome_ensaio": NOME_ENSAIO[ensaio],
                "nome_material": material(tipo),
            })  # fmt: skip
    return grupos


def _textos_gerais(db: Session, dados: dict) -> dict[str, str]:
    data = dados.get("data_emissao") or dados.get("data_envio")
    informacoes = []
    if dados.get("qtd_cp_tracao"):
        informacoes.append(f"QTD CP Tração: {dados['qtd_cp_tracao']}")
    if dados.get("qtd_cp_impacto"):
        informacoes.append(f"QTD CP Impacto Charpy: {dados['qtd_cp_impacto']}")
    if dados.get("observacoes"):
        informacoes.append(dados["observacoes"])
    informacoes.append(f"Nº interno: {dados['numero']}")
    return {
        "data": data.strftime("%d/%m/%Y") if data else "",
        "informacoes": " · ".join(informacoes),
        "quantidade": str((dados.get("qtd_cp_tracao") or 0) + (dados.get("qtd_cp_impacto") or 0) or ""),
    }


# ---------------------------------------------------------------- mexendo no .docx


def _diz_preencher(celula: _Cell) -> bool:
    return (celula.text or "").strip().lower() == MARCADOR


def _primeira_linha(texto: str | None) -> str:
    for linha in (texto or "").splitlines():
        if linha.strip():
            return linha.strip()
    return ""


def _celulas(linha: _Row) -> list[tuple[int, _Cell]]:
    """(coluna, célula) sem repetir a célula mesclada que ocupa várias colunas."""
    vistas, saida = set(), []
    for coluna, celula in enumerate(linha.cells):
        if id(celula._tc) in vistas:
            continue
        vistas.add(id(celula._tc))
        saida.append((coluna, celula))
    return saida


def _papel(tabela: Table, linha_doc: _Row, coluna: int) -> str:
    """O que a célula "Preencher" pede, pelo rótulo à esquerda ("DATA:") ou pelo título da coluna acima."""
    linhas = list(tabela.rows)
    linha = next(i for i, r in enumerate(linhas) if r._tr is linha_doc._tr)  # posição atual (linhas podem ter sido copiadas)
    celulas = linhas[linha].cells
    esquerda = ""
    for c in range(coluna - 1, -1, -1):
        if celulas[c]._tc is not celulas[coluna]._tc:
            esquerda = _primeira_linha(celulas[c].text)
            break
    rotulo = esquerda if esquerda.endswith(":") else ""
    if not rotulo:
        for acima in range(linha - 1, -1, -1):
            celulas_acima = linhas[acima].cells
            if coluna >= len(celulas_acima):
                continue  # tabela irregular: a linha de cima tem menos colunas
            texto = _primeira_linha(celulas_acima[coluna].text)
            if texto and texto.lower() != MARCADOR:
                rotulo = texto
                break
    rotulo = _normalizar(rotulo or esquerda)
    return next((papel for trecho, papel in _PAPEIS if trecho in rotulo), "")


def _escrever(celula: _Cell, texto: str) -> None:
    """Troca o marcador pelo texto, sem negrito/sublinhado/cor de destaque do marcador; mantém fonte e tamanho."""
    paragrafo = celula.paragraphs[0]
    primeiro = paragrafo.runs[0] if paragrafo.runs else None
    fonte, tamanho = (primeiro.font.name, primeiro.font.size) if primeiro else (None, None)
    for filho in list(paragrafo._p):
        if filho.tag.rpartition("}")[2] in _COM_TEXTO:
            paragrafo._p.remove(filho)
    for indice, trecho in enumerate((texto or "").split("\n")):
        run = paragrafo.add_run()
        if indice:
            run.add_break()
        run.add_text(trecho)
        run.bold = run.italic = run.underline = False
        run.font.highlight_color = None
        run.font.color.rgb = RGBColor(0, 0, 0)
        if fonte:
            run.font.name = fonte
        if tamanho:
            run.font.size = tamanho
    for extra in list(celula.paragraphs[1:]):
        extra._element.getparent().remove(extra._element)


def _vazia(tr) -> bool:
    """Linha de tabela sem texto e sem imagem (lugar para mais uma amostra)."""
    if "".join(tr.itertext()).strip():
        return False
    return not any(el.tag.rpartition("}")[2] in ("drawing", "pict", "object") for el in tr.iter())


def _ocupar_linha_vazia(depois_de) -> None:
    """Tira a primeira linha vazia abaixo (pulando as que têm conteúdo, como a de imagem do modelo)."""
    seguinte = depois_de.getnext()
    while seguinte is not None:
        if seguinte.tag == depois_de.tag and _vazia(seguinte):
            seguinte.getparent().remove(seguinte)
            return
        seguinte = seguinte.getnext()


def _preencher_linha_modelo(tabela: Table, linha: _Row, papeis: dict[int, str], grupos: list[dict], gerais: dict[str, str]) -> None:
    """Uma linha por grupo (copiando a linha-modelo); em cada uma, só as células que eram "Preencher"."""
    modelo = linha._tr
    trs = [modelo]
    anterior = modelo
    for _ in grupos[1:]:
        novo = deepcopy(modelo)
        anterior.addnext(novo)
        _ocupar_linha_vazia(novo)  # a linha nova ocupa o lugar de uma vazia do modelo: a tabela não cresce
        anterior = novo
        trs.append(novo)
    varios_ensaios = len({g["nome_ensaio"] for g in grupos}) > 1
    varios_materiais = len({g["nome_material"] for g in grupos}) > 1
    for numero, (tr, grupo) in enumerate(zip(trs, grupos, strict=True), start=1):
        nova = _Row(tr, tabela)
        identificacao = grupo["identificacao"]
        # Se o modelo não deixa escrever o ensaio/material na linha, a identificação diz qual é
        if varios_ensaios and "ensaio" not in papeis.values() and grupo["nome_ensaio"]:
            identificacao = f"{grupo['nome_ensaio']}\n{identificacao}"
        if varios_materiais and "material" not in papeis.values():
            identificacao = f"{grupo['nome_material']}\n{identificacao}"
        valores = {**gerais, **grupo, "identificacao": identificacao, "item": str(numero)}
        celulas = dict(_celulas(nova))
        for coluna, papel in papeis.items():
            if coluna in celulas and valores.get(papel):  # sem valor, o marcador fica para preencher à mão
                _escrever(celulas[coluna], valores[papel])
        if numero > 1:  # o número do item da linha copiada acompanha a sequência
            for coluna, celula in celulas.items():
                if coluna not in papeis and (celula.text or "").strip().isdigit():
                    _escrever(celula, str(numero))
                    break


def preencher_modelo(db: Session, caminho: Path, dados: dict) -> bytes:
    documento = docx.Document(str(caminho))
    grupos = grupos_do_envio(db, dados)
    gerais = _textos_gerais(db, dados)
    for tabela in documento.tables:
        for linha in list(tabela.rows):
            if linha._tr.getparent() is None:
                continue  # linha vazia que já foi ocupada por um grupo
            marcadas = [(coluna, celula) for coluna, celula in _celulas(linha) if _diz_preencher(celula)]
            if not marcadas:
                continue
            papeis = {coluna: _papel(tabela, linha, coluna) for coluna, _ in marcadas}
            do_grupo = {c: p for c, p in papeis.items() if p in PAPEIS_DO_GRUPO}
            if do_grupo:  # o número do item só é do grupo quando a linha é a linha-modelo
                do_grupo |= {c: p for c, p in papeis.items() if p == "item"}
            if do_grupo and grupos:
                _preencher_linha_modelo(tabela, linha, papeis, grupos, gerais)
                continue
            for coluna, celula in marcadas:
                if coluna in do_grupo:
                    continue  # nenhum grupo (nenhum CP informado): a célula fica para preencher à mão
                valor = gerais.get(papeis[coluna], "")
                if valor:
                    _escrever(celula, valor)
    saida = io.BytesIO()
    documento.save(saida)
    return saida.getvalue()
