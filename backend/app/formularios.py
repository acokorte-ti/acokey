"""Formulários de registro de cada tipo de etapa: confere o que foi digitado, calcula aprovado/reprovado e monta o
relatório que fica em `registros.dados["report"]` (e vira o PDF do registro).

Portado de legado/app.py (num, fmt, parse_pares, tempo_no_patamar, tokens, decisao, rel e p_quimica ... p_embalagem).
O formato do relatório é o mesmo do sistema antigo: {titulo, kv: [[rótulo, valor]], tabelas: [{titulo, cab, linhas}],
grafico, obs} e, na inspeção visual, "laser" com os códigos gravados. Os registros migrados usam esse formato.

Especificação: os limites de dureza, tração e Charpy cadastrados para o tipo (especificacoes_tipo) e as cotas
cadastradas para o item (especificacoes_cotas) valem sobre o que vier da tela. Só o limite que NÃO está cadastrado
é pedido à pessoa (nunca se inventa valor da especificação técnica).
"""
import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.models import EspecificacaoCota, EspecificacaoTipo
from app.seguranca import limpar_texto

MAXIMO_PECAS_LASER = 100_000
CICLOS_TT = ("Têmpera", "Revenimento", "Normalização", "Alívio de tensões")


class ErroFormulario(ValueError):
    """Dado do formulário que impede o registro. A mensagem vai direto para a tela."""


@dataclass
class Ficha:
    """O que os formulários precisam saber do lote e da etapa."""

    numero: str
    op: str
    tipo: str
    qtd: int
    corrida: str
    relatorio: str  # nome do relatório oficial da etapa para o tipo do lote
    espec: EspecificacaoTipo | None = None
    cotas: dict[int, EspecificacaoCota] = field(default_factory=dict)
    elementos: list[str] = field(default_factory=list)
    laser_formato: str = ""


@dataclass
class Resultado:
    status: str  # aprovado | reprovado | pendente
    report: dict
    corrida: str | None = None  # Receb. MP: a corrida informada passa a ser a do lote


# ---------------------------------------------------------------- utilitários (iguais aos do sistema antigo)


