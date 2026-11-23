"""Regras do fluxo de etapas, conferidas contra o comportamento do sistema antigo (legado/app.py)."""
from app import fluxo
from app.fluxo import CONCLUIDO, ETAPAS, POR_CHAVE, SituacaoSub

APROVADO = SituacaoSub("aprovado")


def estado_aprovado(tipo: str, ate: str | None = None) -> dict:
    """Todas as etapas aplicáveis aprovadas (ou só até a etapa `ate`, exclusive)."""
    estado = {}
    for e in ETAPAS:
        if ate and e.chave == ate:
            break
        if e.aplicavel(tipo):
            for s in e.subs_de(tipo):
                estado[(e.chave, s)] = APROVADO
    return estado


def test_ordem_das_etapas_e_a_do_sistema_antigo():
    # lotes.etapa guarda o índice: mudar a ordem bagunçaria os lotes migrados
    assert [e.chave for e in ETAPAS] == [
        "receb_mp", "trat_termico", "dureza", "lab_ext", "usinagem", "dim_final", "lp", "tambor", "fosfato", "visual", "embalagem",
    ]  # fmt: skip


def test_ark_pula_dureza_usinagem_e_tamboreamento_e_so_faz_charpy():
    nao_aplicaveis = {e.chave for e in ETAPAS if not e.aplicavel("ARK")}
    assert nao_aplicaveis == {"dureza", "usinagem", "tambor"}
    assert POR_CHAVE["lab_ext"].subs_de("ARK") == ("charpy",)
    assert POR_CHAVE["lab_ext"].subs_de("PIN") == ("tracao", "charpy")
    assert fluxo.progresso("ARK", {}) == (0, 8)
    assert fluxo.progresso("BOX", {}) == (0, 11)


def test_nomes_mudam_por_tipo():
    fosfato = POR_CHAVE["fosfato"]
    assert fosfato.curto_de("ARK") == "Oxidação Negra"
    assert fosfato.curto_de("PIN") == "Fosfato Mn"
    assert POR_CHAVE["embalagem"].nome_de("ARK") == "Embalagem e parafusos M10x10mm / M10x12mm"
    assert POR_CHAVE["lab_ext"].curto_de("ARK") == "Charpy"


def test_lote_novo_esta_no_recebimento_e_concluido_quando_tudo_aprova():
    assert fluxo.etapa_real("PIN", {}) == 0
    assert fluxo.etapa_real("PIN", estado_aprovado("PIN")) == CONCLUIDO
    assert fluxo.etapa_real("ARK", estado_aprovado("ARK")) == CONCLUIDO


def test_ark_vai_do_tratamento_termico_direto_para_o_charpy():
    estado = {("receb_mp", ""): APROVADO, ("trat_termico", ""): APROVADO}
    assert ETAPAS[fluxo.etapa_real("ARK", estado)].chave == "lab_ext"
    assert ETAPAS[fluxo.etapa_real("PIN", estado)].chave == "dureza"


def test_laboratorio_so_libera_com_tracao_e_charpy_aprovados():
    estado = estado_aprovado("PIN", ate="lab_ext") | {("lab_ext", "tracao"): APROVADO}
    assert ETAPAS[fluxo.etapa_real("PIN", estado)].chave == "lab_ext"
    estado[("lab_ext", "charpy")] = APROVADO
    assert ETAPAS[fluxo.etapa_real("PIN", estado)].chave == "usinagem"


def test_reprovacao_bloqueia_ate_a_nc_liberar():
    base = estado_aprovado("PIN", ate="dureza")
    casos = {
        SituacaoSub("reprovado"): False,  # registro antigo sem NC
        SituacaoSub("reprovado", "aberta", ""): False,
        SituacaoSub("reprovado", "em_tratamento", "retrabalho"): False,
        SituacaoSub("reprovado", "encerrada", "retrabalho"): False,  # retrabalho só libera com registro novo aprovado
        SituacaoSub("reprovado", "encerrada", "sucata"): True,
        SituacaoSub("reprovado", "encerrada", "uso_como_esta"): True,
        SituacaoSub("reprovado", "encerrada", "anulada"): True,
    }
    for situacao, libera in casos.items():
        estado = base | {("dureza", ""): situacao}
        passou = fluxo.etapa_real("PIN", estado) > fluxo.INDICE["dureza"]
        assert passou is libera, situacao


def test_nc_pendente_aparece_na_etapa():
    dureza = POR_CHAVE["dureza"]
    assert fluxo.nc_pendente_etapa(dureza, "PIN", {("dureza", ""): SituacaoSub("reprovado", "aberta", "")})
    assert fluxo.nc_pendente_etapa(dureza, "PIN", {("dureza", ""): SituacaoSub("reprovado")})
    assert not fluxo.nc_pendente_etapa(dureza, "PIN", {("dureza", ""): SituacaoSub("reprovado", "encerrada", "sucata")})
    assert not fluxo.nc_pendente_etapa(dureza, "PIN", {})


def test_cursor_passa_direto_por_etapa_que_nao_se_aplica():
    assert fluxo.pode_avancar(fluxo.INDICE["dureza"], "ARK", {})
    assert not fluxo.pode_avancar(fluxo.INDICE["dureza"], "PIN", {})
    assert not fluxo.pode_avancar(CONCLUIDO, "PIN", estado_aprovado("PIN"))


def test_situacao_de_cada_etapa_para_a_tela():
    estado = {("receb_mp", ""): APROVADO, ("trat_termico", ""): SituacaoSub("reprovado", "aberta", "")}
    real = fluxo.etapa_real("PIN", estado)
    situacoes = [fluxo.situacao_etapa(i, "PIN", estado, real) for i in range(4)]
    assert situacoes == ["aprovada", "reprovada", "futura", "futura"]
    assert fluxo.situacao_etapa(fluxo.INDICE["dureza"], "ARK", {}, 0) == "nao_aplicavel"
    assert fluxo.situacao_etapa(0, "PIN", {}, 0) == "atual"