def num(valor: Any) -> float | None:
    """'24,5' -> 24.5. Texto vazio ou que não é número -> None."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, int | float):
        numero = float(valor)
    else:
        try:
            numero = float(str(valor).strip().replace(",", "."))
        except ValueError:
            return None
    return numero if math.isfinite(numero) else None


def fmt(valor: float | None) -> str:
    return "" if valor is None else f"{valor:.6g}"


def texto(campos: dict, chave: str, limite: int = 300) -> str:
    valor = campos.get(chave)
    if valor is None or isinstance(valor, dict | list):
        return ""
    return limpar_texto(str(valor)).strip()[:limite]


def marcado(campos: dict, chave: str) -> bool:
    valor = campos.get(chave)
    return valor is True or str(valor).strip().lower() in ("1", "true", "sim", "on")


def lista(campos: dict, chave: str, limite: int = 200) -> list[dict]:
    valor = campos.get(chave)
    if not isinstance(valor, list):
        return []
    return [item for item in valor[:limite] if isinstance(item, dict)]


def numero_digitado(campos: dict, chave: str, rotulo: str) -> float | None:
    """Número opcional: vazio vale None; preenchido com algo que não é número é erro (antes era ignorado calado)."""
    bruto = campos.get(chave)
    if bruto is None or str(bruto).strip() == "":
        return None
    valor = num(bruto)
    if valor is None:
        raise ErroFormulario(f"{rotulo}: '{str(bruto)[:40]}' não é um número.")
    return valor


def parse_pares(conteudo: str) -> list[tuple[float, float]]:
    """Linhas 'tempo;temperatura' (aceita ; tab espaço ou vírgula)."""
    pontos = []
    for linha in (conteudo or "").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        if ";" in linha or "\t" in linha:
            partes = re.split(r"[;\t]+", linha.replace(",", "."))
        else:
            partes = re.split(r"[,\s]+", linha)
        valores = [num(p) for p in partes[:2]]
        if len(valores) == 2 and None not in valores:
            pontos.append((valores[0], valores[1]))
    return pontos


def tempo_no_patamar(pontos: list[tuple[float, float]], baixo: float, alto: float) -> float:
    """Minutos em que a curva ficou dentro da faixa [baixo, alto], interpolando entre os pontos."""
    total = 0.0
    for (x1, y1), (x2, y2) in zip(pontos, pontos[1:], strict=False):
        dx = x2 - x1
        if dx <= 0:
            continue
        if y1 == y2:
            if baixo <= y1 <= alto:
                total += dx
            continue
        a, b = sorted(((baixo - y1) / (y2 - y1), (alto - y1) / (y2 - y1)))
        a, b = max(a, 0), min(b, 1)
        if b > a:
            total += (b - a) * dx
    return total


def tokens(valor: str) -> list[str]:
    return [t for t in re.split(r"[;\s]+", (valor or "").strip()) if t]


def decisao(campos: dict, ruim: bool) -> str:
    return "reprovado" if ruim or campos.get("decisao") == "reprovado" else "aprovado"


def rel(titulo: str, kv: list, tabelas: list | None = None, grafico: dict | None = None, obs: str = "") -> dict:
    return {"titulo": titulo, "kv": [[a, str(b)] for a, b in kv], "tabelas": tabelas or [], "grafico": grafico, "obs": obs}


def _obs(campos: dict) -> str:
    return texto(campos, "obs", 4000)


def _espec(ficha: Ficha, coluna: str) -> float | None:
    valor = getattr(ficha.espec, coluna, None) if ficha.espec else None
    return float(valor) if valor is not None else None


def _limite(ficha: Ficha, coluna: str, campos: dict, chave: str, rotulo: str) -> float | None:
    """Limite cadastrado na especificação; se não houver, o que a pessoa digitou."""
    cadastrado = _espec(ficha, coluna)
    return cadastrado if cadastrado is not None else numero_digitado(campos, chave, rotulo)


def _data_br(valor: str) -> str:
    try:
        return date.fromisoformat(valor).strftime("%d/%m/%Y")
    except ValueError:
        return valor


def codigos_laser(formato: str, ano: str, tri: str, corrida: str, lote: str, quantidade: int) -> list[str]:
    try:
        return [formato.format(ano=ano, tri=tri, corrida=corrida or "SC", lote=lote, seq=i) for i in range(1, quantidade + 1)]
    except (KeyError, IndexError, ValueError) as erro:
        raise ErroFormulario(
            "O formato do código gravado a laser (parâmetro 'laser_formato') está inválido. Avise o administrador."
        ) from erro


def formato_laser_legivel(formato: str) -> str:
    return formato.replace("{", "<").replace("}", ">").replace(":03d", "")


# ---------------------------------------------------------------- formulários (um por tipo de etapa)


def p_quimica(campos: dict, ficha: Ficha, sub: str) -> Resultado:
    por_elemento = {texto(e, "elemento", 10): e for e in lista(campos, "elementos")}
    linhas, ruim = [], False
    for elemento in ficha.elementos:
        e = por_elemento.get(elemento, {})
        valor = numero_digitado(e, "valor", f"Valor de {elemento}")
        minimo = numero_digitado(e, "min", f"Mínimo de {elemento}")
        maximo = numero_digitado(e, "max", f"Máximo de {elemento}")
        if valor is None:
            continue
        ok = (minimo is None or valor >= minimo) and (maximo is None or valor <= maximo)
        ruim |= not ok
        linhas.append([elemento, fmt(valor), fmt(minimo), fmt(maximo), "OK" if ok else "FORA"])
    if not linhas:
        raise ErroFormulario("Informe ao menos um elemento da composição química.")
    corrida = texto(campos, "corrida", 60)
    if not corrida:
        raise ErroFormulario("Informe o número da corrida.")
    kv = [("Corrida", corrida), ("Fornecedor", texto(campos, "fornecedor")), ("Certificado nº", texto(campos, "cert")),
          ("Norma / grau", texto(campos, "norma"))]  # fmt: skip
    tabela = {"titulo": "Composição química (% em massa)", "cab": ["Elemento", "Valor", "Mín.", "Máx.", "Resultado"], "linhas": linhas}
    return Resultado(decisao(campos, ruim), rel(ficha.relatorio, kv, [tabela], obs=_obs(campos)), corrida=corrida)


def p_tt(campos: dict, ficha: Ficha, sub: str) -> Resultado:
    alvo = numero_digitado(campos, "alvo", "Temperatura alvo")
    tolerancia = numero_digitado(campos, "tol", "Tolerância")
    tolerancia = 10.0 if tolerancia is None else tolerancia
    patamar = numero_digitado(campos, "patamar", "Patamar exigido")
    if alvo is None or patamar is None:
        raise ErroFormulario("Informe temperatura alvo e tempo de patamar exigido.")
    if tolerancia < 0 or patamar < 0:
        raise ErroFormulario("A tolerância e o patamar não podem ser negativos.")
    pontos = sorted(parse_pares(texto(campos, "curva", 200_000)))
    if len(pontos) < 2:
        raise ErroFormulario("Cole ou envie a curva do forno (linhas 'tempo(min); temperatura(°C)').")
    if len(pontos) > 5000:
        raise ErroFormulario("A curva do forno tem pontos demais (máximo 5.000 linhas).")
    no_patamar = tempo_no_patamar(pontos, alvo - tolerancia, alvo + tolerancia)
    maxima = max(y for _, y in pontos)
    ok = no_patamar >= patamar
    ciclo = texto(campos, "ciclo", 40)
    kv = [("Ciclo", ciclo), ("Forno", texto(campos, "forno")), ("Temperatura alvo", f"{fmt(alvo)} °C (±{fmt(tolerancia)})"),
          ("Patamar exigido", f"{fmt(patamar)} min"), ("Tempo medido no patamar", f"{no_patamar:.1f} min"),
          ("Temperatura máxima", f"{maxima:.0f} °C"), ("Duração total", f"{pontos[-1][0] - pontos[0][0]:.0f} min"),
          ("Meio de resfriamento", texto(campos, "meio")), ("Resultado", "APROVADO" if ok else "REPROVADO")]  # fmt: skip
    titulo = ficha.relatorio + (f" - {ciclo}" if ciclo else "")
    grafico = {"pts": [list(p) for p in pontos], "alvo": alvo, "tol": tolerancia}
    return Resultado(decisao(campos, not ok), rel(titulo, kv, grafico=grafico, obs=_obs(campos)))


def ler_leituras_dureza(conteudo: str) -> list[tuple[str, list[float]]]:
    """'P1 35 37', 'P1-35-35-37' ou '35;35;37' (uma peça por linha) -> [(nome, [valores])]."""
    pecas = []
    for i, linha in enumerate([x for x in (conteudo or "").splitlines() if x.strip()], 1):
        partes = [t for t in re.split(r"[;\s\-]+", linha.strip()) if t]
        nome, valores = None, []
        for parte in partes:
            valor = num(parte)
            if valor is None:
                if nome is None and not valores:
                    nome = parte[:20]
                else:
                    raise ErroFormulario(f"Leitura inválida na linha {i}: '{linha[:60]}' (o valor '{parte[:20]}' não é um número).")
            else:
                valores.append(valor)
        if not valores:
            raise ErroFormulario(
                f"Nenhuma leitura numérica na linha {i}: '{linha[:60]}'. Exemplos válidos: 'P1 35', 'P1-35-35-37', '35;35;37'."
            )
        pecas.append((nome or f"P{i}", valores))
    return pecas


def p_dureza(campos: dict, ficha: Ficha, sub: str) -> Resultado:
    minimo = _limite(ficha, "dureza_min", campos, "min", "Dureza mínima")
    maximo = _limite(ficha, "dureza_max", campos, "max", "Dureza máxima")
    if minimo is None and maximo is None:
        raise ErroFormulario("Informe ao menos o limite mínimo ou máximo de dureza (HRC).")
    linhas, valores = [], []
    for nome, leituras in ler_leituras_dureza(texto(campos, "leituras", 50_000)):
        for j, valor in enumerate(leituras, 1):
            ok = (minimo is None or valor >= minimo) and (maximo is None or valor <= maximo)
            linhas.append([nome if len(leituras) == 1 else f"{nome} pt{j}", fmt(valor), "OK" if ok else "FORA"])
            valores.append((valor, ok))
    if not valores:
        raise ErroFormulario("Informe as leituras de dureza (uma por linha, ex.: 'P1 24,5' ou 'P1 24,5 25 24,8').")
    ruim = any(not ok for _, ok in valores)
    v = [x for x, _ in valores]
    kv = [("Método", "Rockwell C (HRC)"), ("Especificação", f"{fmt(minimo) or '-'} a {fmt(maximo) or '-'} HRC"),
          ("Leituras", len(v)), ("Mínimo / Máximo", f"{min(v):g} / {max(v):g} HRC"),
          ("Média", f"{sum(v) / len(v):.1f} HRC"), ("Durômetro / calibração", texto(campos, "equip", 400)),
          ("Resultado", "REPROVADO" if ruim else "APROVADO")]  # fmt: skip
    tabela = {"titulo": "Leituras", "cab": ["Peça / ponto", "HRC", "Resultado"], "linhas": linhas}
    return Resultado(decisao(campos, ruim), rel(ficha.relatorio, kv, [tabela], obs=_obs(campos)))


def _temperatura_charpy(valor: str) -> str:
    """O cadastro guarda texto ('Ambiente', '-20'): número ganha °C, texto fica como está."""
    numero = num(valor)
    return f"{fmt(numero)} °C" if numero is not None else (valor or "-")


def p_lab(campos: dict, ficha: Ficha, sub: str) -> Resultado:
    lab = [("Laboratório", texto(campos, "laboratorio")), ("Relatório do laboratório nº", texto(campos, "rel_lab"))]
    validado = marcado(campos, "validado")
    validador = ("Validado por", texto(campos, "validador", 120) if validado else "NÃO VALIDADO")
    linhas, ruim = [], False
    if sub == "tracao":
        sp = {
            "le_min": _limite(ficha, "tr_le_min", campos, "le_min", "LE mín."),
            "le_max": _limite(ficha, "tr_le_max", campos, "le_max", "LE máx."),
            "lr_min": _limite(ficha, "tr_lr_min", campos, "lr_min", "LR mín."),
            "lr_max": _limite(ficha, "tr_lr_max", campos, "lr_max", "LR máx."),
            "al_min": _limite(ficha, "tr_al_min", campos, "al_min", "Alongamento mín."),
            "ra_min": _limite(ficha, "tr_ra_min", campos, "ra_min", "RA mín."),
        }
        for cp in lista(campos, "cps"):
            nome = texto(cp, "cp", 30)
            le = numero_digitado(cp, "le", f"LE de {nome or 'CP'}")
            lr = numero_digitado(cp, "lr", f"LR de {nome or 'CP'}")
            al = numero_digitado(cp, "al", f"Alongamento de {nome or 'CP'}")
            ra = numero_digitado(cp, "ra", f"RA de {nome or 'CP'}")
            if None in (le, lr, al):
                continue
            ok = (
                (sp["le_min"] is None or le >= sp["le_min"]) and (sp["le_max"] is None or le <= sp["le_max"])
                and (sp["lr_min"] is None or lr >= sp["lr_min"]) and (sp["lr_max"] is None or lr <= sp["lr_max"])
                and (sp["al_min"] is None or al >= sp["al_min"])
                and (sp["ra_min"] is None or ra is None or ra >= sp["ra_min"])
            )  # fmt: skip
            ruim |= not ok
            linhas.append([nome, fmt(le), fmt(lr), fmt(al), fmt(ra), "OK" if ok else "FORA"])
        if not linhas:
            raise ErroFormulario("Informe ao menos um corpo de prova (LE, LR e alongamento).")
        esp = (f"LE {fmt(sp['le_min']) or '-'}-{fmt(sp['le_max']) or '-'} MPa; "
               f"LR {fmt(sp['lr_min']) or '-'}-{fmt(sp['lr_max']) or '-'} MPa; "
               f"A mín. {fmt(sp['al_min']) or '-'}%; RA mín. {fmt(sp['ra_min']) or '-'}%")  # fmt: skip
        titulo = "Relatório de Ensaio de Tração (resultados do laboratório externo)"
        tabelas = [{"titulo": "Corpos de prova", "cab": ["CP", "LE (MPa)", "LR (MPa)", "A (%)", "RA (%)", "Resultado"], "linhas": linhas}]
    elif sub == "charpy":
        temperatura = (ficha.espec.ch_temp if ficha.espec and ficha.espec.ch_temp else "") or texto(campos, "temp", 40)
        corpo_prova = (ficha.espec.ch_dim_cp if ficha.espec and ficha.espec.ch_dim_cp else "") or texto(campos, "dim_cp", 40)
        media_min = _limite(ficha, "ch_med_min", campos, "med_min", "Energia média mín.")
        individual_min = _limite(ficha, "ch_ind_min", campos, "ind_min", "Energia individual mín.")
        if media_min is None and individual_min is None:
            raise ErroFormulario("Informe o critério de energia (média mínima e/ou individual mínima, em J).")
        for conjunto in lista(campos, "conjuntos"):
            nome = texto(conjunto, "cp", 30)
            j = [numero_digitado(conjunto, c, f"{c.upper()} de {nome or 'conjunto'}") for c in ("j1", "j2", "j3")]
            if None in j:
                continue
            media = sum(j) / 3
            ok = (media_min is None or media >= media_min) and (individual_min is None or min(j) >= individual_min)
            ruim |= not ok
            linhas.append([nome, fmt(j[0]), fmt(j[1]), fmt(j[2]), f"{media:.1f}", "OK" if ok else "FORA"])
        if not linhas:
            raise ErroFormulario("Informe ao menos um conjunto de 3 corpos de prova Charpy (energia em J).")
        esp = (f"Média mín. {fmt(media_min) or '-'} J; individual mín. {fmt(individual_min) or '-'} J; "
               f"temperatura de ensaio {_temperatura_charpy(temperatura)}; CP {corpo_prova}")  # fmt: skip
        titulo = "Relatório de Ensaio de Impacto Charpy (resultados do laboratório externo)"
        cab = ["Conjunto", "CP1 (J)", "CP2 (J)", "CP3 (J)", "Média (J)", "Resultado"]
        tabelas = [{"titulo": "Energia absorvida", "cab": cab, "linhas": linhas}]
    else:
        raise ErroFormulario("Escolha o ensaio: tração ou Charpy.")
    status = "reprovado" if ruim else ("aprovado" if validado else "pendente")
    resultado = {"reprovado": "REPROVADO", "aprovado": "APROVADO", "pendente": "AGUARDANDO VALIDAÇÃO"}[status]
    kv = [*lab, ("Especificação", esp), validador, ("Resultado", resultado)]
    return Resultado(status, rel(titulo, kv, tabelas, obs=_obs(campos)))


def p_dim(campos: dict, ficha: Ficha, sub: str) -> Resultado:
    linhas, ruim = [], False
    for i, linha in enumerate(lista(campos, "cotas"), 1):
        cadastrada = ficha.cotas.get(int(num(linha.get("cota_id")) or 0)) if linha.get("cota_id") else None
        if cadastrada:  # cota do cadastro do item: vale o que está cadastrado, não o que veio da tela
            descricao, nominal_txt, tmin_txt, tmax_txt = cadastrada.descricao, cadastrada.nominal, cadastrada.tol_min, cadastrada.tol_max
        else:
            descricao, nominal_txt = texto(linha, "descricao", 200), texto(linha, "nominal", 40)
            tmin_txt, tmax_txt = texto(linha, "tol_min", 40), texto(linha, "tol_max", 40)
        medidas_txt = texto(linha, "medidas", 2000)
        if not medidas_txt:
            continue  # cota não medida
        rotulo = descricao or f"cota da linha {i}"
        medidas = [num(t) for t in tokens(medidas_txt)]
        if None in medidas:
            raise ErroFormulario(f"{rotulo}: as medidas precisam ser números separados por ponto e vírgula (ex.: 12,02; 12,01).")
        nominal, t1, t2 = num(nominal_txt), num(tmin_txt), num(tmax_txt)
        if not descricao.strip() or nominal is None or t1 is None or t2 is None:
            raise ErroFormulario(f"{rotulo}: preencha a descrição, o nominal e as duas tolerâncias (números) para conferir as medidas.")
        baixo, alto = nominal + t1, nominal + t2
        ok = all(baixo <= v <= alto for v in medidas)
        ruim |= not ok
        linhas.append([descricao, fmt(nominal), f"{fmt(baixo)} a {fmt(alto)}", len(medidas), f"{min(medidas):g} / {max(medidas):g}",
                       "OK" if ok else "FORA"])  # fmt: skip
    if not linhas:
        raise ErroFormulario("Informe ao menos uma cota (descrição, nominal, tolerâncias e medidas).")
    kv = [("Instrumento(s)", texto(campos, "instrumento")), ("Certificado de calibração", texto(campos, "calib", 400)),
          ("Peças medidas", texto(campos, "amostra")), ("Resultado", "REPROVADO" if ruim else "APROVADO")]  # fmt: skip
    cab = ["Cota", "Nominal", "Faixa aceitável", "Nº med.", "Mín. / Máx.", "Resultado"]
    return Resultado(decisao(campos, ruim), rel(ficha.relatorio, kv, [{"titulo": "Cotas inspecionadas", "cab": cab, "linhas": linhas}],
                                                obs=_obs(campos)))  # fmt: skip


def p_lp(campos: dict, ficha: Ficha, sub: str) -> Resultado:
    inspecionadas = numero_digitado(campos, "qtd_insp", "Peças inspecionadas")
    indicacoes = numero_digitado(campos, "indicacoes", "Peças com indicação de trinca")
    if inspecionadas is None or indicacoes is None:
        raise ErroFormulario("Informe a quantidade inspecionada e a quantidade de peças com indicações.")
    if inspecionadas < 0 or indicacoes < 0:
        raise ErroFormulario("As quantidades não podem ser negativas.")
    ok = indicacoes == 0
    kv = [("Norma / procedimento", texto(campos, "norma")), ("Penetrante / lote", texto(campos, "penetrante")),
          ("Revelador / lote", texto(campos, "revelador")), ("Temperatura da peça", f"{texto(campos, 'temp', 20)} °C"),
          ("Tempo de penetração", f"{texto(campos, 't_pen', 20)} min"), ("Inspetor / nível", texto(campos, "inspetor")),
          ("Peças inspecionadas", f"{inspecionadas:g}"), ("Peças com indicação de trinca", f"{indicacoes:g}"),
          ("Resultado", "APROVADO - sem indicações relevantes" if ok else "REPROVADO - indicações detectadas")]  # fmt: skip
    descricao = texto(campos, "desc_ind", 1000)
    obs = _obs(campos) + (" | Indicações: " + descricao if descricao else "")
    return Resultado(decisao(campos, not ok), rel(ficha.relatorio, kv, obs=obs))


def p_simples(campos: dict, ficha: Ficha, sub: str) -> Resultado:
    ok = marcado(campos, "ok")
    kv = [("Tempo de processo", f"{texto(campos, 'tempo', 20)} min"), ("Mídia / abrasivo", texto(campos, "midia")),
          ("Rebarbas removidas / peças sem dano", "Sim" if ok else "Não")]  # fmt: skip
    return Resultado(decisao(campos, not ok), rel(ficha.relatorio, kv, obs=_obs(campos)))


def p_fosfato(campos: dict, ficha: Ficha, sub: str) -> Resultado:
    kv = [("Fornecedor", texto(campos, "fornecedor")), ("Certificado nº", texto(campos, "cert")),
          ("Data de envio", _data_br(texto(campos, "envio", 10))), ("Data de retorno", _data_br(texto(campos, "retorno", 10))),
          ("Espessura da camada", f"{texto(campos, 'esp', 20)} µm"), ("Quantidade recebida", texto(campos, "qtd_rec", 20))]  # fmt: skip
    return Resultado(decisao(campos, False), rel(ficha.relatorio, kv, obs=_obs(campos)))


def p_visual(campos: dict, ficha: Ficha, sub: str) -> Resultado:
    aprovadas = numero_digitado(campos, "qtd_aprov", "Peças aprovadas")
    reprovadas = numero_digitado(campos, "qtd_reprov", "Peças reprovadas") or 0
    ano, tri = texto(campos, "ano", 4), texto(campos, "tri", 1)
    if aprovadas is None or aprovadas < 0 or not ano or not tri:
        raise ErroFormulario("Informe quantidade aprovada, ano e trimestre.")
    if not re.fullmatch(r"\d{4}", ano) or tri not in ("1", "2", "3", "4"):
        raise ErroFormulario("O ano precisa ter 4 dígitos e o trimestre ser de 1 a 4.")
    if aprovadas > MAXIMO_PECAS_LASER:
        raise ErroFormulario(f"Quantidade aprovada grande demais (máximo {MAXIMO_PECAS_LASER:,}).".replace(",", "."))
    qtd = int(aprovadas)
    codigos = codigos_laser(ficha.laser_formato, ano, tri, ficha.corrida, ficha.numero, qtd)
    kv = [("Peças aprovadas na inspeção visual", qtd), ("Peças reprovadas", int(reprovadas)), ("Ano / trimestre", f"{ano} / T{tri}"),
          ("Formato da gravação", formato_laser_legivel(ficha.laser_formato)),
          ("Primeiro código gravado", codigos[0] if codigos else "-"), ("Último código gravado", codigos[-1] if codigos else "-"),
          ("Máquina laser / programa", texto(campos, "laser"))]  # fmt: skip
    report = rel(ficha.relatorio, kv, obs=_obs(campos))
    report["laser"] = codigos
    return Resultado(decisao(campos, qtd == 0), report)


def rotulo_parafusos(tipo: str) -> str:
    return "Parafusos M10x10mm / M10x12mm" if tipo == "ARK" else "Parafusos M6x1"


def p_embalagem(campos: dict, ficha: Ficha, sub: str) -> Resultado:
    quantidade = numero_digitado(campos, "qtd_emb", "Peças embaladas")
    parafusos = numero_digitado(campos, "parafusos", rotulo_parafusos(ficha.tipo))
    if quantidade is None or parafusos is None:
        raise ErroFormulario(f"Informe a quantidade embalada e a quantidade de {rotulo_parafusos(ficha.tipo).lower()}.")
    kv = [("Tipo de embalagem", texto(campos, "tipo_emb")), ("Peças embaladas", f"{quantidade:g}"),
          (f"{rotulo_parafusos(ficha.tipo)} incluídos", f"{parafusos:g}"), ("Volumes", texto(campos, "volumes", 40))]  # fmt: skip
    return Resultado(decisao(campos, False), rel(ficha.relatorio, kv, obs=_obs(campos)))


PARSERS = {
    "quimica": p_quimica, "tt": p_tt, "dureza": p_dureza, "lab": p_lab, "dim": p_dim, "lp": p_lp, "simples": p_simples,
    "fosfato": p_fosfato, "visual": p_visual, "embalagem": p_embalagem,
}  # fmt: skip
